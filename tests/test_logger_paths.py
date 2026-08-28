from datetime import datetime
from pathlib import Path

from app.logger import create_trader_live_log_path


def test_trader_live_log_path_contains_local_timestamp():
    path = create_trader_live_log_path(datetime(2026, 8, 28, 17, 40, 43, 749479))

    assert Path(path).name == "trader_live_20260828_174043_749479.log"
