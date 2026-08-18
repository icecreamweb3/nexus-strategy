#!/usr/bin/env python3
"""Nexus Strategy - 交易策略回测系统入口 / Entry point."""
import sys

from PyQt5.QtWidgets import QApplication

from app.logger import setup_logger
from app.ui.main_window import MainWindow


def main() -> int:
    setup_logger()
    app = QApplication(sys.argv)
    app.setApplicationName("Nexus Strategy")
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
