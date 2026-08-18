"""从 .env 加载配置 / Load configuration from .env."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    api_key: str
    api_secret: str
    testnet: bool
    symbol: str

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key) and bool(self.api_secret) \
            and self.api_key != "your_api_key_here"


def load_config() -> Config:
    return Config(
        api_key=os.getenv("BINANCE_API_KEY", ""),
        api_secret=os.getenv("BINANCE_API_SECRET", ""),
        testnet=os.getenv("BINANCE_TESTNET", "true").lower() in ("1", "true", "yes"),
        symbol=os.getenv("BINANCE_SYMBOL", "BTCUSDT"),
    )
