"""WebSocket 监听合约订单状态变化 / Futures user-data WebSocket listener.

通过 python-binance 的 ThreadedWebsocketManager 订阅 user data stream，
ORDER_TRADE_UPDATE 事件经 Qt 信号推送到 UI；listenKey 每 30 分钟保活。
"""
from PyQt5.QtCore import QObject, QTimer, pyqtSignal

try:  # python-binance >= 1.0.28
    from binance.ws.streams import ThreadedWebsocketManager
except ImportError:  # 旧版本
    from binance.threaded_stream import ThreadedWebsocketManager

from app.api.client import BinanceFuturesClient
from app.logger import get_logger

KEEPALIVE_INTERVAL_MS = 30 * 60 * 1000  # 30 分钟


class OrderStreamListener(QObject):
    """监听订单状态变化：order_update(dict) 携带 ORDER_TRADE_UPDATE 的订单字段。"""

    order_update = pyqtSignal(dict)
    stream_started = pyqtSignal()
    stream_stopped = pyqtSignal()

    def __init__(self, client: BinanceFuturesClient, parent=None):
        super().__init__(parent)
        self._client = client
        self._log = get_logger()
        self._twm = None
        self._keepalive_timer = QTimer(self)
        self._keepalive_timer.setInterval(KEEPALIVE_INTERVAL_MS)
        self._keepalive_timer.timeout.connect(self._keepalive)

    def start(self):
        if self._twm is not None:
            return
        cfg = self._client._config
        self._twm = ThreadedWebsocketManager(
            api_key=cfg.api_key, api_secret=cfg.api_secret, testnet=cfg.testnet
        )
        self._twm.start()
        self._twm.start_futures_user_socket(callback=self._on_message)
        self._keepalive_timer.start()
        self._log.info("WebSocket 用户数据流已启动")
        self.stream_started.emit()

    def stop(self):
        self._keepalive_timer.stop()
        if self._twm is not None:
            try:
                self._twm.stop()
            except Exception as exc:  # noqa: BLE001
                self._log.warning("WebSocket 停止异常: %s", exc)
            self._twm = None
        self._log.info("WebSocket 用户数据流已停止")
        self.stream_stopped.emit()

    @property
    def running(self) -> bool:
        return self._twm is not None

    def _keepalive(self):
        try:
            self._client.raw.futures_stream_keepalive()
        except Exception as exc:  # noqa: BLE001
            self._log.warning("listenKey 保活失败: %s", exc)

    def _on_message(self, msg: dict):
        if not isinstance(msg, dict):
            return
        event = msg.get("e")
        if event == "ORDER_TRADE_UPDATE":
            order = msg.get("o", {})
            self._log.info(
                "订单更新 id=%s symbol=%s side=%s status=%s filled=%s avgPrice=%s",
                order.get("i"), order.get("s"), order.get("S"),
                order.get("X"), order.get("z"), order.get("ap"),
            )
            self.order_update.emit(order)
        elif event == "ACCOUNT_UPDATE":
            self._log.debug("账户更新: %s", msg)
