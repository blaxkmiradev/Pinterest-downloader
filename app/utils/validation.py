from __future__ import annotations

from urllib.parse import urlparse


def normalize_url(raw_url: str) -> str:
    url = raw_url.strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    return url


def is_valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def parse_url_lines(text: str) -> tuple[list[str], list[str]]:
    valid_urls: list[str] = []
    invalid_entries: list[str] = []
    seen: set[str] = set()

    for line in text.splitlines():
        item = line.strip()
        if not item:
            continue

        normalized = normalize_url(item)
        if not is_valid_http_url(normalized):
            invalid_entries.append(item)
            continue

        if normalized not in seen:
            valid_urls.append(normalized)
            seen.add(normalized)

    return valid_urls, invalid_entries

