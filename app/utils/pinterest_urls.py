from __future__ import annotations

import re
from urllib.parse import urlparse

PINTEREST_HOST_RE = re.compile(r"(?:^|\.)pinterest\.[a-z.]+$", re.IGNORECASE)
PIN_PATH_RE = re.compile(r"^/pin/\d+/?$", re.IGNORECASE)
PIN_SHORT_HOSTS = {"pin.it"}
RESERVED_PROFILE_SEGMENTS = {
    "",
    "pin",
    "pins",
    "search",
    "ideas",
    "explore",
    "discover",
    "categories",
    "business",
    "about",
    "help",
    "privacy",
    "settings",
    "login",
    "signup",
    "create",
    "shop",
    "_",
}


def is_pinterest_host(host: str) -> bool:
    host_value = host.lower().strip()
    if not host_value:
        return False
    if host_value in PIN_SHORT_HOSTS:
        return True
    return bool(PINTEREST_HOST_RE.search(host_value))


def is_pin_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in PIN_SHORT_HOSTS:
        return True
    if not is_pinterest_host(host):
        return False
    return bool(PIN_PATH_RE.match(parsed.path))


def extract_profile_username(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not is_pinterest_host(host):
        return None
    if host in PIN_SHORT_HOSTS:
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return None

    username = segments[0].strip().lower()
    if username in RESERVED_PROFILE_SEGMENTS:
        return None
    if username.startswith("_"):
        return None
    return username


def is_profile_url(url: str) -> bool:
    if is_pin_url(url):
        return False
    return extract_profile_username(url) is not None


def canonical_profile_url(username: str) -> str:
    return f"https://www.pinterest.com/{username}/"


def canonical_pin_url(pin_id: str) -> str:
    return f"https://www.pinterest.com/pin/{pin_id}/"

