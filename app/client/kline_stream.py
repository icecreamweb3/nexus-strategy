"""Qt 适配器：把 binance_websoket 框架事件安全转发给界面。"""
from __future__ import annotations

from datetime import datetime, timezone

from PyQt5.QtCore import QObject, pyqtSignal

from app.backtest.data_loader import Kline
from app.client.binance_websocket import OrdersMonitor


class KlineStream(QObject):
    closed_kline = pyqtSignal(object)
    order_update = pyqtSignal(dict)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, binance_client, symbol: str, interval: str,
                 testnet: bool = False, parent=None):
        super().__init__(parent)
        self.binance_client = binance_client
        self.symbol = symbol.upper()
        self.interval = interval
        self.testnet = testnet
        self._monitor = None

    @property
    def running(self) -> bool:
        return self._monitor is not None and self._monitor.running

    def start(self):
        if self.running:
            return
        monitor = OrdersMonitor(
            self.binance_client,
            symbol=self.symbol,
            interval=self.interval,
            on_kline_closed=self._on_kline_closed,
            on_order_update=self.order_update.emit,
            testnet=self.testnet,
        )
        self._monitor = monitor
        monitor.start()
        if not monitor.running:
            self._monitor = None
            error = "Binance WebSocket 框架启动失败"
            self.failed.emit(error)
            raise RuntimeError(error)
        self.connected.emit()

    def stop(self):
        monitor = self._monitor
        self._monitor = None
        if monitor is not None:
            monitor.stop()
            self.disconnected.emit()

    def _on_kline_closed(self, raw: dict):
        try:
            open_time = datetime.fromtimestamp(
                int(raw["t"]) / 1000, tz=timezone.utc,
            ).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
            self.closed_kline.emit(Kline(
                index=0,
                open_time=open_time,
                open=float(raw["o"]),
                high=float(raw["h"]),
                low=float(raw["l"]),
                close=float(raw["c"]),
                volume=float(raw["v"]),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            self.failed.emit(str(exc))


class PerpetualPriceStream(QObject):
    """通过迁移的 OrdersMonitor 框架订阅永续合约 aggTrade 实时价格。"""

    price_update = pyqtSignal(float)
    failed = pyqtSignal(str)

    def __init__(self, symbol: str, testnet: bool = False, parent=None):
        super().__init__(parent)
        self.symbol = symbol.upper()
        self.testnet = testnet
        self._monitor = None

    @property
    def running(self) -> bool:
        return self._monitor is not None and self._monitor.running

    def start(self):
        if self.running:
            return
        monitor = OrdersMonitor(
            None,
            symbol=self.symbol,
            on_price_update=self.price_update.emit,
            testnet=self.testnet,
        )
        self._monitor = monitor
        try:
            monitor.start_market_only()
        except Exception as exc:  # noqa: BLE001
            self._monitor = None
            self.failed.emit(str(exc))

    def stop(self):
        monitor = self._monitor
        self._monitor = None
        if monitor is not None:
            monitor.stop()
