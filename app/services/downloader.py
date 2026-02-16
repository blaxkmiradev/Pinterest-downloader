from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from app.constants import (
    HTTP_HEADERS,
    IMAGE_CONTENT_TYPE_TO_EXT,
    REQUEST_TIMEOUT_SECONDS,
    VIDEO_CONTENT_TYPE_TO_EXT,
)
from app.utils.media import infer_media_type_from_url
from app.utils.paths import ensure_directory, sanitize_filename, unique_path

CONTENT_TYPE_TO_EXT = {**IMAGE_CONTENT_TYPE_TO_EXT, **VIDEO_CONTENT_TYPE_TO_EXT}


class DownloadError(Exception):
    """Raised when a media file cannot be downloaded."""


class MediaDownloader:
    def __init__(self, timeout_seconds: int = REQUEST_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def download(
        self,
        media_url: str,
        output_dir: str | Path,
        session: requests.Session | None = None,
        filename_prefix: str = "",
    ) -> Path:
        destination = ensure_directory(output_dir)
        active_session = session or requests.Session()

        response = active_session.get(
            media_url,
            headers=HTTP_HEADERS,
            timeout=self.timeout_seconds,
            stream=True,
        )
        response.raise_for_status()

        filename = self._build_filename(
            media_url=media_url,
            content_type=response.headers.get("Content-Type", ""),
            prefix=filename_prefix,
        )
        path = unique_path(destination / filename)

        try:
            with path.open("wb") as file_handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        file_handle.write(chunk)
        except OSError as exc:
            raise DownloadError(f"Failed to write file: {exc}") from exc

        return path

    def _build_filename(self, media_url: str, content_type: str, prefix: str) -> str:
        parsed = urlparse(media_url)
        basename = unquote(Path(parsed.path).name)

        candidate_stem = Path(basename).stem if basename else "pinterest_media"
        stem = sanitize_filename(candidate_stem)
        if prefix:
            stem = sanitize_filename(f"{prefix}_{stem}")

        extension = self._detect_extension(media_url, basename, content_type)
        return f"{stem}{extension}"

    def _detect_extension(self, media_url: str, basename: str, content_type: str) -> str:
        suffix = Path(basename).suffix.lower()
        if suffix:
            return ".jpg" if suffix == ".jpeg" else suffix

        ct = content_type.split(";")[0].strip().lower()
        if ct in CONTENT_TYPE_TO_EXT:
            return CONTENT_TYPE_TO_EXT[ct]

        media_type = infer_media_type_from_url(media_url)
        if media_type == "video":
            return ".mp4"
        return ".jpg"


# Backward-compatible alias for imports that still use the old class name.
ImageDownloader = MediaDownloader

