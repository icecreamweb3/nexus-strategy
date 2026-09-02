"""Application version and reproducible build metadata."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


APP_VERSION = "v1.0.0"


def _resource_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parent.parent


def _build_datetime() -> datetime:
    """Return embedded package time, with a source-run fallback."""
    metadata = _resource_root() / "build_info.json"
    try:
        value = json.loads(metadata.read_text(encoding="utf-8")).get("build_time")
        if value:
            return datetime.fromisoformat(str(value))
    except (OSError, ValueError, TypeError):
        pass

    source_entry = _resource_root() / "main.py"
    try:
        timestamp = source_entry.stat().st_mtime
    except OSError:
        timestamp = Path(sys.executable).stat().st_mtime
    return datetime.fromtimestamp(timestamp).astimezone()


def get_build_time(language: str = "zh_CN") -> str:
    """Format build time using the currently selected UI language."""
    value = _build_datetime()
    offset = value.utcoffset()
    if offset is not None and int(offset.total_seconds()) == 8 * 60 * 60:
        zone = "China Standard Time" if language == "en_US" else "中国标准时间"
    elif offset is None:
        zone = ""
    else:
        seconds = int(offset.total_seconds())
        sign = "+" if seconds >= 0 else "-"
        seconds = abs(seconds)
        zone = f"UTC{sign}{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"
    return f"{value:%Y-%m-%d %H:%M:%S} {zone}".rstrip()
