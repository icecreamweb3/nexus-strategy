"""实时策略页：Binance K线 → 原条件检测 → 合约市价单。"""
from __future__ import annotations

from datetime import datetime, timezone

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QHeaderView, QTabWidget, QHBoxLayout, QWidget,
)

from app.backtest.engine import LONG, base_order_notional, required_order_margin
from app.client.kline_stream import KlineStream, PerpetualPriceStream
from app.client.live_gateway import BinanceLiveGateway
from app.config import load_config
from app.i18n import i18n, tr
from app.live.signal_processor import LiveSignal, LiveSignalProcessor
from app.logger import create_trader_live_log_path, get_logger
from app.storage import TradingDatabase
from app.ui.backtest_tab import BacktestTab


SYMBOLS = (
    "BTCUSDT", "BTCUSDC", "ETHUSDT", "BNBUSDT",
    "SOLUSDT", "XRPUSDT", "DOGEUSDT",
)
INTERVALS = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d")


class RealtimeStrategyTab(BacktestTab):
    """复用回测参数控件，但数据源和执行目标均为 Binance 实盘。"""

    def __init__(self, parent=None):
        self._gateway = None
        self._kline_stream = None
        self._price_stream = None
        self._processor = None
        self._running = False
        self._placing_order = False
        self._latest_close = None
        self._live_prices = {}
        self._current_position_rows = []
        self._live_log_file = None
        self._live_log_path = ""
        self._db = TradingDatabase()
        super().__init__(parent)
        self.cmb_symbol.currentIndexChanged.connect(self._on_symbol_changed)
        if self.cmb_symbol.lineEdit() is not None:
            self.cmb_symbol.lineEdit().editingFinished.connect(
                self._on_symbol_changed)
        QTimer.singleShot(0, self._restart_price_stream)
        QTimer.singleShot(100, lambda: self._refresh_account(show_errors=False))

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.params_widget = self._build_params_section()
        root.addWidget(self.params_widget)
        root.addWidget(self._build_market_section())
        root.addWidget(self._build_live_orders_section(), stretch=1)
        root.addWidget(self._build_log_section(), stretch=1)

    def _build_log_section(self) -> QGroupBox:
        """实时页保留日志内容和搜索，隐藏回测页使用的控制工具栏。"""
        box = super()._build_log_section()
        for widget in (
            self.btn_toggle_log, self.btn_export_log, self.chk_triggers,
            self.btn_show_all, self.btn_prev, self.btn_next, self.lbl_page,
        ):
            widget.hide()
        return box

    def _build_market_section(self) -> QGroupBox:
        box = QGroupBox()
        self._reg(box.setTitle, "live_trading_panel")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        # 第一行：ticker / 实时价格 / 余额 / 风险率
        self.cmb_symbol = QComboBox()
        self.cmb_symbol.setEditable(True)
        self.cmb_symbol.addItems(SYMBOLS)
        self.cmb_symbol.setMinimumWidth(105)
        configured = load_config().symbol.upper()
        index = self.cmb_symbol.findText(configured)
        if index < 0:
            self.cmb_symbol.setCurrentText(configured)
        else:
            self.cmb_symbol.setCurrentIndex(index)
        self.cmb_interval = QComboBox()
        self.cmb_interval.addItems(INTERVALS)
        self.cmb_interval.setCurrentText("1m")
        self.cmb_interval.setMinimumWidth(70)
        self.lbl_latest_value = QLabel(f"{configured} PERP  —")
        self.lbl_latest_value.setStyleSheet("color: #00a99d; font-weight: bold;")
        self.lbl_balance_value = QLabel("—")
        self.lbl_balance_value.setStyleSheet("color: #00a99d;")
        self.lbl_risk_value = QLabel("—")
        self.lbl_risk_value.setStyleSheet("color: #00a99d;")
        self.btn_refresh_account = QPushButton()
        self._reg(self.btn_refresh_account.setText, "live_refresh")
        self.btn_refresh_account.clicked.connect(self._refresh_account)

        grid.addWidget(self.cmb_symbol, 0, 0)
        grid.addWidget(self.cmb_interval, 0, 1)
        grid.addWidget(self.lbl_latest_value, 0, 2)
        grid.setColumnStretch(3, 1)
        grid.addWidget(self._label("live_balance_short"), 0, 4)
        grid.addWidget(self.lbl_balance_value, 0, 5)
        grid.addWidget(self._label("live_risk_rate"), 0, 6)
        grid.addWidget(self.lbl_risk_value, 0, 7)
        grid.addWidget(self.btn_refresh_account, 0, 8)

        # Refresh 右侧：交易控制
        self.btn_start = QPushButton()
        self.btn_start.clicked.connect(self._start_live)
        self.btn_close = QPushButton()
        self._reg(self.btn_close.setText, "live_close_trading")
        self.btn_close.clicked.connect(self._close_all_positions_and_stop)
        self.btn_close.setEnabled(False)
        grid.addWidget(self.btn_start, 0, 9)
        grid.addWidget(self.btn_close, 0, 10)
        return box

    def _build_live_orders_section(self) -> QGroupBox:
        box = QGroupBox()
        self._reg(box.setTitle, "trade_records")
        layout = QVBoxLayout(box)
        self.records_tabs = QTabWidget()
        self.position_table = self._new_record_table(10)
        self.position_history_table = self._new_record_table(9)
        self.open_orders_table = self._new_record_table(10)
        self.order_history_table = self._new_record_table(10)
        self.records_tabs.addTab(self.position_table, "")
        self.records_tabs.addTab(self.position_history_table, "")

        open_orders_page = QWidget()
        open_layout = QVBoxLayout(open_orders_page)
        open_layout.setContentsMargins(0, 0, 0, 0)
        open_toolbar = QHBoxLayout()
        open_toolbar.addStretch(1)
        self.btn_cancel_selected = QPushButton()
        self.btn_cancel_selected.clicked.connect(self._cancel_selected_order)
        open_toolbar.addWidget(self.btn_cancel_selected)
        open_layout.addLayout(open_toolbar)
        open_layout.addWidget(self.open_orders_table)
        self.records_tabs.addTab(open_orders_page, "")

        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_toolbar = QHBoxLayout()
        history_toolbar.addStretch(1)
        self.lbl_order_status_filter = QLabel()
        self.order_status_filter = QComboBox()
        self.order_status_filter.addItems(
            ["ALL", "FILLED", "CANCELED", "EXPIRED", "REJECTED"])
        self.order_status_filter.currentIndexChanged.connect(
            self._refresh_record_tables)
        history_toolbar.addWidget(self.lbl_order_status_filter)
        history_toolbar.addWidget(self.order_status_filter)
        history_layout.addLayout(history_toolbar)
        history_layout.addWidget(self.order_history_table)
        self.records_tabs.addTab(history_page, "")
        layout.addWidget(self.records_tabs)
        return box

    @staticmethod
    def _new_record_table(columns: int) -> QTableWidget:
        table = QTableWidget(0, columns)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)
        return table

    def retranslate(self):
        for setter, key in self._retr:
            setter(tr(key))
        self._rebuild_combos()
        self.btn_start.setText(tr("live_start_trading"))
        self.btn_start.setEnabled(not self._running)
        self.btn_close.setEnabled(self._running)
        self.edit_search.setPlaceholderText(tr("search_placeholder"))
        for index, key in enumerate((
            "tab_current_positions", "tab_position_history", "tab_current_orders",
            "tab_order_history",
        )):
            self.records_tabs.setTabText(index, tr(key))
        self.btn_cancel_selected.setText(tr("cancel_selected_order"))
        self.lbl_order_status_filter.setText(tr("col_order_status"))
        self.position_table.setHorizontalHeaderLabels([
            tr("live_symbol"), tr("col_position_mode"), tr("live_side"),
            tr("col_qty"), tr("col_entry_price"), tr("col_open_time"),
            tr("col_unrealized_pnl"), tr("col_tp_price"), tr("col_sl_price"),
            tr("col_liquidation_price"),
        ])
        self.position_history_table.setHorizontalHeaderLabels([
            tr("live_symbol"), tr("live_side"), tr("col_entry_price"),
            tr("col_exit_price"), tr("col_qty"), tr("col_pnl"),
            tr("col_fee"), tr("col_position_mode"), tr("col_time"),
        ])
        self.open_orders_table.setHorizontalHeaderLabels([
            tr("col_order_id"), tr("live_symbol"), tr("live_side"),
            tr("col_action_type"), tr("col_type"), tr("col_order_price"),
            tr("col_qty"), tr("col_filled_qty"), tr("col_order_status"),
            tr("col_time"),
        ])
        self.order_history_table.setHorizontalHeaderLabels([
            tr("live_symbol"), tr("live_side"), tr("col_type"),
            tr("col_order_price"), tr("col_avg_price"), tr("col_qty"),
            tr("col_filled_qty"), tr("col_fee"), tr("col_order_status"),
            tr("col_time"),
        ])
        self._refresh_record_tables()
        self._refresh_log_view()

    def _rebuild_combos(self):
        index = max(self.cmb_direction.currentIndex(), 0)
        self.cmb_direction.blockSignals(True)
        self.cmb_direction.clear()
        self.cmb_direction.addItems([tr("dir_both"), tr("dir_long"), tr("dir_short")])
        self.cmb_direction.setCurrentIndex(index)
        self.cmb_direction.blockSignals(False)

    def _start_live(self):
        if self._running:
            return
        config = load_config()
        if not config.has_credentials:
            QMessageBox.warning(self, tr("app_title"), tr("live_no_credentials"))
            return
        symbol = self.cmb_symbol.currentText().strip().upper()
        interval = self.cmb_interval.currentText()
        if not symbol:
            return
        strategy, order = self._collect_params()
        required_bars = LiveSignalProcessor.required_history_bars(strategy)
        # REST 最后一根通常仍在形成中；额外请求一根，过滤后仍满足预热数量。
        history_limit = min(required_bars + 1, 1500)
        try:
            self._open_live_log()
            gateway = BinanceLiveGateway(config)
            klines = gateway.recent_closed_klines(symbol, interval, history_limit)
            if len(klines) < required_bars:
                raise RuntimeError(tr("realtime_history_empty"))
            # USDⓈ-M 杠杆参数为整数；信号处理和下单金额使用交易所实际设置值。
            order.leverage = max(1, int(order.leverage))
            if not gateway.client.set_leverage(symbol, int(order.leverage)):
                raise RuntimeError(f"无法设置 {symbol} 杠杆")
            processor = LiveSignalProcessor(
                klines, strategy, order, self._record_log,
                lambda key, **kwargs: i18n().tr_for(i18n().lang, key, **kwargs))
            stream = KlineStream(
                gateway.client, symbol, interval, config.testnet, self)
            stream.closed_kline.connect(self._on_closed_kline)
            stream.order_update.connect(self._on_order_update)
            stream.protection_update.connect(self._on_protection_update)
            stream.failed.connect(self._on_stream_error)

            self._gateway = gateway
            self._processor = processor
            self._kline_stream = stream
            self.klines = processor.klines
            self._running = True
            self._log_lines.clear()
            self._page = 0
            self.cmb_symbol.setEnabled(False)
            self.cmb_interval.setEnabled(False)
            self.params_widget.setEnabled(False)
            stream.start()
            initial_signal = processor.evaluate_latest_closed()
            if initial_signal is not None:
                self._place_signal_order(initial_signal)
            self._refresh_account(show_errors=False)
            get_logger().info(
                "实时策略启动: %s %s, 所需预热K线=%d, 实际=%d",
                symbol, interval, required_bars, len(klines))
            self._record_log(tr("realtime_started", symbol=symbol, interval=interval,
                                count=len(klines)), True)
            self.retranslate()
        except Exception as exc:  # noqa: BLE001
            if self._kline_stream is not None:
                self._kline_stream.stop()
            self._gateway = None
            self._processor = None
            self._kline_stream = None
            self._record_log(tr("live_error", err=exc), True)
            self._close_live_log()
            QMessageBox.warning(self, tr("app_title"), tr("live_error", err=exc))

    def stop_live(self):
        self._running = False
        if self._kline_stream is not None:
            self._kline_stream.stop()
        self._kline_stream = None
        self._processor = None
        self._gateway = None
        self._placing_order = False
        self._close_live_log()
        self.cmb_symbol.setEnabled(True)
        self.cmb_interval.setEnabled(True)
        self.params_widget.setEnabled(True)
        self.retranslate()

    def _close_all_positions_and_stop(self):
        """停止策略并市价平掉 Binance 账户的全部当前持仓。"""
        client = self._gateway.client if self._gateway is not None else None
        self._running = False
        self._placing_order = True
        stream = self._kline_stream
        self._kline_stream = None
        if stream is not None:
            stream.stop()

        try:
            if client is None:
                config = load_config()
                if not config.has_credentials:
                    raise RuntimeError(tr("live_no_credentials"))
                client = BinanceLiveGateway(config).client

            summary = client.close_all_positions()
            for item in summary["closed"]:
                order = item["order"]
                close_side = "SELL" if item["side"] == LONG else "BUY"
                self._insert_order(order, item["symbol"], close_side)
                self._record_log(tr(
                    "realtime_position_closed", symbol=item["symbol"],
                    side=item["side"], quantity=f"{item['quantity']:g}"), True)

            failures = summary["failed"]
            if failures:
                detail = "; ".join(
                    f"{item['symbol']} {item['side']} {item['quantity']:g}: "
                    f"{item['error']}" for item in failures)
                self._record_log(tr(
                    "realtime_close_positions_partial", err=detail), True)
                QMessageBox.warning(
                    self, tr("app_title"),
                    tr("realtime_close_positions_partial", err=detail))
            else:
                self._record_log(tr(
                    "realtime_all_positions_closed",
                    count=len(summary["closed"])), True)

            self._db.sync_positions(client.get_positions())
            self._refresh_record_tables()
        except Exception as exc:  # noqa: BLE001
            self._record_log(tr("realtime_close_positions_failed", err=exc), True)
            QMessageBox.warning(
                self, tr("app_title"),
                tr("realtime_close_positions_failed", err=exc))
        finally:
            self._placing_order = False
            self.stop_live()

    def _on_stream_error(self, error: str):
        self._record_log(tr("realtime_ws_error", err=error), False)

    def _record_log(self, message: str, is_trigger: bool = False):
        self._log_lines.append((message, is_trigger))
        if self._live_log_file is not None:
            try:
                self._live_log_file.write(message + "\n")
                self._live_log_file.flush()
            except OSError as exc:
                get_logger().warning("实盘会话日志写入失败: %s", exc)
        self._refresh_log_view()

    def _open_live_log(self):
        self._close_live_log()
        self._live_log_path = create_trader_live_log_path()
        self._live_log_file = open(
            self._live_log_path, "w", encoding="utf-8", buffering=1)
        get_logger().info("本次实盘日志: %s", self._live_log_path)

    def _close_live_log(self):
        log_file = self._live_log_file
        self._live_log_file = None
        if log_file is not None:
            try:
                log_file.flush()
                log_file.close()
            except OSError as exc:
                get_logger().warning("关闭实盘会话日志失败: %s", exc)

    def _on_closed_kline(self, kline):
        if not self._running or self._processor is None:
            return
        signal = self._processor.add_closed_kline(kline)
        self.klines = self._processor.klines
        self._latest_close = kline.close
        if signal is not None:
            self._place_signal_order(signal)

    def _restart_price_stream(self, *_args):
        if self._price_stream is not None:
            self._price_stream.stop()
        self._price_stream = None
        # 切换交易对后不沿用旧连接的价格；首个新价格到达前显示 REST PnL。
        self._live_prices.clear()
        symbol = self.cmb_symbol.currentText().strip().upper()
        if not symbol:
            self.lbl_latest_value.setText("—")
            return
        stream = PerpetualPriceStream(
            symbol=symbol, testnet=load_config().testnet, parent=self)
        stream.price_update.connect(
            lambda price, stream_symbol=symbol:
            self._on_live_price(stream_symbol, price))
        stream.failed.connect(self._on_stream_error)
        self._price_stream = stream
        self.lbl_latest_value.setText(f"{symbol} PERP  —")
        stream.start()

    def _on_symbol_changed(self, *_args):
        self._restart_price_stream()
        QTimer.singleShot(
            0, lambda: self._refresh_account(show_errors=False))

    def _on_live_price(self, symbol: str, price: float):
        current_symbol = self.cmb_symbol.currentText().strip().upper()
        if symbol != current_symbol:
            return
        self._latest_close = price
        self._live_prices[symbol] = price
        self.lbl_latest_value.setText(f"{symbol} PERP  {price:,.2f}")
        self._update_live_unrealized_pnl(symbol, price)

    def _place_signal_order(self, signal: LiveSignal):
        if self._placing_order or self._gateway is None:
            return
        symbol = self.cmb_symbol.currentText().strip().upper()
        try:
            # 保持回测的单持仓语义：账户中该交易对已有仓位时不叠加新首仓。
            has_position = self._gateway.client.has_open_position(symbol)
            if has_position is None:
                raise RuntimeError(f"无法查询 {symbol} 当前持仓")
            if has_position:
                self._record_log(tr("realtime_position_exists", symbol=symbol), True)
                return
            order = self._processor.order
            account = self._gateway.client.get_account_info()
            if not account:
                raise RuntimeError("Binance 账户接口未返回数据")
            margin_asset, available_balance = self._available_margin_balance(
                account, symbol)
            reference_price = self._latest_close or signal.kline.close
            target_notional = base_order_notional(
                order.total_capital, order.split_count)
            quantity = self._gateway.normalize_quantity(
                symbol, target_notional / reference_price)
            actual_notional = quantity * reference_price
            required_margin = required_order_margin(
                actual_notional, order.leverage, order.fee_rate_pct)
            self._record_log(tr(
                "realtime_order_margin_check", symbol=symbol,
                quantity=f"{quantity:g}", notional=f"{actual_notional:.2f}",
                leverage=f"{order.leverage:g}",
                required=f"{required_margin:.2f}", available=f"{available_balance:.2f}",
                asset=margin_asset), True)
            if available_balance < required_margin:
                raise RuntimeError(tr(
                    "realtime_margin_insufficient", symbol=symbol,
                    required=f"{required_margin:.2f}",
                    available=f"{available_balance:.2f}", asset=margin_asset))
            side = "BUY" if signal.direction == LONG else "SELL"
            position_mode = self._gateway.client.get_position_mode()
            position_side = signal.direction if position_mode is not False else None
            self._placing_order = True
            result = self._gateway.market_order(
                symbol, side, quantity, position_side=position_side)
            self._insert_order(result, symbol, side)
            order_id = result.get("orderId")
            if order_id is None:
                raise RuntimeError("Binance 开仓返回缺少 orderId")
            close_side = "SELL" if signal.direction == LONG else "BUY"
            protection = {
                "symbol": symbol,
                "signal_type": signal.direction,
                "signal_kline_index": signal.kline.index,
                "stop_loss": ({
                    "price_param": order.stop_loss, "price_type": "百分比",
                    "side": close_side, "position_side": signal.direction,
                } if order.stop_loss > 0 else None),
                "take_profit": ({
                    "price_param": order.take_profit, "price_type": "百分比",
                    "side": close_side, "position_side": signal.direction,
                } if order.take_profit > 0 else None),
            }
            try:
                self._kline_stream.monitor_filled_order(
                    str(order_id), {
                        "symbol": symbol, "side": side, "quantity": quantity,
                        "position_side": position_side or "BOTH",
                    }, protection)
            except Exception as protection_exc:  # noqa: BLE001
                self._record_log(tr(
                    "realtime_protection_failed", err=protection_exc), True)
                QMessageBox.warning(
                    self, tr("app_title"),
                    tr("realtime_protection_failed", err=protection_exc))
            self._record_log(tr(
                "realtime_order_sent", side=signal.direction,
                quantity=result.get("origQty", quantity), symbol=symbol,
                kline=signal.kline.index), True)
        except Exception as exc:  # noqa: BLE001
            self._record_log(tr("realtime_order_failed", err=exc), True)
            QMessageBox.warning(self, tr("app_title"), tr("live_error", err=exc))
        finally:
            self._placing_order = False

    def _on_protection_update(self, update: dict):
        """保存保护单及触发价，并刷新持仓/挂单表。"""
        try:
            symbol = str(update.get("symbol") or "").upper()
            direction = str(update.get("signal_type") or "").upper()
            avg_price = float(update.get("avg_price") or 0)
            quantity = float(update.get("executed_qty") or 0)
            tp_price = update.get("take_profit_price")
            sl_price = update.get("stop_loss_price")
            close_side = "SELL" if direction == LONG else "BUY"

            if self._gateway is not None:
                self._db.sync_positions(self._gateway.client.get_positions(symbol))
            self._db.set_position_protection(
                symbol, direction, tp_price=tp_price, sl_price=sl_price)

            protection_orders = (
                (update.get("take_profit_order_id"), "TAKE_PROFIT_MARKET", tp_price, "TP"),
                (update.get("stop_loss_order_id"), "STOP_MARKET", sl_price, "SL"),
            )
            for algo_id, order_type, trigger_price, action_type in protection_orders:
                if not algo_id:
                    continue
                self._db.upsert_order({
                    "orderId": str(algo_id), "algoId": str(algo_id),
                    "symbol": symbol, "side": close_side,
                    "positionSide": direction or "BOTH", "type": order_type,
                    "origQty": quantity, "stopPrice": trigger_price,
                    "price": trigger_price, "status": "NEW",
                    "action_type": action_type,
                    "use_type": f"{action_type}_CLOSE",
                })

            missing = []
            if tp_price is not None and not update.get("take_profit_order_id"):
                missing.append("TP")
            if sl_price is not None and not update.get("stop_loss_order_id"):
                missing.append("SL")
            if missing:
                warning = tr(
                    "realtime_protection_partial", missing=", ".join(missing))
                self._record_log(warning, True)
                QMessageBox.warning(self, tr("app_title"), warning)
            else:
                self._record_log(tr(
                    "realtime_protection_sent", symbol=symbol,
                    entry=f"{avg_price:.2f}",
                    tp=f"{float(tp_price):.2f}" if tp_price is not None else "Disabled",
                    sl=f"{float(sl_price):.2f}" if sl_price is not None else "Disabled"), True)
            self._refresh_record_tables()
        except Exception as exc:  # noqa: BLE001
            get_logger().exception("保存 TP/SL 保护单失败")
            self._record_log(tr("realtime_protection_failed", err=exc), True)

    def _refresh_account(self, show_errors: bool = True):
        """刷新余额和账户风险率。"""
        try:
            client = self._gateway.client if self._gateway is not None else None
            if client is None:
                config = load_config()
                if not config.has_credentials:
                    raise RuntimeError(tr("live_no_credentials"))
                gateway = BinanceLiveGateway(config)
                client = gateway.client
            account = client.get_account_info()
            if not account:
                raise RuntimeError("Binance 账户接口未返回数据")
            symbol = self.cmb_symbol.currentText().strip().upper()
            margin_asset, balance = self._available_margin_balance(
                account, symbol)
            risk = self._account_risk_ratio(account)
            if risk is None:
                risk = client.get_account_margin_ratio()
            self.lbl_balance_value.setText(
                f"{balance:,.2f} {margin_asset}")
            self.lbl_risk_value.setText(
                f"{risk * 100:.2f}%" if risk is not None else "0.00%")
            for remote_order in (
                client.get_order_history(symbol) + client.get_open_orders(symbol)):
                _, newly_filled = self._db.upsert_order(remote_order)
                if newly_filled:
                    self._db.record_filled_trade(
                        remote_order, balance_after=balance)
            self._db.sync_positions(client.get_positions())
            self._refresh_record_tables()
        except Exception as exc:  # noqa: BLE001
            if show_errors:
                QMessageBox.warning(self, tr("app_title"), tr("live_error", err=exc))

    @staticmethod
    def _account_risk_ratio(account: dict):
        """使用 Binance 账户汇总字段计算维持保证金风险率。"""
        try:
            maintenance = float(account.get("totalMaintMargin", 0) or 0)
            equity = float(account.get(
                "totalMarginBalance", account.get("totalWalletBalance", 0)) or 0)
            if equity > 0:
                return maintenance / equity
            if maintenance == 0:
                return 0.0
        except (TypeError, ValueError):
            pass
        return None

    @staticmethod
    def _margin_asset_for_symbol(symbol: str) -> str:
        symbol = symbol.upper()
        for asset in ("USDT", "USDC", "FDUSD", "BUSD"):
            if symbol.endswith(asset):
                return asset
        return "USDT"

    @classmethod
    def _available_margin_balance(cls, account: dict, symbol: str):
        """返回所选合约可实际使用的保证金币种与余额。"""
        asset_name = cls._margin_asset_for_symbol(symbol)
        multi_assets = account.get("multiAssetsMargin", False)
        if multi_assets is True or str(multi_assets).lower() == "true":
            return asset_name, float(account.get("availableBalance", 0) or 0)
        asset = next((
            row for row in account.get("assets", [])
            if str(row.get("asset", "")).upper() == asset_name
        ), {})
        return asset_name, float(asset.get("availableBalance", 0) or 0)

    def _insert_order(self, order: dict, symbol: str, side: str):
        order_id = order.get("orderId")
        if order_id is None:
            return
        normalized = dict(order)
        normalized.setdefault("symbol", symbol)
        normalized.setdefault("side", side)
        self._on_order_update(normalized)

    def _on_order_update(self, order: dict):
        try:
            _, newly_filled = self._db.upsert_order(order)
            if newly_filled:
                balance = self._number_from_label(self.lbl_balance_value.text())
                self._db.record_filled_trade(order, balance_after=balance)
            self._refresh_record_tables()
        except Exception as exc:  # noqa: BLE001
            get_logger().exception("保存订单状态失败")
            self._record_log(tr("db_write_error", err=exc), False)

    @staticmethod
    def _number_from_label(text: str):
        try:
            return float(text.split()[0].replace(",", ""))
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _format_number(value, digits=4) -> str:
        if value in (None, ""):
            return ""
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _format_local_time(value) -> str:
        """把 Binance/SQLite 的 UTC 时间转换为当前系统本地时区。"""
        if value in (None, ""):
            return ""
        try:
            if isinstance(value, (int, float)):
                timestamp = float(value)
                if abs(timestamp) >= 100_000_000_000:
                    timestamp /= 1000
                parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            elif isinstance(value, datetime):
                parsed = value
            else:
                text = str(value).strip()
                if text.replace(".", "", 1).isdigit():
                    timestamp = float(text)
                    if abs(timestamp) >= 100_000_000_000:
                        timestamp /= 1000
                    parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                else:
                    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return str(value)

    @staticmethod
    def _calculate_unrealized_pnl(position: dict, price: float):
        """按 USD-M 线性合约价格实时计算未实现盈亏。"""
        try:
            entry_price = float(position.get("avg_entry_price", 0) or 0)
            quantity = abs(float(position.get("quantity", 0) or 0))
            live_price = float(price)
        except (TypeError, ValueError):
            return None
        if entry_price <= 0 or quantity <= 0 or live_price <= 0:
            return None
        side = str(position.get("position_side", "") or "").upper()
        if side == LONG:
            return (live_price - entry_price) * quantity
        if side == "SHORT":
            return (entry_price - live_price) * quantity
        return None

    def _position_unrealized_pnl(self, position: dict):
        live_price = self._live_prices.get(str(position.get("symbol", "")).upper())
        if live_price is not None:
            calculated = self._calculate_unrealized_pnl(position, live_price)
            if calculated is not None:
                return calculated
        return position.get("unrealized_pnl")

    def _update_live_unrealized_pnl(self, symbol: str, price: float):
        """仅更新持仓表的 PnL 单元格，避免每个成交推送都重查数据库。"""
        if not hasattr(self, "position_table"):
            return
        for row_index, position in enumerate(self._current_position_rows):
            if str(position.get("symbol", "")).upper() != symbol:
                continue
            pnl = self._calculate_unrealized_pnl(position, price)
            if pnl is None:
                continue
            item = self.position_table.item(row_index, 6)
            if item is None:
                item = QTableWidgetItem()
                self.position_table.setItem(row_index, 6, item)
            item.setText(self._format_number(pnl))
            item.setForeground(QColor("#00a000" if pnl >= 0 else "#e00000"))

    def _fill_table(self, table: QTableWidget, rows, fields, pnl_columns=()):
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, field in enumerate(fields):
                value = field(row) if callable(field) else row.get(field, "")
                item = QTableWidgetItem("" if value is None else str(value))
                if column in pnl_columns:
                    try:
                        number = float(value)
                        item.setForeground(QColor("#00a000" if number >= 0 else "#e00000"))
                    except (TypeError, ValueError):
                        pass
                table.setItem(row_index, column, item)

    def _refresh_record_tables(self):
        if not hasattr(self, "position_table"):
            return
        n = self._format_number
        local_time = self._format_local_time
        positions = self._db.current_positions()
        self._current_position_rows = positions
        self._fill_table(self.position_table, positions, [
            "symbol", "position_mode", "position_side", lambda r: n(r["quantity"]),
            lambda r: n(r["avg_entry_price"], 2), lambda r: local_time(r["updated_at"]),
            lambda r: n(self._position_unrealized_pnl(r)), lambda r: n(r["tp_price"], 2),
            lambda r: n(r["sl_price"], 2), lambda r: n(r["liquidation_price"], 2),
        ], pnl_columns=(6,))
        self._fill_table(self.position_history_table, self._db.position_history(), [
            "symbol", "side", lambda r: n(r["entry_price"], 2),
            lambda r: n(r["close_price"], 2), lambda r: n(r["quantity"]),
            lambda r: n(r["realized_pnl"]), lambda r: n(r["commission"]),
            "position_mode", lambda r: local_time(r["updated_at"]),
        ], pnl_columns=(5,))
        self._fill_table(self.open_orders_table, self._db.current_orders(), [
            "order_id", "symbol", "trade_direction", "action_type", "order_type",
            lambda r: n(r["price"], 2), lambda r: n(r["quantity"]),
            lambda r: n(r["filled_qty"]), "status",
            lambda r: local_time(r["updated_at"]),
        ])
        order_history = self._db.order_history()
        selected_status = self.order_status_filter.currentText()
        if selected_status != "ALL":
            order_history = [
                row for row in order_history if row["status"] == selected_status]
        self._fill_table(self.order_history_table, order_history, [
            "symbol", "side", "order_type", lambda r: n(r["price"], 2),
            lambda r: n(r["avg_price"], 2), lambda r: n(r["quantity"]),
            lambda r: n(r["filled_qty"]), lambda r: n(r["commission"]),
            "status", lambda r: local_time(r["updated_at"]),
        ])
    def _cancel_selected_order(self):
        row = self.open_orders_table.currentRow()
        if row < 0:
            QMessageBox.information(
                self, tr("app_title"), tr("select_order_to_cancel"))
            return
        order_id_item = self.open_orders_table.item(row, 0)
        symbol_item = self.open_orders_table.item(row, 1)
        if order_id_item is None or symbol_item is None:
            return
        order_id, symbol = order_id_item.text(), symbol_item.text()
        try:
            client = self._gateway.client if self._gateway is not None else None
            if client is None:
                config = load_config()
                if not config.has_credentials:
                    raise RuntimeError(tr("live_no_credentials"))
                client = BinanceLiveGateway(config).client
            result = client.cancel_order(symbol, order_id)
            if not result:
                raise RuntimeError(tr("cancel_order_failed"))
            self._on_order_update(result)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, tr("app_title"), tr("live_error", err=exc))

    def close_listener(self):
        if self._price_stream is not None:
            self._price_stream.stop()
            self._price_stream = None
        self.stop_live()
