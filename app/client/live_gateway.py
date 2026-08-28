"""项目内使用的 Binance 合约 REST 网关。

将 SDK 返回值统一转换为回测引擎使用的 ``Kline``，让实时与回测共用
同一套条件检测代码。
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from app.backtest.data_loader import Kline
from app.client.binance_client import BinanceClient
from app.config import Config


class BinanceLiveGateway:
    def __init__(self, config: Config):
        self.client = BinanceClient(
            api_key=config.api_key,
            secret_key=config.api_secret,
            testnet=config.testnet,
        )
        self._quantity_steps: dict[str, float] = {}

    def recent_closed_klines(self, symbol: str, interval: str,
                             limit: int = 500) -> list[Kline]:
        rows = self.client.get_kline_data(
            symbol=symbol.upper(), interval=interval,
            limit=min(max(limit, 2), 1500))
        now_ms = int(time.time() * 1000)
        closed = [row for row in rows if int(row[6]) < now_ms]
        return [self.kline_from_rest(row, index + 1)
                for index, row in enumerate(closed)]

    @staticmethod
    def kline_from_rest(row, index: int) -> Kline:
        timestamp = datetime.fromtimestamp(
            int(row[0]) / 1000, tz=timezone.utc,
        ).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
        return Kline(index, timestamp, float(row[1]), float(row[2]),
                     float(row[3]), float(row[4]), float(row[5]))

    def market_order(self, symbol: str, side: str, quantity: float,
                     position_side: str | None = None) -> dict:
        quantity = self.normalize_quantity(symbol, quantity)
        if quantity <= 0:
            raise ValueError("下单数量低于交易对允许的最小精度")
        result = self.client.place_market_order(
            symbol=symbol.upper(), side=side, quantity=quantity,
            position_side=position_side)
        if not result:
            raise RuntimeError("Binance 下单未返回结果")
        if result.get("error"):
            raise RuntimeError(result.get("error_message", "Binance 下单失败"))
        return result

    def normalize_quantity(self, symbol: str, quantity: float) -> float:
        symbol = symbol.upper()
        step = self._quantity_steps.get(symbol)
        if step is None:
            info = self.client.get_symbol_precision_info(symbol)
            if info is None:
                raise ValueError(f"Binance 不支持交易对 {symbol}")
            step = info.get("step_size")
            if not step:
                raise ValueError(f"无法取得 {symbol} 的数量精度")
            step = float(step)
            self._quantity_steps[symbol] = step
        units = math.floor((quantity + step * 1e-12) / step)
        decimals = max(0, len(f"{step:.16f}".rstrip("0").split(".")[-1]))
        return round(units * step, decimals)
