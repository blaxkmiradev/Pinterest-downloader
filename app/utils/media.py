from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".avif",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".webm",
    ".m4v",
    ".avi",
    ".mkv",
    ".3gp",
}

NON_MEDIA_EXTENSIONS = {
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".css",
    ".js",
}

SIZE_SEGMENT_RE = re.compile(r"^\d+x\d*$")


def infer_media_type_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path.lower()
    suffix = Path(path).suffix.lower()

    if suffix in NON_MEDIA_EXTENSIONS:
        return None
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS or "/videos/" in path:
        return "video"

    if "pinimg.com" in parsed.netloc.lower():
        segments = [segment for segment in path.split("/") if segment]
        if not segments:
            return None
        first_segment = segments[0]
        if first_segment == "originals" or SIZE_SEGMENT_RE.match(first_segment):
            return "image"
        if first_segment.endswith("x_rs") and suffix in IMAGE_EXTENSIONS:
            return "image"
        return None
    return None


def infer_media_type_from_path(path_value: str) -> str | None:
    suffix = Path(path_value).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return None
