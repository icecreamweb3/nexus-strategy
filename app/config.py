"""从 .env 加载配置 / Load configuration from .env."""
import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

APP_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_project_env() -> None:
    """Load the project .env as the authoritative runtime configuration."""
    # A desktop app is often launched from a shell/IDE that still contains old
    # credentials.  The explicitly selected project .env must win over those
    # inherited values, otherwise the UI can silently connect to another account.
    load_dotenv(os.path.join(APP_DIR, ".env"), override=True)


_load_project_env()


_LANG_ALIASES = {
    "zh": "zh_CN", "zh_cn": "zh_CN", "cn": "zh_CN",
    "en": "en_US", "en_us": "en_US",
}


@dataclass
class Config:
    api_key: str
    api_secret: str
    testnet: bool
    symbol: str
    language: str

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key) and bool(self.api_secret) \
            and self.api_key != "your_api_key_here" \
            and self.api_secret != "your_api_secret_here"


def load_config() -> Config:
    # Reload on every connection/start action so edits to .env are picked up and
    # stale process variables cannot become the credential source again.
    _load_project_env()
    lang = os.getenv("UI_LANGUAGE", "zh_CN").strip().lower()
    return Config(
        api_key=os.getenv("BINANCE_API_KEY", ""),
        api_secret=os.getenv("BINANCE_API_SECRET", ""),
        testnet=os.getenv("BINANCE_TESTNET", "true").lower() in ("1", "true", "yes"),
        symbol=os.getenv("BINANCE_SYMBOL", "BTCUSDT"),
        language=_LANG_ALIASES.get(lang, "zh_CN"),
    )
