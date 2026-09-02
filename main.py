#!/usr/bin/env python3
"""Nexus Strategy - 交易策略回测系统入口 / Entry point."""
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from app.config import load_config
from app.i18n import i18n
from app.logger import setup_logger
from app.ui.main_window import MainWindow


def show_main_window(window: MainWindow, app: QApplication) -> None:
    """Show the window inside the current screen and bring it to the front."""
    screen = app.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        width = min(1536, max(900, area.width()))
        height = min(1032, max(650, area.height()))
        window.resize(width, height)
        window.move(
            area.x() + max(0, (area.width() - width) // 2),
            area.y() + max(0, (area.height() - height) // 2),
        )
    window.show()
    window.raise_()
    window.activateWindow()


def main() -> int:
    setup_logger()
    i18n().set_language(load_config().language)  # 按 .env 的 UI_LANGUAGE 设置默认语言
    app = QApplication(sys.argv)
    app.setApplicationName("Nexus Strategy")
    window = MainWindow()
    show_main_window(window, app)
    # Some Wayland/XWayland compositors ignore activation before the event loop
    # starts. Retry once after pending window-system events have been processed.
    QTimer.singleShot(0, lambda: (window.raise_(), window.activateWindow()))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
