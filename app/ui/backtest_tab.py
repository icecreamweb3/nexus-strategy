"""回测页 / Backtest tab — 按截图风格：导入数据 / 参数 / 结果 / 明细 / 日志."""
import csv
import json
import os
from dataclasses import asdict

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from app.backtest.data_loader import DataLoadError, load_klines
from app.backtest.engine import BacktestEngine, OrderParams, StrategyParams
from app.backtest.stats import compute_stats
from app.i18n import tr
from app.logger import get_logger


class BacktestWorker(QThread):
    log_line = pyqtSignal(str, bool)
    finished_ok = pyqtSignal(list, object)
    failed = pyqtSignal(str)

    def __init__(self, klines, sp: StrategyParams, op: OrderParams, parent=None):
        super().__init__(parent)
        self._klines = klines
        self._sp = sp
        self._op = op
        self._engine = None

    def cancel(self):
        if self._engine is not None:
            self._engine.cancelled = True

    def run(self):
        try:
            self._engine = BacktestEngine(
                self._klines, self._sp, self._op,
                log=lambda msg, is_trigger=False: self.log_line.emit(msg, is_trigger),
            )
            trades = self._engine.run()
            self.finished_ok.emit(trades, compute_stats(trades))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


def _dspin(value: float, maximum: float = 1e9, decimals: int = 2, minimum: float = 0.0) -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(minimum, maximum)
    w.setDecimals(decimals)
    w.setValue(value)
    return w


def _ispin(value: int, maximum: int = 100000, minimum: int = 0) -> QSpinBox:
    w = QSpinBox()
    w.setRange(minimum, maximum)
    w.setValue(value)
    return w


class BacktestTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.klines = []
        self.data_path = ""
        self.trades = []
        self.stats = None
        self._worker = None
        self._log_lines = []   # (text, is_trigger)
        self._page = 0
        self._retr = []        # [(setter_callable, key)] 用于语言切换
        self._build_ui()
        self.retranslate()

    # ---------- i18n helpers ----------

    def _reg(self, setter, key):
        self._retr.append((setter, key))

    def _label(self, key) -> QLabel:
        lab = QLabel()
        self._reg(lab.setText, key)
        return lab

    # ---------- UI 构建 ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.addWidget(self._build_import_section())
        root.addWidget(self._build_params_section(), stretch=0)
        root.addWidget(self._build_results_section())
        root.addWidget(self._build_trades_section(), stretch=1)
        root.addWidget(self._build_log_section(), stretch=1)

    def _build_import_section(self) -> QGroupBox:
        box = QGroupBox()
        self._reg(box.setTitle, "sec_import")
        lay = QHBoxLayout(box)
        self.lbl_file = QLabel()
        lay.addWidget(self.lbl_file, stretch=1)
        self.btn_file = QPushButton()
        self._reg(self.btn_file.setText, "btn_choose_file")
        self.btn_file.clicked.connect(self._choose_file)
        lay.addWidget(self.btn_file)
        return box

    def _build_params_section(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)

        # ---- 左：策略参数 ----
        strat_box = QGroupBox()
        self._reg(strat_box.setTitle, "sec_strategy")
        grid = QGridLayout(strat_box)

        self.btn_export_params = QPushButton()
        self._reg(self.btn_export_params.setText, "export_params")
        self.btn_export_params.clicked.connect(self._export_params)
        self.btn_import_params = QPushButton()
        self._reg(self.btn_import_params.setText, "import_params")
        self.btn_import_params.clicked.connect(self._import_params)
        grid.addWidget(self.btn_export_params, 0, 0)
        grid.addWidget(self.btn_import_params, 0, 1)

        r = 1
        self.chk_trend = QCheckBox()
        self.chk_trend.setChecked(True)
        self._reg(self.chk_trend.setText, "trend_strategy")
        grid.addWidget(self.chk_trend, r, 0, 1, 2)
        r += 1
        self.sp_trend_count = _ispin(2)
        self.sp_trend_cum = _dspin(0.06, decimals=4)
        self.sp_trend_last_n = _ispin(1, minimum=1)
        self.sp_trend_single = _dspin(0.04, decimals=4)
        for key, w in (("trend_count", self.sp_trend_count),
                       ("trend_cum_pct", self.sp_trend_cum),
                       ("trend_last_n", self.sp_trend_last_n),
                       ("trend_single_pct", self.sp_trend_single)):
            grid.addWidget(self._label(key), r, 0)
            grid.addWidget(w, r, 1)
            r += 1

        self.chk_pattern = QCheckBox()
        self.chk_pattern.setChecked(True)
        self._reg(self.chk_pattern.setText, "pattern_strategy")
        grid.addWidget(self.chk_pattern, r, 0, 1, 2)
        r += 1
        self.sp_long_bear_count = _ispin(2)
        self.sp_long_bear_up = _dspin(0.8, decimals=4)
        self.sp_long_bear_low = _dspin(0.7, decimals=4)
        self.sp_rev_bull_up = _dspin(0.6, decimals=4)
        self.sp_rev_bull_low = _dspin(0.5, decimals=4)
        for key, w in (("pattern_long", self.sp_long_bear_count),
                       ("bear_body_upper", self.sp_long_bear_up),
                       ("bear_body_lower", self.sp_long_bear_low),
                       ("rev_bull_body_upper", self.sp_rev_bull_up),
                       ("rev_bull_body_lower", self.sp_rev_bull_low)):
            grid.addWidget(self._label(key), r, 0)
            grid.addWidget(w, r, 1)
            r += 1
        self.sp_short_bull_count = _ispin(2)
        self.sp_short_bull_up = _dspin(0.7, decimals=4)
        self.sp_short_bull_low = _dspin(0.8, decimals=4)
        self.sp_rev_bear_up = _dspin(0.5, decimals=4)
        self.sp_rev_bear_low = _dspin(0.6, decimals=4)
        for key, w in (("pattern_short", self.sp_short_bull_count),
                       ("bull_body_upper", self.sp_short_bull_up),
                       ("bull_body_lower", self.sp_short_bull_low),
                       ("rev_bear_body_upper", self.sp_rev_bear_up),
                       ("rev_bear_body_lower", self.sp_rev_bear_low)):
            grid.addWidget(self._label(key), r, 0)
            grid.addWidget(w, r, 1)
            r += 1

        self.chk_reverse = QCheckBox()
        self.chk_reverse.setChecked(True)
        self._reg(self.chk_reverse.setText, "reverse_strategy")
        grid.addWidget(self.chk_reverse, r, 0, 1, 2)
        r += 1
        self.sp_body_low = _dspin(1.0, decimals=4)
        self.sp_body_high = _dspin(1000000.0, decimals=4)
        for key, w in (("body_ratio_low", self.sp_body_low),
                       ("body_ratio_high", self.sp_body_high)):
            grid.addWidget(self._label(key), r, 0)
            grid.addWidget(w, r, 1)
            r += 1

        self.chk_volume = QCheckBox()
        self.chk_volume.setChecked(True)
        self._reg(self.chk_volume.setText, "volume_strategy")
        grid.addWidget(self.chk_volume, r, 0, 1, 2)
        r += 1
        self.sp_vol_ratio = _dspin(0.6, decimals=4)
        grid.addWidget(self._label("volume_ratio"), r, 0)
        grid.addWidget(self.sp_vol_ratio, r, 1)
        r += 1

        self.btn_start = QPushButton()
        self._reg(self.btn_start.setText, "start_backtest")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-size: 15px;"
            " font-weight: bold; border-radius: 4px; }"
            "QPushButton:disabled { background-color: #9e9e9e; }")
        self.btn_start.clicked.connect(self._start_backtest)
        grid.addWidget(self.btn_start, r, 0, 1, 2)

        # ---- 右：开单参数 ----
        order_box = QGroupBox()
        self._reg(order_box.setTitle, "sec_order_params")
        ogrid = QGridLayout(order_box)

        self.sp_position = _dspin(10000.0)
        self.sp_fee = _dspin(0.03, decimals=4)
        self.sp_stop_loss = _dspin(500.0)
        self.sp_cooldown = _ispin(10)
        self.sp_take_profit = _dspin(500.0)
        self.sp_min_tp = _dspin(100.0)
        self.cmb_order_type = QComboBox()
        self.sp_limit_offset = _dspin(100.0)
        self.sp_limit_valid = _ispin(10, minimum=1)
        self.cmb_direction = QComboBox()
        self.cmb_reverse = QComboBox()

        row = 0
        for key, w in (("position_size", self.sp_position), ("fee_rate", self.sp_fee)):
            ogrid.addWidget(self._label(key), row, 0)
            ogrid.addWidget(w, row, 1)
            row += 1
        ogrid.addWidget(self._label("stop_loss_type"), row, 0)
        ogrid.addWidget(self.sp_stop_loss, row, 1)
        ogrid.addWidget(self._label("stop_cooldown"), row, 2)
        ogrid.addWidget(self.sp_cooldown, row, 3)
        row += 1
        ogrid.addWidget(self._label("take_profit_type"), row, 0)
        ogrid.addWidget(self.sp_take_profit, row, 1)
        ogrid.addWidget(self._label("min_take_profit"), row, 2)
        ogrid.addWidget(self.sp_min_tp, row, 3)
        row += 1
        ogrid.addWidget(self._label("order_type"), row, 0)
        ogrid.addWidget(self.cmb_order_type, row, 1)
        ogrid.addWidget(self._label("limit_offset"), row, 2)
        ogrid.addWidget(self.sp_limit_offset, row, 3)
        ogrid.addWidget(self._label("limit_valid"), row, 4)
        ogrid.addWidget(self.sp_limit_valid, row, 5)
        row += 1
        ogrid.addWidget(self._label("direction"), row, 0)
        ogrid.addWidget(self.cmb_direction, row, 1)
        ogrid.addWidget(self._label("reverse_trading"), row, 2)
        ogrid.addWidget(self.cmb_reverse, row, 3)
        row += 1

        self.chk_short_look = QCheckBox()
        self.chk_short_look.setChecked(True)
        self.sp_short_look_n = _ispin(10, minimum=1)
        self.sp_short_dev = _dspin(100.0)
        self.chk_long_look = QCheckBox()
        self.chk_long_look.setChecked(True)
        self.sp_long_look_n = _ispin(10, minimum=1)
        self.sp_long_dev = _dspin(100.0)
        self.chk_rev_vol = QCheckBox()
        self.chk_rev_vol.setChecked(True)
        self.sp_rev_vol_n = _ispin(10, minimum=1)
        self.sp_rev_vol_mult = _dspin(1.2, decimals=4)
        self.chk_body_edge = QCheckBox()
        self.chk_body_edge.setChecked(True)
        self.sp_edge_long_n = _ispin(10, minimum=1)
        self.sp_edge_short_n = _ispin(10, minimum=1)

        ogrid.addWidget(self._label("short_lookback"), row, 0)
        ogrid.addWidget(self.chk_short_look, row, 1)
        ogrid.addWidget(self._label("lookback_n"), row, 2)
        ogrid.addWidget(self.sp_short_look_n, row, 3)
        ogrid.addWidget(self._label("deviation"), row, 4)
        ogrid.addWidget(self.sp_short_dev, row, 5)
        row += 1
        ogrid.addWidget(self._label("long_lookback"), row, 0)
        ogrid.addWidget(self.chk_long_look, row, 1)
        ogrid.addWidget(self._label("lookback_n"), row, 2)
        ogrid.addWidget(self.sp_long_look_n, row, 3)
        ogrid.addWidget(self._label("deviation"), row, 4)
        ogrid.addWidget(self.sp_long_dev, row, 5)
        row += 1
        ogrid.addWidget(self._label("reverse_volume_check"), row, 0)
        ogrid.addWidget(self.chk_rev_vol, row, 1)
        ogrid.addWidget(self._label("lookback_n"), row, 2)
        ogrid.addWidget(self.sp_rev_vol_n, row, 3)
        ogrid.addWidget(self._label("volume_mult"), row, 4)
        ogrid.addWidget(self.sp_rev_vol_mult, row, 5)
        row += 1
        ogrid.addWidget(self._label("reverse_body_edge_check"), row, 0)
        ogrid.addWidget(self.chk_body_edge, row, 1)
        ogrid.addWidget(self._label("body_edge_long_n"), row, 2)
        ogrid.addWidget(self.sp_edge_long_n, row, 3)
        ogrid.addWidget(self._label("body_edge_short_n"), row, 4)
        ogrid.addWidget(self.sp_edge_short_n, row, 5)

        lay.addWidget(strat_box, stretch=3)
        lay.addWidget(order_box, stretch=2)
        return wrap

    def _build_results_section(self) -> QGroupBox:
        box = QGroupBox()
        self._reg(box.setTitle, "sec_results")
        lay = QVBoxLayout(box)
        self.lbl_result_1 = QLabel("—")
        self.lbl_result_2 = QLabel("—")
        for lab in (self.lbl_result_1, self.lbl_result_2):
            f = lab.font()
            f.setPointSize(11)
            f.setBold(True)
            lab.setFont(f)
            lay.addWidget(lab)
        return box

    def _build_trades_section(self) -> QGroupBox:
        box = QGroupBox()
        self._reg(box.setTitle, "sec_trades")
        lay = QVBoxLayout(box)
        self.btn_export_trades = QPushButton()
        self._reg(self.btn_export_trades.setText, "export_trades")
        self.btn_export_trades.clicked.connect(self._export_trades)
        lay.addWidget(self.btn_export_trades, alignment=Qt.AlignLeft)
        self.table = QTableWidget(0, 9)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table)
        return box

    def _build_log_section(self) -> QGroupBox:
        box = QGroupBox()
        self._reg(box.setTitle, "sec_log")
        lay = QVBoxLayout(box)

        bar = QHBoxLayout()
        self.btn_toggle_log = QPushButton()
        self._reg(self.btn_toggle_log.setText, "toggle_log")
        self.btn_toggle_log.clicked.connect(
            lambda: self.log_view.setVisible(not self.log_view.isVisible()))
        self.btn_export_log = QPushButton()
        self._reg(self.btn_export_log.setText, "export_log")
        self.btn_export_log.clicked.connect(self._export_log)
        self.chk_triggers = QCheckBox()
        self._reg(self.chk_triggers.setText, "only_triggers")
        self.chk_triggers.stateChanged.connect(self._refresh_log_view)
        self.btn_show_all = QPushButton()
        self._reg(self.btn_show_all.setText, "show_all")
        self.btn_show_all.clicked.connect(self._show_all_logs)
        self.btn_prev = QPushButton()
        self._reg(self.btn_prev.setText, "prev_page")
        self.btn_prev.clicked.connect(lambda: self._turn_page(-1))
        self.btn_next = QPushButton()
        self._reg(self.btn_next.setText, "next_page")
        self.btn_next.clicked.connect(lambda: self._turn_page(1))
        self.lbl_page = QLabel()
        for w in (self.btn_toggle_log, self.btn_export_log, self.chk_triggers,
                  self.btn_show_all, self.btn_prev, self.btn_next, self.lbl_page):
            bar.addWidget(w)
        bar.addStretch(1)
        lay.addLayout(bar)

        search_bar = QHBoxLayout()
        self.edit_search = QLineEdit()
        self.edit_search.textChanged.connect(self._refresh_log_view)
        search_bar.addWidget(self.edit_search, stretch=1)
        self.lbl_page_size = QLabel()
        self._reg(self.lbl_page_size.setText, "page_size")
        self.sp_page_size = _ispin(5000, maximum=100000, minimum=10)
        self.sp_page_size.valueChanged.connect(self._refresh_log_view)
        search_bar.addWidget(self.lbl_page_size)
        search_bar.addWidget(self.sp_page_size)
        lay.addLayout(search_bar)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        lay.addWidget(self.log_view)
        return box

    # ---------- 语言切换 ----------

    def retranslate(self):
        for setter, key in self._retr:
            setter(tr(key))
        self._rebuild_combos()
        self.lbl_file.setText(
            tr("loaded_file", name=os.path.basename(self.data_path), count=len(self.klines))
            if self.klines else tr("no_file"))
        self.edit_search.setPlaceholderText(tr("search_placeholder"))
        self._fill_table()
        self._show_stats()
        self._refresh_log_view()

    def _rebuild_combos(self):
        combos = (
            (self.cmb_order_type, ("limit_order", "market_order")),
            (self.cmb_direction, ("dir_both", "dir_long", "dir_short")),
            (self.cmb_reverse, ("enabled", "disabled")),
        )
        for combo, keys in combos:
            idx = max(combo.currentIndex(), 0)
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([tr(k) for k in keys])
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        self.table.setHorizontalHeaderLabels([
            tr("col_no"), tr("col_type"), tr("col_side"),
            tr("col_entry_kline"), tr("col_entry_price"),
            tr("col_exit_kline"), tr("col_exit_price"),
            tr("col_pnl"), tr("col_fee"),
        ])

    # ---------- 数据导入 ----------

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("btn_choose_file"), "", "Data Files (*.csv *.xlsx)")
        if not path:
            return
        try:
            self.klines = load_klines(path)
            self.data_path = path
        except (DataLoadError, OSError) as exc:
            QMessageBox.warning(self, tr("app_title"), tr("err_load_file", err=exc))
            return
        self.lbl_file.setText(tr("loaded_file", name=os.path.basename(path), count=len(self.klines)))
        get_logger().info("加载K线数据 %s (%d 条)", path, len(self.klines))

    # ---------- 参数收集 ----------

    def _collect_params(self):
        sp = StrategyParams(
            trend_enabled=self.chk_trend.isChecked(),
            trend_kline_count=self.sp_trend_count.value(),
            trend_cum_pct=self.sp_trend_cum.value(),
            trend_last_n=self.sp_trend_last_n.value(),
            trend_single_pct=self.sp_trend_single.value(),
            pattern_enabled=self.chk_pattern.isChecked(),
            long_bear_count=self.sp_long_bear_count.value(),
            long_bear_body_upper=self.sp_long_bear_up.value(),
            long_bear_body_lower=self.sp_long_bear_low.value(),
            rev_bull_body_upper=self.sp_rev_bull_up.value(),
            rev_bull_body_lower=self.sp_rev_bull_low.value(),
            short_bull_count=self.sp_short_bull_count.value(),
            short_bull_body_upper=self.sp_short_bull_up.value(),
            short_bull_body_lower=self.sp_short_bull_low.value(),
            rev_bear_body_upper=self.sp_rev_bear_up.value(),
            rev_bear_body_lower=self.sp_rev_bear_low.value(),
            reverse_enabled=self.chk_reverse.isChecked(),
            body_ratio_min=self.sp_body_low.value(),
            body_ratio_max=self.sp_body_high.value(),
            volume_enabled=self.chk_volume.isChecked(),
            volume_ratio=self.sp_vol_ratio.value(),
        )
        op = OrderParams(
            position_size=self.sp_position.value(),
            fee_rate_pct=self.sp_fee.value(),
            stop_loss=self.sp_stop_loss.value(),
            stop_cooldown=self.sp_cooldown.value(),
            take_profit=self.sp_take_profit.value(),
            min_take_profit=self.sp_min_tp.value(),
            order_type="LIMIT" if self.cmb_order_type.currentIndex() == 0 else "MARKET",
            limit_offset=self.sp_limit_offset.value(),
            limit_valid_klines=self.sp_limit_valid.value(),
            direction=("BOTH", "LONG", "SHORT")[self.cmb_direction.currentIndex()],
            reverse_trading=self.cmb_reverse.currentIndex() == 0,
            short_lookback_enabled=self.chk_short_look.isChecked(),
            short_lookback_n=self.sp_short_look_n.value(),
            short_deviation=self.sp_short_dev.value(),
            long_lookback_enabled=self.chk_long_look.isChecked(),
            long_lookback_n=self.sp_long_look_n.value(),
            long_deviation=self.sp_long_dev.value(),
            reverse_volume_enabled=self.chk_rev_vol.isChecked(),
            reverse_volume_n=self.sp_rev_vol_n.value(),
            reverse_volume_mult=self.sp_rev_vol_mult.value(),
            reverse_body_edge_enabled=self.chk_body_edge.isChecked(),
            body_edge_long_n=self.sp_edge_long_n.value(),
            body_edge_short_n=self.sp_edge_short_n.value(),
        )
        return sp, op

    def _export_params(self):
        path, _ = QFileDialog.getSaveFileName(self, "", "params.json", "JSON (*.json)")
        if not path:
            return
        sp, op = self._collect_params()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"strategy": asdict(sp), "order": asdict(op)}, f, indent=2, ensure_ascii=False)

    def _import_params(self):
        path, _ = QFileDialog.getOpenFileName(self, "", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            sp = StrategyParams(**data.get("strategy", {}))
            op = OrderParams(**data.get("order", {}))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            QMessageBox.warning(self, tr("app_title"), tr("err_load_file", err=exc))
            return
        self.chk_trend.setChecked(sp.trend_enabled)
        self.sp_trend_count.setValue(sp.trend_kline_count)
        self.sp_trend_cum.setValue(sp.trend_cum_pct)
        self.sp_trend_last_n.setValue(sp.trend_last_n)
        self.sp_trend_single.setValue(sp.trend_single_pct)
        self.chk_pattern.setChecked(sp.pattern_enabled)
        self.sp_long_bear_count.setValue(sp.long_bear_count)
        self.sp_long_bear_up.setValue(sp.long_bear_body_upper)
        self.sp_long_bear_low.setValue(sp.long_bear_body_lower)
        self.sp_rev_bull_up.setValue(sp.rev_bull_body_upper)
        self.sp_rev_bull_low.setValue(sp.rev_bull_body_lower)
        self.sp_short_bull_count.setValue(sp.short_bull_count)
        self.sp_short_bull_up.setValue(sp.short_bull_body_upper)
        self.sp_short_bull_low.setValue(sp.short_bull_body_lower)
        self.sp_rev_bear_up.setValue(sp.rev_bear_body_upper)
        self.sp_rev_bear_low.setValue(sp.rev_bear_body_lower)
        self.chk_reverse.setChecked(sp.reverse_enabled)
        self.sp_body_low.setValue(sp.body_ratio_min)
        self.sp_body_high.setValue(sp.body_ratio_max)
        self.chk_volume.setChecked(sp.volume_enabled)
        self.sp_vol_ratio.setValue(sp.volume_ratio)
        self.sp_position.setValue(op.position_size)
        self.sp_fee.setValue(op.fee_rate_pct)
        self.sp_stop_loss.setValue(op.stop_loss)
        self.sp_cooldown.setValue(op.stop_cooldown)
        self.sp_take_profit.setValue(op.take_profit)
        self.sp_min_tp.setValue(op.min_take_profit)
        self.cmb_order_type.setCurrentIndex(0 if op.order_type == "LIMIT" else 1)
        self.sp_limit_offset.setValue(op.limit_offset)
        self.sp_limit_valid.setValue(op.limit_valid_klines)
        self.cmb_direction.setCurrentIndex(("BOTH", "LONG", "SHORT").index(op.direction))
        self.cmb_reverse.setCurrentIndex(0 if op.reverse_trading else 1)
        self.chk_short_look.setChecked(op.short_lookback_enabled)
        self.sp_short_look_n.setValue(op.short_lookback_n)
        self.sp_short_dev.setValue(op.short_deviation)
        self.chk_long_look.setChecked(op.long_lookback_enabled)
        self.sp_long_look_n.setValue(op.long_lookback_n)
        self.sp_long_dev.setValue(op.long_deviation)
        self.chk_rev_vol.setChecked(op.reverse_volume_enabled)
        self.sp_rev_vol_n.setValue(op.reverse_volume_n)
        self.sp_rev_vol_mult.setValue(op.reverse_volume_mult)
        self.chk_body_edge.setChecked(op.reverse_body_edge_enabled)
        self.sp_edge_long_n.setValue(op.body_edge_long_n)
        self.sp_edge_short_n.setValue(op.body_edge_short_n)

    # ---------- 回测执行 ----------

    def _start_backtest(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.btn_start.setEnabled(False)
            return
        if not self.klines:
            QMessageBox.information(self, tr("app_title"), tr("err_no_data"))
            return
        sp, op = self._collect_params()
        self._log_lines.clear()
        self._page = 0
        self.trades = []
        self.stats = None
        self._fill_table()
        self.btn_start.setEnabled(False)
        self.lbl_result_1.setText(tr("backtest_running"))
        self.lbl_result_2.setText("")

        self._worker = BacktestWorker(self.klines, sp, op, self)
        self._worker.log_line.connect(self._on_log_line)
        self._worker.finished_ok.connect(self._on_backtest_done)
        self._worker.failed.connect(self._on_backtest_failed)
        self._worker.finished.connect(lambda: self.btn_start.setEnabled(True))
        self._worker.start()

    def _on_log_line(self, msg: str, is_trigger: bool):
        self._log_lines.append((msg, is_trigger))
        if len(self._log_lines) % 500 == 0:
            self._refresh_log_view()

    def _on_backtest_done(self, trades, stats):
        self.trades = trades
        self.stats = stats
        self._show_stats()
        self._fill_table()
        self._refresh_log_view()
        get_logger().info("回测完成: %d 笔, 总盈亏 %.2f", stats.total_trades, stats.total_pnl)

    def _on_backtest_failed(self, err: str):
        QMessageBox.warning(self, tr("app_title"), err)
        self.lbl_result_1.setText("—")

    # ---------- 结果展示 ----------

    def _show_stats(self):
        s = self.stats
        if s is None:
            return
        dd_interval = ""
        if s.drawdown_interval:
            dd_interval = f" (#{s.drawdown_interval[0]}-#{s.drawdown_interval[1]})"
        self.lbl_result_1.setText(
            f"{tr('total_trades')}: {s.total_trades}  |  "
            f"{tr('total_pnl')}: {s.total_pnl:.2f}  |  "
            f"{tr('total_fees')}: {s.total_fees:.2f}")
        self.lbl_result_2.setText(
            f"{tr('short_count')}: {s.short_count}  |  "
            f"{tr('long_count')}: {s.long_count}  |  "
            f"{tr('max_drawdown')}: {s.max_drawdown:.2f}{dd_interval}")
        color = "#d32f2f" if s.total_pnl < 0 else "#388e3c"
        self.lbl_result_1.setStyleSheet(f"color: {color};" if s.total_trades else "")

    _TYPE_KEYS = {"TP": "type_tp", "SL": "type_sl", "REVERSE": "type_reverse"}

    def _fill_table(self):
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.trades))
        for row, t in enumerate(self.trades):
            vals = (
                f"#{t.no}", f"[{tr(self._TYPE_KEYS.get(t.exit_type, 'type_tp'))}] {t.side}",
                f"#{t.entry_kline}", f"{t.entry_price:.2f}",
                f"#{t.exit_kline}", f"{t.exit_price:.2f}",
                f"{t.pnl:+.2f}", f"{t.fee:.2f}",
            )
            # 编号列单独放，类型列带颜色
            items = [QTableWidgetItem(v) for v in vals]
            if t.exit_type == "SL":
                items[1].setForeground(QColor("#d32f2f"))
            else:
                items[1].setForeground(QColor("#388e3c"))
            items[6].setForeground(QColor("#d32f2f" if t.pnl < 0 else "#388e3c"))
            for col, item in enumerate(items):
                self.table.setItem(row, col, item)

    def _export_trades(self):
        if not self.trades:
            return
        path, _ = QFileDialog.getSaveFileName(self, "", "trades.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow([tr("col_no"), tr("col_type"), tr("col_side"),
                        tr("col_entry_kline"), tr("col_entry_price"),
                        tr("col_exit_kline"), tr("col_exit_price"),
                        tr("col_pnl"), tr("col_fee")])
            for t in self.trades:
                w.writerow([t.no, tr(self._TYPE_KEYS.get(t.exit_type, "type_tp")), t.side,
                            t.entry_kline, f"{t.entry_price:.2f}",
                            t.exit_kline, f"{t.exit_price:.2f}",
                            f"{t.pnl:.2f}", f"{t.fee:.2f}"])

    # ---------- 日志展示 ----------

    def _filtered_logs(self):
        keyword = self.edit_search.text().strip().lower()
        only_triggers = self.chk_triggers.isChecked()
        return [msg for msg, is_trigger in self._log_lines
                if (not only_triggers or is_trigger)
                and (not keyword or keyword in msg.lower())]

    def _refresh_log_view(self):
        lines = self._filtered_logs()
        size = max(self.sp_page_size.value(), 1)
        total_pages = max((len(lines) + size - 1) // size, 1)
        self._page = min(self._page, total_pages - 1)
        start = self._page * size
        self.log_view.setPlainText("\n".join(lines[start:start + size]))
        self.lbl_page.setText(tr("page_info", cur=self._page + 1, total=total_pages))

    def _turn_page(self, delta: int):
        lines = self._filtered_logs()
        size = max(self.sp_page_size.value(), 1)
        total_pages = max((len(lines) + size - 1) // size, 1)
        self._page = max(0, min(self._page + delta, total_pages - 1))
        self._refresh_log_view()

    def _show_all_logs(self):
        self.chk_triggers.setChecked(False)
        self.edit_search.clear()
        self._page = 0
        self._refresh_log_view()

    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "", "backtest.log", "Log (*.log *.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(msg for msg, _ in self._log_lines))
