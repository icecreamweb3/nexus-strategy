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


def get_build_time() -> str:
    """Return embedded package time, with a useful source-run fallback."""
    metadata = _resource_root() / "build_info.json"
    try:
        value = json.loads(metadata.read_text(encoding="utf-8")).get("build_time")
        if value:
            return str(value)
    except (OSError, ValueError, TypeError):
        pass

    source_entry = _resource_root() / "main.py"
    try:
        timestamp = source_entry.stat().st_mtime
    except OSError:
        timestamp = Path(sys.executable).stat().st_mtime
    return datetime.fromtimestamp(timestamp).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S %Z")
