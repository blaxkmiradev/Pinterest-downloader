from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlparse

import requests

from app.constants import HTTP_HEADERS, PINTEREST_IMAGE_HOST, REQUEST_TIMEOUT_SECONDS
from app.utils.media import infer_media_type_from_url
from app.utils.validation import is_valid_http_url, normalize_url

SIZE_SEGMENT_RE = re.compile(r"^\d+x\d*$")
PIN_ID_PATH_RE = re.compile(r"/pin/(\d+)/?")
OEMBED_PIN_ID_RE = re.compile(r"[?&]id=(\d+)")
VIDEO_RESOLUTION_RE = re.compile(r"/(\d{3,4})p(?:/|$)")

META_IMAGE_PATTERNS = (
    re.compile(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)',
        re.IGNORECASE,
    ),
)

LD_JSON_PATTERN = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)

HOSTED_MEDIA_PATTERN = re.compile(
    r'https?:\\\\/\\\\/(?:[a-z0-9-]+\.)?pinimg\.com[^"\'<>\s)\]}]+|'
    r'https?://(?:[a-z0-9-]+\.)?pinimg\.com[^"\'<>\s)\]}]+',
    re.IGNORECASE,
)

NORMALIZED_URL_RE = re.compile(r'^https?://[^\s"\'<>)\]}]+', re.IGNORECASE)


@dataclass(frozen=True)
class MediaCandidate:
    url: str
    media_type: str
    quality_score: int
    source: str = ""


class ResolutionError(Exception):
    """Raised when a Pinterest URL cannot be mapped to downloadable media."""


