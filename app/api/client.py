"""币安合约 REST API 封装 / Binance Futures REST client wrapper."""
from binance.client import Client
from binance.exceptions import BinanceAPIException

from app.config import Config
from app.logger import get_logger


class BinanceFuturesClient:
    """Thin wrapper around python-binance futures endpoints."""

    def __init__(self, config: Config):
        self._config = config
        self._client = Client(
            api_key=config.api_key,
            api_secret=config.api_secret,
            testnet=config.testnet,
        )
        self._log = get_logger()

    @property
    def raw(self) -> Client:
        return self._client

    def get_balance(self) -> float:
        """USDT 合约账户可用余额。"""
        balances = self._client.futures_account_balance()
        for item in balances:
            if item.get("asset") == "USDT":
                return float(item.get("availableBalance", 0.0))
        return 0.0

    def place_order(self, symbol: str, side: str, quantity: float,
                    order_type: str = "MARKET", price: float = None) -> dict:
        """下单。side: BUY/SELL, order_type: MARKET/LIMIT。"""
        params = dict(symbol=symbol, side=side, type=order_type, quantity=quantity)
        if order_type == "LIMIT":
            params.update(timeInForce="GTC", price=price)
        self._log.info("下单 %s %s %s qty=%s price=%s", symbol, side, order_type, quantity, price)
        try:
            result = self._client.futures_create_order(**params)
            self._log.info("下单成功 orderId=%s status=%s", result.get("orderId"), result.get("status"))
            return result
        except BinanceAPIException as exc:
            self._log.error("下单失败: %s", exc)
            raise

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        self._log.info("撤单 %s orderId=%s", symbol, order_id)
        return self._client.futures_cancel_order(symbol=symbol, orderId=order_id)

    def get_order(self, symbol: str, order_id: int) -> dict:
        return self._client.futures_get_order(symbol=symbol, orderId=order_id)
