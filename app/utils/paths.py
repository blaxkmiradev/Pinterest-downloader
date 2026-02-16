from __future__ import annotations

import re
from pathlib import Path

INVALID_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")


def ensure_directory(path_value: str | Path) -> Path:
    directory = Path(path_value).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def sanitize_filename(name: str, max_length: int = 96) -> str:
    cleaned = INVALID_FILENAME_CHARS_RE.sub("_", name.strip())
    cleaned = cleaned.strip("._ ")
    if not cleaned:
        cleaned = "image"
    return cleaned[:max_length]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1

