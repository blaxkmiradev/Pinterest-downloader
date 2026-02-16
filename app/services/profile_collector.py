from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from app.constants import HTTP_HEADERS, REQUEST_TIMEOUT_SECONDS
from app.utils.pinterest_urls import (
    canonical_pin_url,
    canonical_profile_url,
    extract_profile_username,
)
from app.utils.validation import is_valid_http_url, normalize_url

INITIAL_PROPS_SCRIPT_RE = re.compile(
    r'<script id="__PWS_INITIAL_PROPS__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
PIN_PATH_RE = re.compile(r"/pin/(\d+)/", re.IGNORECASE)


@dataclass(frozen=True)
class ProfileCollectionResult:
    profile_url: str
    profile_username: str
    pin_urls: list[str]
    discovered_count: int


class ProfileCollectionError(Exception):
    """Raised when profile pins cannot be fetched."""


class ProfilePinCollector:
    def __init__(self, timeout_seconds: int = REQUEST_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def collect_profile_pin_urls(
        self,
        profile_url: str,
        session: requests.Session | None = None,
        max_pins: int = 0,
    ) -> ProfileCollectionResult:
        normalized = normalize_url(profile_url)
        if not is_valid_http_url(normalized):
            raise ProfileCollectionError("Invalid profile URL format.")

        username = extract_profile_username(normalized)
        if not username:
            raise ProfileCollectionError("Could not detect Pinterest profile username from this URL.")

        canonical_profile = canonical_profile_url(username)
        active_session = session or requests.Session()

        response = active_session.get(
            canonical_profile,
            headers=HTTP_HEADERS,
            timeout=self.timeout_seconds,
            allow_redirects=True,
        )
        response.raise_for_status()

        initial_data = self._parse_initial_props(response.text)
        if not initial_data:
            raise ProfileCollectionError("Could not parse profile data from Pinterest page.")

        initial_entry = self._extract_user_pins_entry(initial_data)
        if not initial_entry:
            fallback = self._extract_pin_urls_from_html(response.text)
            if not fallback:
                raise ProfileCollectionError("No pins were detected on this profile.")
            deduped = self._dedupe_urls(fallback)
            if max_pins > 0:
                deduped = deduped[:max_pins]
            return ProfileCollectionResult(
                profile_url=canonical_profile,
                profile_username=username,
                pin_urls=deduped,
                discovered_count=len(deduped),
            )

        collected = self._extract_pin_urls_from_resource_data(initial_entry.get("data"))
        bookmark = initial_entry.get("nextBookmark")

        seen_bookmarks: set[str] = set()
        while self._can_continue_pagination(bookmark, max_pins, len(collected)):
            if bookmark in seen_bookmarks:
                break
            seen_bookmarks.add(bookmark)

            page_data, next_bookmark = self._fetch_user_pins_page(
                session=active_session,
                profile_username=username,
                profile_url=canonical_profile,
                bookmark=bookmark,
            )
            if not page_data:
                break

            collected.extend(self._extract_pin_urls_from_resource_data(page_data))
            bookmark = next_bookmark

        deduped = self._dedupe_urls(collected)
        if max_pins > 0:
            deduped = deduped[:max_pins]
        if not deduped:
            raise ProfileCollectionError("No downloadable pins found on this profile.")

        return ProfileCollectionResult(
            profile_url=canonical_profile,
            profile_username=username,
            pin_urls=deduped,
            discovered_count=len(deduped),
        )

    def _parse_initial_props(self, html_text: str) -> dict | None:
        match = INITIAL_PROPS_SCRIPT_RE.search(html_text)
        if not match:
            return None

        try:
            payload = json.loads(match.group(1))
        except ValueError:
            return None

        if not isinstance(payload, dict):
            return None
        return payload

    def _extract_user_pins_entry(self, initial_props: dict) -> dict | None:
        state = initial_props.get("initialReduxState")
        if not isinstance(state, dict):
            return None

        resources = state.get("resources")
        if not isinstance(resources, dict):
            return None

        user_pins_resource = resources.get("UserPinsResource")
        if not isinstance(user_pins_resource, dict) or not user_pins_resource:
            return None

        first_key = next(iter(user_pins_resource.keys()))
        entry = user_pins_resource.get(first_key)
        if isinstance(entry, dict):
            return entry
        return None

    def _extract_pin_urls_from_resource_data(self, rows: object) -> list[str]:
        if not isinstance(rows, list):
            return []

        urls: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            seo_url = row.get("seo_url")
            if isinstance(seo_url, str):
                match = PIN_PATH_RE.search(seo_url)
                if match:
                    urls.append(canonical_pin_url(match.group(1)))
                    continue

            pin_id = row.get("id")
            if isinstance(pin_id, str) and pin_id.isdigit():
                urls.append(canonical_pin_url(pin_id))

        return urls

    def _extract_pin_urls_from_html(self, html_text: str) -> list[str]:
        pin_ids = PIN_PATH_RE.findall(html_text)
        return [canonical_pin_url(pin_id) for pin_id in pin_ids]

    def _fetch_user_pins_page(
        self,
        session: requests.Session,
        profile_username: str,
        profile_url: str,
        bookmark: str,
    ) -> tuple[list[dict], str]:
        options = {
            "add_vase": True,
            "field_set_key": "mobile_grid_item",
            "is_own_profile_pins": False,
            "username": profile_username,
            "bookmarks": [bookmark],
        }
        payload = {"options": options, "context": {}}
        params = {
            "source_url": f"/{profile_username}/",
            "data": json.dumps(payload, separators=(",", ":")),
            "_": "1700000000000",
        }

        headers = dict(HTTP_HEADERS)
        headers.update(
            {
                "Referer": profile_url,
                "X-Requested-With": "XMLHttpRequest",
                "X-Pinterest-AppState": "active",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
        )

        csrf = session.cookies.get("csrftoken")
        if csrf:
            headers["X-CSRFToken"] = csrf

        response = session.post(
            "https://www.pinterest.com/resource/UserPinsResource/get/",
            params=params,
            headers=headers,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 403:
            return [], "-end-"
        response.raise_for_status()

        try:
            payload_json = response.json()
        except ValueError:
            return [], "-end-"

        resource_response = payload_json.get("resource_response")
        if not isinstance(resource_response, dict):
            return [], "-end-"

        data = resource_response.get("data")
        bookmark_value = resource_response.get("bookmark")
        if not isinstance(bookmark_value, str):
            bookmark_value = "-end-"

        if not isinstance(data, list):
            return [], bookmark_value

        typed_rows = [row for row in data if isinstance(row, dict)]
        return typed_rows, bookmark_value

    @staticmethod
    def _can_continue_pagination(bookmark: object, max_pins: int, current_count: int) -> bool:
        if max_pins > 0 and current_count >= max_pins:
            return False
        if not isinstance(bookmark, str):
            return False
        if not bookmark:
            return False
        if bookmark == "-end-":
            return False
        return True

    @staticmethod
    def _dedupe_urls(urls: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for url in urls:
            normalized = urlparse(url)._replace(query="", fragment="").geturl()
            if normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        return deduped

