from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from app.constants import APP_NAME
from app.ui.main_window import MainWindow


def _load_stylesheet(app: QApplication) -> None:
    style_path = Path(__file__).resolve().parent / "resources" / "style.qss"
    if style_path.exists():
        app.setStyleSheet(style_path.read_text(encoding="utf-8"))


def run() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI", 10))
    _load_stylesheet(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())

