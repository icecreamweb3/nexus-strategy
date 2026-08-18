"""实盘交易页 / Live trading tab — REST 下单 + WebSocket 监听订单状态."""
from datetime import datetime

from PyQt5.QtWidgets import (
    QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from app.api.client import BinanceFuturesClient
from app.api.ws_listener import OrderStreamListener
from app.config import load_config
from app.i18n import tr
from app.logger import get_logger


class LiveTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._client = None
        self._listener = None
        self._retr = []
        self._order_rows = {}   # order_id -> row
        self._build_ui()
        self.retranslate()

    def _reg(self, setter, key):
        self._retr.append((setter, key))

    def _label(self, key) -> QLabel:
        lab = QLabel()
        self._reg(lab.setText, key)
        return lab

    def _build_ui(self):
        root = QVBoxLayout(self)

        # 连接区
        conn_box = QGroupBox()
        self._reg(conn_box.setTitle, "tab_live")
        grid = QGridLayout(conn_box)
        self.btn_connect = QPushButton()
        self.btn_connect.clicked.connect(self._toggle_connection)
        self.lbl_status = QLabel()
        self.lbl_balance_val = QLabel("—")
        self.btn_refresh = QPushButton()
        self._reg(self.btn_refresh.setText, "live_refresh_balance")
        self.btn_refresh.clicked.connect(self._refresh_balance)
        self.btn_refresh.setEnabled(False)
        grid.addWidget(self._label("live_status"), 0, 0)
        grid.addWidget(self.lbl_status, 0, 1)
        grid.addWidget(self.btn_connect, 0, 2)
        grid.addWidget(self._label("live_balance"), 1, 0)
        grid.addWidget(self.lbl_balance_val, 1, 1)
        grid.addWidget(self.btn_refresh, 1, 2)
        root.addWidget(conn_box)

        # 下单区
        order_box = QGroupBox()
        self._reg(order_box.setTitle, "live_place_order")
        ogrid = QGridLayout(order_box)
        self.cmb_symbol = QComboBox()
        self.cmb_symbol.setEditable(True)
        self.cmb_symbol.addItems(["BTCUSDT", "ETHUSDT", "BNBUSDT"])
        cfg = load_config()
        idx = self.cmb_symbol.findText(cfg.symbol)
        if idx >= 0:
            self.cmb_symbol.setCurrentIndex(idx)
        self.cmb_side = QComboBox()
        self.cmb_type = QComboBox()
        self.sp_qty = QDoubleSpinBox()
        self.sp_qty.setRange(0.0001, 1e6)
        self.sp_qty.setDecimals(4)
        self.sp_qty.setValue(0.001)
        self.sp_price = QDoubleSpinBox()
        self.sp_price.setRange(0.01, 1e9)
        self.sp_price.setDecimals(2)
        self.sp_price.setValue(50000.0)
        self.btn_place = QPushButton()
        self._reg(self.btn_place.setText, "live_place_order")
        self.btn_place.clicked.connect(self._place_order)
        self.btn_place.setEnabled(False)
        ogrid.addWidget(self._label("live_symbol"), 0, 0)
        ogrid.addWidget(self.cmb_symbol, 0, 1)
        ogrid.addWidget(self._label("live_side"), 0, 2)
        ogrid.addWidget(self.cmb_side, 0, 3)
        ogrid.addWidget(self._label("live_qty"), 0, 4)
        ogrid.addWidget(self.sp_qty, 0, 5)
        ogrid.addWidget(self._label("order_type"), 1, 0)
        ogrid.addWidget(self.cmb_type, 1, 1)
        ogrid.addWidget(self._label("live_price"), 1, 2)
        ogrid.addWidget(self.sp_price, 1, 3)
        ogrid.addWidget(self.btn_place, 1, 5)
        root.addWidget(order_box)

        # 订单状态表（WebSocket 推送）
        orders_box = QGroupBox()
        self._reg(orders_box.setTitle, "live_orders")
        v = QVBoxLayout(orders_box)
        self.table = QTableWidget(0, 7)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.table)
        root.addWidget(orders_box, stretch=1)

    def retranslate(self):
        for setter, key in self._retr:
            setter(tr(key))
        connected = self._listener is not None and self._listener.running
        self.btn_connect.setText(tr("live_disconnect" if connected else "live_connect"))
        self.lbl_status.setText(tr("live_connected" if connected else "live_disconnected"))
        idx_side = max(self.cmb_side.currentIndex(), 0)
        self.cmb_side.blockSignals(True)
        self.cmb_side.clear()
        self.cmb_side.addItems([tr("live_buy"), tr("live_sell")])
        self.cmb_side.setCurrentIndex(idx_side)
        self.cmb_side.blockSignals(False)
        idx_type = max(self.cmb_type.currentIndex(), 0)
        self.cmb_type.blockSignals(True)
        self.cmb_type.clear()
        self.cmb_type.addItems([tr("market_order"), tr("limit_order")])
        self.cmb_type.setCurrentIndex(idx_type)
        self.cmb_type.blockSignals(False)
        self.table.setHorizontalHeaderLabels([
            tr("col_order_id"), tr("live_symbol"), tr("live_side"),
            tr("col_order_status"), tr("col_filled_qty"),
            tr("col_avg_price"), tr("col_time"),
        ])

    # ---------- 连接 ----------

    def _toggle_connection(self):
        if self._listener is not None and self._listener.running:
            self._listener.stop()
            self.btn_refresh.setEnabled(False)
            self.btn_place.setEnabled(False)
            self.retranslate()
            return
        cfg = load_config()
        if not cfg.has_credentials:
            QMessageBox.warning(self, tr("app_title"), tr("live_no_credentials"))
            return
        try:
            self._client = BinanceFuturesClient(cfg)
            self._listener = OrderStreamListener(self._client, self)
            self._listener.order_update.connect(self._on_order_update)
            self._listener.stream_started.connect(
                lambda: get_logger().info(tr("live_ws_started")))
            self._listener.start()
            self.btn_refresh.setEnabled(True)
            self.btn_place.setEnabled(True)
            self._refresh_balance()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("app_title"), tr("live_error", err=exc))
        self.retranslate()

    def _refresh_balance(self):
        if self._client is None:
            return
        try:
            balance = self._client.get_balance()
            self.lbl_balance_val.setText(f"{balance:,.2f}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("app_title"), tr("live_error", err=exc))

    # ---------- 下单 ----------

    def _place_order(self):
        if self._client is None:
            return
        symbol = self.cmb_symbol.currentText().strip().upper()
        side = "BUY" if self.cmb_side.currentIndex() == 0 else "SELL"
        order_type = "MARKET" if self.cmb_type.currentIndex() == 0 else "LIMIT"
        try:
            self._client.place_order(
                symbol=symbol, side=side, quantity=self.sp_qty.value(),
                order_type=order_type,
                price=self.sp_price.value() if order_type == "LIMIT" else None,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("app_title"), tr("live_error", err=exc))

    # ---------- WebSocket 订单更新 ----------

    def _on_order_update(self, order: dict):
        order_id = order.get("i")
        if order_id is None:
            return
        ts = order.get("T") or order.get("O")
        time_str = datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S") if ts else ""
        vals = [str(order_id), order.get("s", ""), order.get("S", ""),
                order.get("X", ""), order.get("z", ""), order.get("ap", ""), time_str]
        row = self._order_rows.get(order_id)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._order_rows[order_id] = row
        for col, val in enumerate(vals):
            self.table.setItem(row, col, QTableWidgetItem(val))

    def close_listener(self):
        if self._listener is not None:
            self._listener.stop()
