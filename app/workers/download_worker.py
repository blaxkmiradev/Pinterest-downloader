from __future__ import annotations

from pathlib import Path

import requests
from PyQt5.QtCore import QObject, pyqtSignal

from app.services.downloader import DownloadError, MediaDownloader
from app.services.pinterest_resolver import MediaCandidate, PinterestResolver, ResolutionError
from app.services.profile_collector import ProfileCollectionError, ProfilePinCollector
from app.utils.pinterest_urls import is_profile_url


class DownloadWorker(QObject):
    queue_prepared = pyqtSignal(object)
    progress_changed = pyqtSignal(int, int)
    row_updated = pyqtSignal(object)
    completed = pyqtSignal(object)
    crashed = pyqtSignal(str)

    def __init__(
        self,
        source_urls: list[str],
        output_dir: str,
        max_profile_pins: int = 0,
    ) -> None:
        super().__init__()
        self.source_urls = source_urls
        self.output_dir = output_dir
        self.max_profile_pins = max_profile_pins
        self.profile_collector = ProfilePinCollector()
        self.resolver = PinterestResolver()
        self.downloader = MediaDownloader()
        self._cancelled = False

    def stop(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            with requests.Session() as session:
                queue_payload = self._build_download_queue(session=session)
                pin_urls = queue_payload["pin_urls"]
                self.queue_prepared.emit(queue_payload)

                total = len(pin_urls)
                success_count = 0
                failed_count = 0
                self.progress_changed.emit(0, total)

                if total == 0:
                    summary = {
                        "total": 0,
                        "success": 0,
                        "failed": 0,
                        "cancelled": self._cancelled,
                        "queue_notes": queue_payload.get("notes", []),
                    }
                    self.completed.emit(summary)
                    return

                for index, pin_url in enumerate(pin_urls, start=1):
                    if self._cancelled:
                        break

                    self.row_updated.emit(
                        {
                            "index": index,
                            "pin_url": pin_url,
                            "status": "Processing",
                            "saved_path": "",
                            "media_url": "",
                            "media_type": "",
                            "error": "",
                        }
                    )

                    try:
                        saved_path, media_candidate = self._download_single(
                            pin_url=pin_url,
                            row_index=index,
                            session=session,
                        )
                        success_count += 1
                        self.row_updated.emit(
                            {
                                "index": index,
                                "pin_url": pin_url,
                                "status": "Downloaded",
                                "saved_path": str(saved_path),
                                "media_url": media_candidate.url,
                                "media_type": media_candidate.media_type,
                                "error": "",
                            }
                        )
                    except (ResolutionError, DownloadError, requests.RequestException) as exc:
                        failed_count += 1
                        self.row_updated.emit(
                            {
                                "index": index,
                                "pin_url": pin_url,
                                "status": "Failed",
                                "saved_path": "",
                                "media_url": "",
                                "media_type": "",
                                "error": str(exc),
                            }
                        )

                    self.progress_changed.emit(index, total)

                summary = {
                    "total": total,
                    "success": success_count,
                    "failed": failed_count,
                    "cancelled": self._cancelled,
                    "queue_notes": queue_payload.get("notes", []),
                    "discovered": queue_payload.get("discovered", 0),
                }
                self.completed.emit(summary)
        except Exception as exc:  # pragma: no cover - defensive fallback
            self.crashed.emit(str(exc))

    def _build_download_queue(self, session: requests.Session) -> dict:
        expanded_pin_urls: list[str] = []
        notes: list[str] = []
        discovered_total = 0

        for source_url in self.source_urls:
            if self._cancelled:
                break

            if not is_profile_url(source_url):
                expanded_pin_urls.append(source_url)
                continue

            try:
                result = self.profile_collector.collect_profile_pin_urls(
                    profile_url=source_url,
                    session=session,
                    max_pins=self.max_profile_pins,
                )
                expanded_pin_urls.extend(result.pin_urls)
                discovered_total += result.discovered_count
                notes.append(
                    f"Profile @{result.profile_username}: discovered {result.discovered_count} pin(s)."
                )
            except (ProfileCollectionError, requests.RequestException) as exc:
                notes.append(f"Profile scan failed ({source_url}): {exc}")

        deduped = self._dedupe_urls(expanded_pin_urls)
        return {
            "pin_urls": deduped,
            "notes": notes,
            "discovered": discovered_total,
        }

    def _download_single(
        self,
        pin_url: str,
        row_index: int,
        session: requests.Session,
    ) -> tuple[Path, MediaCandidate]:
        candidate_media = self.resolver.resolve_media_candidates(pin_url, session=session)

        last_error = ""
        for candidate in candidate_media:
            try:
                saved_path = self.downloader.download(
                    media_url=candidate.url,
                    output_dir=self.output_dir,
                    session=session,
                    filename_prefix=f"pin_{row_index:03d}",
                )
                return saved_path, candidate
            except (DownloadError, requests.RequestException) as exc:
                last_error = str(exc)
                continue

        raise DownloadError(last_error or "No downloadable media candidate found.")

    @staticmethod
    def _dedupe_urls(urls: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in urls:
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        return deduped

