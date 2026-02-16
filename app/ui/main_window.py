from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt, QThread, QTimer, QUrl
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtGui import QBrush, QCloseEvent, QColor, QDesktopServices, QPixmap
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.constants import APP_NAME, APP_VERSION
from app.utils.media import infer_media_type_from_path
from app.utils.paths import ensure_directory
from app.utils.validation import parse_url_lines
from app.workers.download_worker import DownloadWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker_thread: QThread | None = None
        self.worker: DownloadWorker | None = None

        self.row_results: dict[int, dict[str, Any]] = {}
        self.row_states: dict[int, str] = {}
        self.current_urls: list[str] = []
        self._preview_pixmap = QPixmap()
        self._current_preview_path: str = ""
        self.media_player = QMediaPlayer(self)
        self.media_player.error.connect(self._handle_preview_player_error)

        self._build_ui()
        self.media_player.setVideoOutput(self.video_widget)
        self.media_player.stateChanged.connect(self._on_player_state_changed)
        self.media_player.mediaStatusChanged.connect(self._on_player_media_status_changed)
        self._set_default_output_directory()
        self._refresh_stats()

    def _build_ui(self) -> None:
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1260, 780)
        self.setMinimumSize(1080, 700)

        root_widget = QWidget()
        root_widget.setObjectName("rootWidget")
        self.setCentralWidget(root_widget)

        root_layout = QHBoxLayout(root_widget)
        root_layout.setContentsMargins(22, 22, 22, 22)
        root_layout.setSpacing(16)

        left_panel = QFrame()
        left_panel.setObjectName("panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(14)

        hero_card = QFrame()
        hero_card.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero_card)
        hero_layout.setContentsMargins(16, 16, 16, 16)
        hero_layout.setSpacing(6)

        hero_title = QLabel(APP_NAME)
        hero_title.setObjectName("heroTitle")
        hero_subtitle = QLabel(
            "Paste pin URLs or profile URLs to download high-quality images and videos."
        )
        hero_subtitle.setObjectName("heroSubtitle")
        hero_subtitle.setWordWrap(True)
        hero_meta = QLabel("Open Source Release by K-SEC - rikixz.com")
        hero_meta.setObjectName("heroMeta")

        hero_layout.addWidget(hero_title)
        hero_layout.addWidget(hero_subtitle)
        hero_layout.addWidget(hero_meta)
        left_layout.addWidget(hero_card)

        input_card = QFrame()
        input_card.setObjectName("card")
        input_layout = QVBoxLayout(input_card)
        input_layout.setContentsMargins(14, 14, 14, 14)
        input_layout.setSpacing(8)

        input_label = QLabel("Pinterest Links (pin or profile, one URL per line)")
        input_label.setObjectName("sectionLabel")
        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText(
            "https://www.pinterest.com/pin/123456789012345678/\n"
            "https://www.pinterest.com/pinterest/"
        )
        self.url_input.setMinimumHeight(185)

        input_layout.addWidget(input_label)
        input_layout.addWidget(self.url_input)
        left_layout.addWidget(input_card, 1)

        folder_card = QFrame()
        folder_card.setObjectName("card")
        folder_layout = QVBoxLayout(folder_card)
        folder_layout.setContentsMargins(14, 14, 14, 14)
        folder_layout.setSpacing(8)

        folder_label = QLabel("Save Folder")
        folder_label.setObjectName("sectionLabel")

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.output_dir_input = QLineEdit()
        self.browse_button = QPushButton("Browse")
        self.browse_button.clicked.connect(self._choose_output_directory)

        folder_row.addWidget(self.output_dir_input, 1)
        folder_row.addWidget(self.browse_button)
        folder_layout.addWidget(folder_label)
        folder_layout.addLayout(folder_row)
        left_layout.addWidget(folder_card)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.start_button = QPushButton("Download Media")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start_download)

        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._clear_form)

        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.clicked.connect(self._open_output_directory)

        action_row.addWidget(self.start_button, 2)
        action_row.addWidget(self.clear_button, 1)
        action_row.addWidget(self.open_folder_button, 1)
        left_layout.addLayout(action_row)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(8)
        total_card, self.total_value = self._create_stat_card("Total")
        success_card, self.success_value = self._create_stat_card("Success")
        failed_card, self.failed_value = self._create_stat_card("Failed")
        stats_row.addWidget(total_card)
        stats_row.addWidget(success_card)
        stats_row.addWidget(failed_card)
        left_layout.addLayout(stats_row)

        right_panel = QFrame()
        right_panel.setObjectName("panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(14)

        table_card = QFrame()
        table_card.setObjectName("card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(14, 14, 14, 14)
        table_layout.setSpacing(8)

        table_title = QLabel("Download Queue")
        table_title.setObjectName("sectionLabel")

        self.result_table = QTableWidget(0, 5)
        self.result_table.setHorizontalHeaderLabels(
            ["#", "Pinterest URL", "Status", "Type", "Saved File"]
        )
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.result_table.setSelectionMode(QTableWidget.SingleSelection)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.itemSelectionChanged.connect(self._update_preview_from_selection)

        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)

        table_layout.addWidget(table_title)
        table_layout.addWidget(self.result_table)
        right_layout.addWidget(table_card, 4)

        preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(14, 14, 14, 14)
        preview_layout.setSpacing(10)

        preview_title = QLabel("Media Preview")
        preview_title.setObjectName("sectionLabel")

        self.preview_stack = QStackedWidget()
        self.preview_stack.setObjectName("previewStack")
        self.preview_stack.setMinimumHeight(260)

        self.preview_message_label = QLabel("Select a downloaded row to preview image or video.")
        self.preview_message_label.setObjectName("previewLabel")
        self.preview_message_label.setAlignment(Qt.AlignCenter)
        self.preview_message_label.setWordWrap(True)

        self.preview_image_label = QLabel()
        self.preview_image_label.setObjectName("previewLabel")
        self.preview_image_label.setAlignment(Qt.AlignCenter)
        self.preview_image_label.setWordWrap(True)

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("previewVideo")

        self.preview_stack.addWidget(self.preview_message_label)
        self.preview_stack.addWidget(self.preview_image_label)
        self.preview_stack.addWidget(self.video_widget)

        video_controls = QHBoxLayout()
        video_controls.setSpacing(8)

        self.play_pause_button = QPushButton("Play")
        self.play_pause_button.clicked.connect(self._toggle_video_playback)
        self.play_pause_button.setVisible(False)

        self.stop_video_button = QPushButton("Stop")
        self.stop_video_button.clicked.connect(self._stop_video_preview)
        self.stop_video_button.setVisible(False)

        video_controls.addWidget(self.play_pause_button)
        video_controls.addWidget(self.stop_video_button)
        video_controls.addStretch(1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("statusLabel")

        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(self.preview_stack, 1)
        preview_layout.addLayout(video_controls)
        preview_layout.addWidget(self.progress_bar)
        preview_layout.addWidget(self.status_label)
        right_layout.addWidget(preview_card, 3)

        root_layout.addWidget(left_panel, 2)
        root_layout.addWidget(right_panel, 3)

    def _create_stat_card(self, title: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setObjectName("statCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("statTitle")
        value_label = QLabel("0")
        value_label.setObjectName("statValue")

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return card, value_label

    def _set_default_output_directory(self) -> None:
        default_path = Path.home() / "Downloads" / "PinterestDownloads"
        self.output_dir_input.setText(str(default_path))

    def _choose_output_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Choose Download Folder",
            self.output_dir_input.text().strip() or str(Path.home()),
        )
        if selected:
            self.output_dir_input.setText(selected)

    def _open_output_directory(self) -> None:
        path_text = self.output_dir_input.text().strip()
        if not path_text:
            return

        directory = ensure_directory(path_text)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _clear_form(self) -> None:
        self._stop_video_preview(clear_media=True)
        self.url_input.clear()
        self._reset_results_table()
        self.current_urls = []
        self.row_states = {}
        self.row_results = {}
        self._refresh_stats()
        self.status_label.setText("Ready")
        self.status_label.setToolTip("")
        self.progress_bar.setValue(0)
        self._set_preview_message("Select a downloaded row to preview image or video.")

    def _start_download(self) -> None:
        if self.worker_thread and self.worker_thread.isRunning():
            return

        urls, invalid_entries = parse_url_lines(self.url_input.toPlainText())
        if not urls:
            message = "Add at least one valid URL."
            if invalid_entries:
                message = f"No valid URLs detected. Invalid lines: {len(invalid_entries)}"
            QMessageBox.warning(self, "No URLs", message)
            return

        requested_path = self.output_dir_input.text().strip()
        if not requested_path:
            requested_path = str(Path.home() / "Downloads" / "PinterestDownloads")

        try:
            output_dir = ensure_directory(requested_path)
        except OSError as exc:
            QMessageBox.critical(self, "Folder Error", f"Could not create output folder:\n{exc}")
            return

        self.output_dir_input.setText(str(output_dir))
        self.current_urls = []
        self.row_results = {}
        self.row_states = {}
        self._reset_results_table()
        self._refresh_stats()
        self._stop_video_preview(clear_media=True)
        self._set_preview_message("Select a downloaded row to preview image or video.")

        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.status_label.setText("Preparing queue (profile scan if needed)...")
        self._set_controls_enabled(False)

        self.worker_thread = QThread(self)
        self.worker = DownloadWorker(source_urls=urls, output_dir=str(output_dir), max_profile_pins=0)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.queue_prepared.connect(self._handle_queue_prepared)
        self.worker.row_updated.connect(self._handle_row_update)
        self.worker.progress_changed.connect(self._handle_progress_update)
        self.worker.completed.connect(self._handle_completed)
        self.worker.crashed.connect(self._handle_crash)

        self.worker.completed.connect(self.worker_thread.quit)
        self.worker.crashed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._cleanup_worker_references)

        self.worker_thread.start()

        if invalid_entries:
            self.status_label.setText(
                "Preparing queue. "
                f"Accepted {len(urls)} URL(s), skipped {len(invalid_entries)} invalid line(s)."
            )

    def _prepare_table(self, urls: list[str]) -> None:
        self.result_table.setRowCount(len(urls))
        for row, url in enumerate(urls):
            self.result_table.setItem(row, 0, self._make_item(str(row + 1)))
            self.result_table.setItem(row, 1, self._make_item(url))
            self.result_table.setItem(row, 2, self._status_item("Pending"))
            self.result_table.setItem(row, 3, self._make_item(""))
            self.result_table.setItem(row, 4, self._make_item(""))

    def _reset_results_table(self) -> None:
        self.result_table.clearContents()
        self.result_table.setRowCount(0)

    def _handle_queue_prepared(self, payload: dict[str, Any]) -> None:
        pin_urls = payload.get("pin_urls", [])
        notes = payload.get("notes", [])
        if not isinstance(pin_urls, list):
            pin_urls = []
        if not isinstance(notes, list):
            notes = []

        self.current_urls = pin_urls
        self.row_results = {}
        self.row_states = {index: "Pending" for index in range(len(pin_urls))}
        self._prepare_table(pin_urls)
        self._refresh_stats()

        self.progress_bar.setRange(0, max(len(pin_urls), 1))
        self.progress_bar.setValue(0)

        if pin_urls:
            self.status_label.setText(f"Queue ready: {len(pin_urls)} pin(s). Starting download...")
        else:
            self.status_label.setText("No pins found from provided URL(s).")

        if notes:
            self.status_label.setToolTip("\n".join(str(note) for note in notes))
        else:
            self.status_label.setToolTip("")

    def _handle_row_update(self, payload: dict[str, Any]) -> None:
        row = int(payload["index"]) - 1
        status = payload.get("status", "Pending")
        saved_path = payload.get("saved_path", "")
        media_type = payload.get("media_type", "")
        error = payload.get("error", "")

        if row >= self.result_table.rowCount():
            self.result_table.setRowCount(row + 1)
            pin_url = str(payload.get("pin_url", ""))
            self.result_table.setItem(row, 0, self._make_item(str(row + 1)))
            self.result_table.setItem(row, 1, self._make_item(pin_url))
            self.result_table.setItem(row, 2, self._status_item("Pending"))
            self.result_table.setItem(row, 3, self._make_item(""))
            self.result_table.setItem(row, 4, self._make_item(""))

        self.row_results[row] = payload
        self.row_states[row] = status

        self.result_table.setItem(row, 2, self._status_item(status, error))
        self.result_table.setItem(row, 3, self._make_item(media_type.title() if media_type else ""))
        if status == "Processing":
            self.result_table.setItem(row, 4, self._make_item("Working..."))
        elif status == "Downloaded":
            filename_item = self._make_item(Path(saved_path).name if saved_path else "")
            if saved_path:
                filename_item.setToolTip(saved_path)
            self.result_table.setItem(row, 4, filename_item)
        elif status == "Failed":
            failed_item = self._make_item("Failed")
            if error:
                failed_item.setToolTip(error)
            self.result_table.setItem(row, 4, failed_item)

        self._refresh_stats()

        if status == "Downloaded":
            current_row = self.result_table.currentRow()
            if current_row < 0:
                self.result_table.selectRow(row)
                if saved_path:
                    self._load_preview(saved_path, media_type)
            elif current_row == row and saved_path:
                self._load_preview(saved_path, media_type)

    def _handle_progress_update(self, current: int, total: int) -> None:
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(current)
        if total > 0:
            self.status_label.setText(f"Processing {current}/{total}...")

    def _handle_completed(self, summary: dict[str, Any]) -> None:
        self._set_controls_enabled(True)
        self._refresh_stats()
        total = int(summary.get("total", 0))
        self.progress_bar.setValue(total)

        notes = summary.get("queue_notes", [])
        note_text = "\n".join(str(note) for note in notes) if isinstance(notes, list) else ""
        if note_text:
            self.status_label.setToolTip(note_text)
        else:
            self.status_label.setToolTip("")

        if summary.get("cancelled"):
            self.status_label.setText("Download cancelled.")
        elif total == 0:
            self.status_label.setText("No downloadable pins found from provided URL(s).")
        else:
            self.status_label.setText(
                f"Done. Success: {summary.get('success', 0)} | Failed: {summary.get('failed', 0)}"
            )

    def _handle_crash(self, message: str) -> None:
        self._set_controls_enabled(True)
        self.status_label.setText("Unexpected worker error.")
        self.status_label.setToolTip("")
        QMessageBox.critical(self, "Download Error", message)

    def _cleanup_worker_references(self) -> None:
        self.worker = None
        self.worker_thread = None

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.start_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)
        self.browse_button.setEnabled(enabled)
        self.url_input.setEnabled(enabled)
        self.output_dir_input.setEnabled(enabled)

    def _refresh_stats(self) -> None:
        total = len(self.current_urls)
        success = sum(1 for status in self.row_states.values() if status == "Downloaded")
        failed = sum(1 for status in self.row_states.values() if status == "Failed")
        self.total_value.setText(str(total))
        self.success_value.setText(str(success))
        self.failed_value.setText(str(failed))

    def _update_preview_from_selection(self) -> None:
        selected_rows = self.result_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        payload = self.row_results.get(row, {})
        saved_path = payload.get("saved_path", "")
        media_type = payload.get("media_type", "")
        if saved_path and Path(saved_path).exists():
            self._load_preview(saved_path, media_type)
            return

        status = payload.get("status")
        if status == "Failed":
            self._set_preview_message("No preview for failed download.")
        else:
            self._set_preview_message("Preview appears after a successful download.")

    def _load_preview(self, saved_path: str, media_type: str = "") -> None:
        resolved_type = media_type or infer_media_type_from_path(saved_path) or "image"
        if resolved_type == "video":
            self._load_video_preview(saved_path)
            return
        self._load_image_preview(saved_path)

    def _load_image_preview(self, image_path: str) -> None:
        path = Path(image_path)
        if not path.exists():
            self._set_preview_message("Preview file was not found on disk.")
            return

        self._stop_video_preview(clear_media=True)
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._set_preview_message("Preview not available for this image.")
            return

        self._current_preview_path = str(path)
        self._preview_pixmap = pixmap
        self.preview_stack.setCurrentWidget(self.preview_image_label)
        self._render_preview()
        QTimer.singleShot(0, self._render_preview)

    def _load_video_preview(self, video_path: str) -> None:
        path = Path(video_path)
        if not path.exists():
            self._set_preview_message("Preview file was not found on disk.")
            return

        self._preview_pixmap = QPixmap()
        self.preview_stack.setCurrentWidget(self.video_widget)
        self.play_pause_button.setVisible(True)
        self.stop_video_button.setVisible(True)

        self._current_preview_path = str(path)
        media = QMediaContent(QUrl.fromLocalFile(str(path.resolve())))
        self.media_player.setMedia(media)
        self.play_pause_button.setText("Play")
        QTimer.singleShot(0, self.media_player.play)

    def _render_preview(self) -> None:
        if self._preview_pixmap.isNull():
            return

        target_size = self.preview_image_label.size()
        if target_size.width() < 2 or target_size.height() < 2:
            target_size = self.preview_stack.size()
        if target_size.width() < 2 or target_size.height() < 2:
            return

        scaled = self._preview_pixmap.scaled(
            target_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_image_label.setPixmap(scaled)
        self.preview_image_label.setText("")

    def _set_preview_message(self, text: str) -> None:
        self._stop_video_preview(clear_media=True)
        self._preview_pixmap = QPixmap()
        self._current_preview_path = ""
        self.preview_image_label.setPixmap(QPixmap())
        self.preview_image_label.setText("")
        self.preview_message_label.setText(text)
        self.preview_stack.setCurrentWidget(self.preview_message_label)

    def _toggle_video_playback(self) -> None:
        if self.media_player.mediaStatus() == QMediaPlayer.NoMedia:
            return

        if self.media_player.state() == QMediaPlayer.PlayingState:
            self.media_player.pause()
            self.play_pause_button.setText("Play")
            return

        self.media_player.play()
        self.play_pause_button.setText("Pause")

    def _stop_video_preview(self, clear_media: bool = False) -> None:
        if self.media_player.state() != QMediaPlayer.StoppedState:
            self.media_player.stop()
        if clear_media:
            self.media_player.setMedia(QMediaContent())
        self.play_pause_button.setVisible(False)
        self.stop_video_button.setVisible(False)

    def _on_player_state_changed(self, state: QMediaPlayer.State) -> None:
        if state == QMediaPlayer.PlayingState:
            self.play_pause_button.setText("Pause")
        else:
            self.play_pause_button.setText("Play")

    def _on_player_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.InvalidMedia:
            self._set_preview_message(
                "Video preview is not supported by this system codec setup. "
                "Use Open Folder to play the file externally."
            )

    def _handle_preview_player_error(self, error: int) -> None:
        if error == QMediaPlayer.NoError:
            return
        self._set_preview_message(
            "Video preview failed. Use Open Folder to play the saved file externally."
        )

    def _make_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _status_item(self, status: str, error: str = "") -> QTableWidgetItem:
        item = self._make_item(status)
        color_map = {
            "Pending": QColor("#6b7280"),
            "Processing": QColor("#0f5fd2"),
            "Downloaded": QColor("#0e7a4f"),
            "Failed": QColor("#b42318"),
        }
        item.setForeground(QBrush(color_map.get(status, QColor("#1f2937"))))
        if error:
            item.setToolTip(error)
        return item

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if not self._preview_pixmap.isNull():
            self._render_preview()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_video_preview(clear_media=True)
        if self.worker_thread and self.worker_thread.isRunning():
            if self.worker:
                self.worker.stop()
            self.worker_thread.quit()
            self.worker_thread.wait(1500)
        super().closeEvent(event)
