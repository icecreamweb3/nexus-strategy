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
TRADE_DETAIL_LOG_FILE = os.path.join(LOG_DIR, "trade_details.log")

_logger = None
_trade_detail_logger = None


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


def setup_trade_detail_logger(enabled: bool):
    """按配置创建独立的逐笔成交明细日志；关闭时不创建日志文件。"""
    global _trade_detail_logger
    if not enabled:
        if _trade_detail_logger is not None:
            for handler in tuple(_trade_detail_logger.handlers):
                _trade_detail_logger.removeHandler(handler)
                handler.close()
        _trade_detail_logger = None
        return None
    if _trade_detail_logger is not None:
        return _trade_detail_logger

    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("nexus_strategy.trade_details")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    # 清理同一进程内重新配置遗留的 handler，避免明细重复写入。
    for existing_handler in tuple(logger.handlers):
        logger.removeHandler(existing_handler)
        existing_handler.close()
    handler = RotatingFileHandler(
        TRADE_DETAIL_LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    _trade_detail_logger = logger
    return logger


def get_trade_detail_logger():
    """返回已启用的逐笔成交明细 logger，否则返回 None。"""
    return _trade_detail_logger


def create_backtest_log_path(now: datetime = None) -> str:
    """为单次回测创建带本地执行时间戳的独立日志路径。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(LOG_DIR, f"backtest_{timestamp}.log")


def create_trader_live_log_path(now: datetime = None) -> str:
    """为单次实盘交易会话创建带本地时间戳的独立日志路径。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(LOG_DIR, f"trader_live_{timestamp}.log")
