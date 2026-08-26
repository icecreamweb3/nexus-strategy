"""交易日志：文件轮转 + 控制台 / Trade logger: rotating file + console."""
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler

APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(APP_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "trade.log")

_logger = None


def setup_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("nexus_strategy")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    return _logger if _logger is not None else setup_logger()


def create_backtest_log_path(now: datetime = None) -> str:
    """为单次回测创建带本地执行时间戳的独立日志路径。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(LOG_DIR, f"backtest_{timestamp}.log")
