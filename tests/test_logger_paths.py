from datetime import datetime
from pathlib import Path

from app import logger as logger_module
from app.logger import create_trader_live_log_path


def test_trader_live_log_path_contains_local_timestamp():
    path = create_trader_live_log_path(datetime(2026, 8, 28, 17, 40, 43, 749479))

    assert Path(path).name == "trader_live_20260828_174043_749479.log"


def test_trade_detail_logger_writes_only_when_enabled(tmp_path, monkeypatch):
    detail_path = tmp_path / "trade_details.log"
    monkeypatch.setattr(logger_module, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(
        logger_module, "TRADE_DETAIL_LOG_FILE", str(detail_path))
    monkeypatch.setattr(logger_module, "_trade_detail_logger", None)

    assert logger_module.setup_trade_detail_logger(False) is None
    assert not detail_path.exists()

    detail_logger = logger_module.setup_trade_detail_logger(True)
    detail_logger.debug("filled trade detail")
    for handler in detail_logger.handlers:
        handler.flush()

    assert "filled trade detail" in detail_path.read_text(encoding="utf-8")
    logger_module.setup_trade_detail_logger(False)