class PinterestResolver:
    def __init__(self, timeout_seconds: int = REQUEST_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def resolve_media_candidates(
        self,
        pin_url: str,
        session: requests.Session | None = None,
    ) -> list[MediaCandidate]:
        normalized = normalize_url(pin_url)
        if not is_valid_http_url(normalized):
            raise ResolutionError("Invalid URL format.")

        parsed = urlparse(normalized)
        direct_media_type = infer_media_type_from_url(normalized)
        if self._is_pinimg_host(parsed.netloc) and direct_media_type:
            candidates = self._build_candidates(
                normalized,
                direct_media_type,
                source="direct",
                size_hint="orig",
            )
            return self._sort_and_dedupe(candidates)

        active_session = session or requests.Session()
        response = active_session.get(
            normalized,
            headers=HTTP_HEADERS,
            timeout=self.timeout_seconds,
            allow_redirects=True,
        )
        response.raise_for_status()

        final_url = response.url
        final_media_type = infer_media_type_from_url(final_url)
        if self._is_pinimg_host(urlparse(final_url).netloc) and final_media_type:
            candidates = self._build_candidates(
                final_url,
                final_media_type,
                source="redirect",
                size_hint="orig",
            )
            return self._sort_and_dedupe(candidates)

        pin_id = self._extract_pin_id(final_url)
        if not pin_id:
            pin_id = self._extract_pin_id(normalized)
        if not pin_id:
            pin_id = self._extract_pin_id(response.text)
        if not pin_id:
            pin_id = self._resolve_pin_id_via_oembed(final_url, active_session)

        api_candidates: list[MediaCandidate] = []
        if pin_id:
            api_candidates = self._fetch_pin_api_candidates(pin_id, active_session)
        if api_candidates:
            return self._sort_and_dedupe(api_candidates)

        html_candidates = self._extract_html_candidates(response.text, final_url)
        html_candidates.extend(self._fetch_oembed_media_candidates(final_url, active_session))

        deduped = self._sort_and_dedupe(html_candidates)
        preferred_hosts = {"i.pinimg.com", "v1.pinimg.com"}
        preferred = [
            item
            for item in deduped
            if item.media_type == "video" or urlparse(item.url).netloc.lower() in preferred_hosts
        ]
        if preferred:
            deduped = preferred
        if not deduped:
            raise ResolutionError("Could not detect image or video media on this Pinterest page.")
        return deduped

    def resolve_image_urls(
        self,
        pin_url: str,
        session: requests.Session | None = None,
    ) -> list[str]:
        media_candidates = self.resolve_media_candidates(pin_url, session=session)
        image_urls = [item.url for item in media_candidates if item.media_type == "image"]
        if not image_urls:
            raise ResolutionError("No downloadable image found for this URL.")
        return image_urls

    def _fetch_pin_api_candidates(
        self,
        pin_id: str,
        session: requests.Session,
    ) -> list[MediaCandidate]:
        endpoint = f"https://api.pinterest.com/v3/pidgets/pins/info/?pin_ids={pin_id}"
        try:
            response = session.get(
                endpoint,
                headers=HTTP_HEADERS,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return []

        data = payload.get("data")
        if not isinstance(data, list) or not data:
            return []

        pin_data = data[0]
        if not isinstance(pin_data, dict):
            return []

        base_url = f"https://www.pinterest.com/pin/{pin_id}/"
        candidates: list[MediaCandidate] = []

        images = pin_data.get("images")
        if isinstance(images, dict):
            for size_key, details in images.items():
                if isinstance(details, dict):
                    raw_url = details.get("url")
                    if isinstance(raw_url, str):
                        normalized = self._normalize_candidate(raw_url, base_url)
                        if normalized and not self._is_placeholder_image(normalized):
                            candidates.extend(
                                self._build_candidates(
                                    normalized,
                                    "image",
                                    source="api-images",
                                    size_hint=str(size_key),
                                )
                            )

        videos = pin_data.get("videos")
        if videos is not None:
            candidates.extend(
                self._extract_candidates_from_object(
                    videos,
                    base_url=base_url,
                    source="api-videos",
                    media_type_hint="video",
                )
            )

        story_pin_data = pin_data.get("story_pin_data")
        if story_pin_data is not None:
            candidates.extend(
                self._extract_candidates_from_object(
                    story_pin_data,
                    base_url=base_url,
                    source="api-story",
                    media_type_hint=None,
                )
            )

        if pin_data.get("is_video"):
            candidates.extend(
                self._extract_candidates_from_object(
                    pin_data,
                    base_url=base_url,
                    source="api-fallback",
                    media_type_hint="video",
                )
            )

        return self._sort_and_dedupe(candidates)

    def _extract_html_candidates(self, html_text: str, base_url: str) -> list[MediaCandidate]:
        candidates: list[MediaCandidate] = []

        for pattern in META_IMAGE_PATTERNS:
            for match in pattern.finditer(html_text):
                normalized = self._normalize_candidate(match.group(1), base_url)
                if normalized and not self._is_placeholder_image(normalized):
                    candidates.extend(
                        self._build_candidates(
                            normalized,
                            "image",
                            source="meta",
                            size_hint="meta",
                        )
                    )

        ldjson_candidates = self._extract_ldjson_candidates(html_text, base_url)
        if ldjson_candidates:
            candidates.extend(ldjson_candidates)

        if candidates:
            return self._sort_and_dedupe(candidates)

        for match in HOSTED_MEDIA_PATTERN.finditer(html_text):
            normalized = self._normalize_candidate(match.group(0), base_url)
            if not normalized:
                continue

            media_type = infer_media_type_from_url(normalized)
            if not media_type:
                continue
            if media_type == "image" and self._is_placeholder_image(normalized):
                continue

            candidates.extend(
                self._build_candidates(
                    normalized,
                    media_type,
                    source="html-regex",
                    size_hint="",
                )
            )

        return self._sort_and_dedupe(candidates)

    def _extract_ldjson_candidates(self, html_text: str, base_url: str) -> list[MediaCandidate]:
        candidates: list[MediaCandidate] = []
        for match in LD_JSON_PATTERN.finditer(html_text):
            raw_json = match.group(1).strip()
            if not raw_json:
                continue

            try:
                payload = json.loads(raw_json)
            except ValueError:
                continue

            candidates.extend(
                self._extract_candidates_from_object(
                    payload,
                    base_url=base_url,
                    source="ldjson",
                    media_type_hint=None,
                )
            )

        return self._sort_and_dedupe(candidates)

    def _fetch_oembed_media_candidates(
        self,
        page_url: str,
        session: requests.Session,
    ) -> list[MediaCandidate]:
        oembed_url = f"https://www.pinterest.com/oembed.json?url={quote(page_url, safe='')}"
        try:
            response = session.get(
                oembed_url,
                headers=HTTP_HEADERS,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return []

        candidates: list[MediaCandidate] = []
        for key in ("thumbnail_url", "url"):
            value = payload.get(key)
            if isinstance(value, str):
                normalized = self._normalize_candidate(value, page_url)
                if not normalized:
                    continue
                media_type = infer_media_type_from_url(normalized)
                if media_type == "image" and self._is_placeholder_image(normalized):
                    continue
                if media_type:
                    candidates.extend(
                        self._build_candidates(
                            normalized,
                            media_type,
                            source=f"oembed-{key}",
                            size_hint=key,
                        )
                    )

        return self._sort_and_dedupe(candidates)

    def _resolve_pin_id_via_oembed(self, page_url: str, session: requests.Session) -> str | None:
        oembed_url = f"https://www.pinterest.com/oembed.json?url={quote(page_url, safe='')}"
        try:
            response = session.get(
                oembed_url,
                headers=HTTP_HEADERS,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return None

        html_embed = payload.get("html")
        if isinstance(html_embed, str):
            match = OEMBED_PIN_ID_RE.search(html_embed)
            if match:
                return match.group(1)
        return None

    def _extract_candidates_from_object(
        self,
        payload: object,
        base_url: str,
        source: str,
        media_type_hint: str | None,
    ) -> list[MediaCandidate]:
        candidates: list[MediaCandidate] = []

        def walk(value: object, key_hint: str = "") -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    walk(nested, key_hint=str(key))
                return
            if isinstance(value, list):
                for nested in value:
                    walk(nested, key_hint=key_hint)
                return
            if not isinstance(value, str):
                return
            if "http" not in value and "\\/" not in value:
                return

            normalized = self._normalize_candidate(value, base_url)
            if not normalized:
                return

            media_type = infer_media_type_from_url(normalized)
            if not media_type:
                return
            if media_type_hint and media_type != media_type_hint:
                return
            if media_type == "image" and self._is_placeholder_image(normalized):
                return

            candidates.extend(
                self._build_candidates(
                    normalized,
                    media_type,
                    source=source,
                    size_hint=key_hint,
                )
            )

        walk(payload)
        return self._sort_and_dedupe(candidates)

    def _build_candidates(
        self,
        url: str,
        media_type: str,
        source: str,
        size_hint: str,
    ) -> list[MediaCandidate]:
        if media_type == "image":
            variants = self._pinimg_variants(url)
            return [
                MediaCandidate(
                    url=variant,
                    media_type="image",
                    quality_score=self._score_image(variant, size_hint),
                    source=source,
                )
                for variant in variants
            ]

        return [
            MediaCandidate(
                url=url,
                media_type="video",
                quality_score=self._score_video(url, size_hint),
                source=source,
            )
        ]

    def _normalize_candidate(self, value: str, base_url: str) -> str | None:
        candidate = html.unescape(value.strip())
        if not candidate:
            return None

        candidate = (
            candidate.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u0026", "&")
            .replace("&amp;", "&")
        )
        candidate = candidate.strip("\"' ),")

        if candidate.startswith("//"):
            candidate = f"https:{candidate}"
        candidate = urljoin(base_url, candidate)
        candidate = candidate.rstrip(".,;")

        match = NORMALIZED_URL_RE.match(candidate)
        if not match:
            return None
        candidate = match.group(0)

        if not is_valid_http_url(candidate):
            return None

        return candidate

    def _pinimg_variants(self, url: str) -> list[str]:
        parsed = urlparse(url)
        if not self._is_pinimg_host(parsed.netloc):
            return [url]

        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments:
            return [url]

        variants = [url]
        first_segment = segments[0]
        if first_segment != "originals" and SIZE_SEGMENT_RE.match(first_segment):
            rebuilt_path = "/" + "/".join(["originals", *segments[1:]])
            variants.insert(0, parsed._replace(path=rebuilt_path).geturl())

        return self._dedupe_url_list(variants)

    def _score_image(self, url: str, size_hint: str) -> int:
        path = urlparse(url).path.lower()
        score = 1000

        if "/originals/" in path or size_hint.lower() == "orig":
            score += 9000

        segments = [segment for segment in path.split("/") if segment]
        if segments:
            match = SIZE_SEGMENT_RE.match(segments[0])
            if match:
                width_text, _, height_text = segments[0].partition("x")
                width = int(width_text) if width_text.isdigit() else 0
                height = int(height_text) if height_text.isdigit() else width
                score += width + height

        if "75x75_rs" in path or "facebook_share_image" in path:
            score -= 6000
        if "/images/" in path and "/originals/" not in path:
            score -= 3000

        if self._is_pinimg_host(urlparse(url).netloc):
            score += 300

        return score

    def _score_video(self, url: str, size_hint: str) -> int:
        path = urlparse(url).path.lower()
        score = 20000

        match = VIDEO_RESOLUTION_RE.search(path)
        if match:
            score += int(match.group(1))

        if path.endswith(".mp4"):
            score += 500
        if path.endswith(".m3u8"):
            score -= 300
        if "hls" in path:
            score -= 150
        if size_hint and size_hint.lower().endswith("p"):
            digits = re.sub(r"\D", "", size_hint)
            if digits.isdigit():
                score += int(digits)

        return score

    @staticmethod
    def _extract_pin_id(text: str) -> str | None:
        match = PIN_ID_PATH_RE.search(text)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _is_pinimg_host(host: str) -> bool:
        host_value = host.lower()
        return host_value == PINTEREST_IMAGE_HOST or host_value.endswith(".pinimg.com")

    @staticmethod
    def _is_placeholder_image(url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.lower()

        if "facebook_share_image" in path:
            return True
        if "/images/" in path and "/originals/" not in path:
            return True
        return False

    @staticmethod
    def _dedupe_url_list(values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        return deduped

    def _sort_and_dedupe(self, candidates: list[MediaCandidate]) -> list[MediaCandidate]:
        by_key: dict[tuple[str, str], MediaCandidate] = {}
        for item in candidates:
            key = (item.media_type, item.url)
            existing = by_key.get(key)
            if not existing or item.quality_score > existing.quality_score:
                by_key[key] = item

        ranked = list(by_key.values())
        ranked.sort(key=lambda item: item.quality_score, reverse=True)
        return ranked
