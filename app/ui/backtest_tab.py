"""回测页 / Backtest tab — 按截图风格：导入数据 / 参数 / 结果 / 明细 / 日志."""
import csv
import os

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from app.backtest.data_loader import DataLoadError, load_klines
from app.backtest.engine import BacktestEngine, OrderParams, StrategyParams
from app.backtest.params_io import ParamsFileError, load_params, save_params
from app.backtest.stats import compute_stats
from app.config import APP_DIR
from app.i18n import i18n, tr
from app.logger import create_backtest_log_path, get_logger


class BacktestWorker(QThread):
    log_line = pyqtSignal(str, bool)
    finished_ok = pyqtSignal(list, object)
    failed = pyqtSignal(str)

    def __init__(self, klines, sp: StrategyParams, op: OrderParams, parent=None):
        super().__init__(parent)
        self._klines = klines
        self._sp = sp
        self._op = op
        self._language = i18n().lang
        self._engine = None
        self.log_path = ""

    def cancel(self):
        if self._engine is not None:
            self._engine.cancelled = True

    def run(self):
        try:
            self.log_path = create_backtest_log_path()
            with open(self.log_path, "w", encoding="utf-8", buffering=1) as log_file:
                def record(message, is_trigger=False):
                    log_file.write(message + "\n")
                    self.log_line.emit(message, is_trigger)

                self._engine = BacktestEngine(
                    self._klines, self._sp, self._op, log=record,
                    translate=lambda key, **kwargs: i18n().tr_for(
                        self._language, key, **kwargs),
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
    w.setAlignment(Qt.AlignLeft)
    return w


def _ispin(value: int, maximum: int = 100000, minimum: int = 0) -> QSpinBox:
    w = QSpinBox()
    w.setRange(minimum, maximum)
    w.setValue(value)
    w.setAlignment(Qt.AlignLeft)
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
        self._load_saved_default_params(show_errors=False)

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

        self.btn_start = QPushButton()
        self._reg(self.btn_start.setText, "start_backtest")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start_backtest)
        lay.addWidget(self.btn_start)
        return box

    def _build_params_section(self) -> QWidget:
        # 策略条件与订单参数属于同一个参数设置 Group，内部横向分隔。
        wrap = QGroupBox()
        self._reg(wrap.setTitle, "sec_params")
        lay = QVBoxLayout(wrap)

        # ---- 左：策略参数 ----
        strat_box = QGroupBox()
        self._reg(strat_box.setTitle, "sec_strategy")
        strat_box.setFlat(True)
        grid = QGridLayout(strat_box)

        self.btn_reset_params = QPushButton()
        self._reg(self.btn_reset_params.setText, "reset_params")
        self.btn_reset_params.clicked.connect(self._reset_params)
        self.btn_save_default_params = QPushButton()
        self._reg(self.btn_save_default_params.setText, "save_default_params")
        self.btn_save_default_params.clicked.connect(self._save_default_params)
        self.btn_export_params = QPushButton()
        self._reg(self.btn_export_params.setText, "export_params")
        self.btn_export_params.clicked.connect(self._export_params)
        self.btn_import_params = QPushButton()
        self._reg(self.btn_import_params.setText, "import_params")
        self.btn_import_params.clicked.connect(self._import_params)
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_reset_params)
        toolbar.addWidget(self.btn_save_default_params)
        toolbar.addWidget(self.btn_import_params)
        toolbar.addWidget(self.btn_export_params)

        r = 0
        # 每个条件一个勾选框；全部勾选条件满足才确认信号
        # 成交量：当前K线成交量 >= 前N根均量 × 阈值
        self.chk_volume = QCheckBox()
        self.chk_volume.setChecked(True)
        self._reg(self.chk_volume.setText, "cond_volume")
        self.sp_volume_prev_n = _ispin(10, minimum=1)
        self.sp_volume_mult = _dspin(0.6, decimals=4)
        vol_row = QWidget()
        vol_lay = QHBoxLayout(vol_row)
        vol_lay.setContentsMargins(0, 0, 0, 0)
        vol_lay.addWidget(self.chk_volume)
        vol_lay.addSpacing(16)
        vol_lay.addWidget(self._label("cond_volume_prev_n"))
        vol_lay.addWidget(self.sp_volume_prev_n, alignment=Qt.AlignLeft)
        vol_lay.addSpacing(16)
        vol_lay.addWidget(self._label("cond_volume_mult"))
        vol_lay.addWidget(self.sp_volume_mult, alignment=Qt.AlignLeft)
        vol_lay.addStretch(1)
        grid.addWidget(vol_row, r, 0, 1, 4)
        r += 1

        self.chk_single = QCheckBox()
        self.chk_single.setChecked(True)
        self._reg(self.chk_single.setText, "cond_single_change")
        self.sp_single_pct = _dspin(0.004, decimals=4, minimum=0.0001)
        self.sp_single_pct.setSingleStep(0.0001)
        self.sp_single_max_pct = _dspin(100.0, decimals=4)
        single_row = QWidget()
        single_lay = QHBoxLayout(single_row)
        single_lay.setContentsMargins(0, 0, 0, 0)
        single_lay.addWidget(self.chk_single)
        single_lay.addSpacing(16)
        single_lay.addWidget(self._label("cond_change_min"))
        single_lay.addWidget(self.sp_single_pct, alignment=Qt.AlignLeft)
        single_lay.addSpacing(16)
        single_lay.addWidget(self._label("cond_change_max"))
        single_lay.addWidget(self.sp_single_max_pct, alignment=Qt.AlignLeft)
        single_lay.addStretch(1)
        grid.addWidget(single_row, r, 0, 1, 4)
        r += 1

        self.chk_consec = QCheckBox()
        self.chk_consec.setChecked(True)
        self._reg(self.chk_consec.setText, "cond_consecutive")
        self.sp_consec_count = _ispin(2, minimum=0)
        consec_row = QWidget()
        consec_lay = QHBoxLayout(consec_row)
        consec_lay.setContentsMargins(0, 0, 0, 0)
        consec_lay.addWidget(self.chk_consec)
        consec_lay.addSpacing(16)
        consec_lay.addWidget(self.sp_consec_count, alignment=Qt.AlignLeft)
        consec_lay.addStretch(1)
        grid.addWidget(consec_row, r, 0, 1, 4)
        r += 1

        self.chk_cum = QCheckBox()
        self.chk_cum.setChecked(True)
        self._reg(self.chk_cum.setText, "cond_cum_klines")
        self.sp_cum_klines = _ispin(3, minimum=1)
        self.sp_cum_pct = _dspin(0.06, decimals=4, minimum=0.0001)
        self.sp_cum_pct.setSingleStep(0.0001)
        cum_row = QWidget()
        cum_lay = QHBoxLayout(cum_row)
        cum_lay.setContentsMargins(0, 0, 0, 0)
        cum_lay.addWidget(self.chk_cum)
        cum_lay.addSpacing(16)
        cum_lay.addWidget(self.sp_cum_klines, alignment=Qt.AlignLeft)
        cum_lay.addSpacing(16)
        cum_lay.addWidget(self._label("cond_cum_pct"))
        cum_lay.addWidget(self.sp_cum_pct, alignment=Qt.AlignLeft)
        cum_lay.addStretch(1)
        grid.addWidget(cum_row, r, 0, 1, 4)
        r += 1

        self.chk_atr = QCheckBox()
        self.chk_atr.setChecked(True)
        self._reg(self.chk_atr.setText, "cond_atr")
        self.sp_atr_period = _ispin(14, minimum=1)
        self.sp_atr_min = _dspin(0.0, decimals=4)
        self.sp_atr_max = _dspin(100.0, decimals=4)
        atr_row = QWidget()
        atr_lay = QHBoxLayout(atr_row)
        atr_lay.setContentsMargins(0, 0, 0, 0)
        atr_lay.addWidget(self.chk_atr)
        atr_lay.addSpacing(16)
        atr_lay.addWidget(self._label("cond_atr_period"))
        atr_lay.addWidget(self.sp_atr_period, alignment=Qt.AlignLeft)
        atr_lay.addSpacing(16)
        atr_lay.addWidget(self.sp_atr_min, alignment=Qt.AlignLeft)
        atr_lay.addWidget(QLabel("~", alignment=Qt.AlignCenter))
        atr_lay.addWidget(self.sp_atr_max, alignment=Qt.AlignLeft)
        atr_lay.addStretch(1)
        grid.addWidget(atr_row, r, 0, 1, 4)
        r += 1

        # 逆势影线/实体：做多检查上影线，做空检查下影线
        self.chk_shadow = QCheckBox()
        self.chk_shadow.setChecked(True)
        self._reg(self.chk_shadow.setText, "cond_shadow_body")
        self.sp_shadow_upper = _dspin(0.5, decimals=4)
        # 保留旧字段仅用于兼容已导出的参数文件。
        self.sp_shadow_lower = _dspin(0.5, decimals=4)
        sh_row = QWidget()
        sh_lay = QHBoxLayout(sh_row)
        sh_lay.setContentsMargins(0, 0, 0, 0)
        sh_lay.addWidget(self.chk_shadow)
        sh_lay.addSpacing(16)
        sh_lay.addWidget(self._label("cond_shadow_ratio"))
        sh_lay.addWidget(self.sp_shadow_upper, alignment=Qt.AlignLeft)
        sh_lay.addStretch(1)
        grid.addWidget(sh_row, r, 0, 1, 4)
        r += 1

        # ---- 右：订单参数 ----
        order_box = QGroupBox()
        self._reg(order_box.setTitle, "sec_order_params")
        order_box.setFlat(True)
        ogrid = QGridLayout(order_box)

        self.sp_total_capital = _dspin(100.0)
        self.sp_split_count = _ispin(1, maximum=100000, minimum=1)
        self.sp_leverage = _dspin(100.0, maximum=1000.0, decimals=4)
        self.sp_fee = _dspin(0.03, decimals=4)
        self.sp_stop_loss = _dspin(1.0, maximum=100.0, decimals=4)
        self.sp_cooldown = _ispin(10)
        self.sp_take_profit = _dspin(1.0, maximum=100.0, decimals=4)
        self.cmb_direction = QComboBox()
        self.sp_add_interval = _dspin(0.0, maximum=100.0)
        self.sp_add_mult = _dspin(1.0, maximum=100.0)
        self.sp_add_count = _ispin(1, maximum=100, minimum=0)
        self.sp_max_hold = _ispin(0)

        row = 0
        ogrid.addWidget(self._label("total_capital"), row, 0,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_total_capital, row, 1)
        ogrid.addWidget(self._label("split_count"), row, 2,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_split_count, row, 3)
        ogrid.addWidget(self._label("leverage"), row, 4,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_leverage, row, 5)
        row += 1
        ogrid.addWidget(self._label("fee_rate"), row, 0,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_fee, row, 1)
        ogrid.addWidget(self._label("stop_loss_type"), row, 2,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_stop_loss, row, 3)
        ogrid.addWidget(self._label("stop_cooldown"), row, 4,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_cooldown, row, 5)
        row += 1
        ogrid.addWidget(self._label("take_profit_type"), row, 0,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_take_profit, row, 1)
        ogrid.addWidget(self._label("direction"), row, 2,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.cmb_direction, row, 3)
        ogrid.addWidget(self._label("max_hold_klines"), row, 4,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_max_hold, row, 5)
        row += 1
        ogrid.addWidget(self._label("add_interval"), row, 0,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_add_interval, row, 1)
        ogrid.addWidget(self._label("add_mult"), row, 2,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_add_mult, row, 3)
        ogrid.addWidget(self._label("add_count"), row, 4,
                        alignment=Qt.AlignRight | Qt.AlignVCenter)
        ogrid.addWidget(self.sp_add_count, row, 5)
        row += 1

        strat_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        order_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sections = QHBoxLayout()
        sections.setContentsMargins(0, 0, 0, 0)
        sections.addWidget(strat_box, stretch=6)
        sections.addWidget(order_box, stretch=4)
        lay.addLayout(toolbar)
        lay.addLayout(sections)
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
        self.table = QTableWidget(0, 11)
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
        self._sync_import_button_sizes()
        self._rebuild_combos()
        self.lbl_file.setText(
            tr("loaded_file", name=os.path.basename(self.data_path), count=len(self.klines))
            if self.klines else tr("no_file"))
        self.edit_search.setPlaceholderText(tr("search_placeholder"))
        self._fill_table()
        self._show_stats()
        self._refresh_log_view()

    def _sync_import_button_sizes(self):
        """文件选择与开始回测按钮始终使用相同且能容纳文案的尺寸。"""
        buttons = (self.btn_file, self.btn_start)
        for button in buttons:
            button.setMinimumSize(0, 0)
            button.setMaximumSize(16777215, 16777215)
        size = self.btn_file.sizeHint().expandedTo(self.btn_start.sizeHint())
        for button in buttons:
            button.setFixedSize(size)

    def _rebuild_combos(self):
        combos = (
            (self.cmb_direction, ("dir_both", "dir_long", "dir_short")),
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
            tr("col_amount"), tr("col_qty"),
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
        self.btn_start.setEnabled(True)
        self.lbl_file.setText(tr("loaded_file", name=os.path.basename(path), count=len(self.klines)))
        get_logger().info("加载K线数据 %s (%d 条)", path, len(self.klines))

    # ---------- 参数收集 ----------

    def _reset_params(self):
        """优先恢复用户保存的默认参数，否则使用程序内置默认值。"""
        if self._load_saved_default_params(show_errors=True):
            return
        self._apply_params(StrategyParams(), OrderParams())

    def _apply_params(self, sp: StrategyParams, op: OrderParams):
        """把完整参数模型应用到界面控件。"""
        self.chk_volume.setChecked(sp.volume_enabled)
        self.sp_volume_prev_n.setValue(sp.volume_prev_n)
        self.sp_volume_mult.setValue(sp.volume_mult)
        self.chk_single.setChecked(sp.single_change_enabled)
        self.sp_single_pct.setValue(sp.single_change_pct)
        self.sp_single_max_pct.setValue(sp.single_change_max_pct)
        self.chk_consec.setChecked(sp.consecutive_enabled)
        self.sp_consec_count.setValue(sp.consecutive_count)
        self.chk_cum.setChecked(sp.cum_change_enabled)
        self.sp_cum_klines.setValue(sp.cum_klines)
        self.sp_cum_pct.setValue(sp.cum_change_pct)
        self.chk_atr.setChecked(sp.atr_enabled)
        self.sp_atr_period.setValue(sp.atr_period)
        self.sp_atr_min.setValue(sp.atr_min_pct)
        self.sp_atr_max.setValue(sp.atr_max_pct)
        self.chk_shadow.setChecked(sp.shadow_body_enabled)
        self.sp_shadow_upper.setValue(sp.shadow_body_upper)
        self.sp_shadow_lower.setValue(sp.shadow_body_lower)
        self.sp_total_capital.setValue(op.total_capital)
        self.sp_split_count.setValue(op.split_count)
        self.sp_leverage.setValue(op.leverage)
        self.sp_fee.setValue(op.fee_rate_pct)
        self.sp_stop_loss.setValue(op.stop_loss)
        self.sp_cooldown.setValue(op.stop_cooldown)
        self.sp_take_profit.setValue(op.take_profit)
        self.cmb_direction.setCurrentIndex(
            ("BOTH", "LONG", "SHORT").index(op.direction))
        self.sp_add_interval.setValue(op.add_interval_pct)
        self.sp_add_mult.setValue(op.add_mult)
        self.sp_add_count.setValue(op.add_count)
        self.sp_max_hold.setValue(op.max_hold_klines)

    @staticmethod
    def _default_params_path() -> str:
        return os.path.join(APP_DIR, "data", "nexus_strategy_defaults.inf")

    def _load_saved_default_params(self, show_errors: bool = False) -> bool:
        path = self._default_params_path()
        if not os.path.isfile(path):
            return False
        try:
            strategy, order = load_params(path)
            self._apply_params(strategy, order)
            return True
        except (OSError, ParamsFileError) as exc:
            get_logger().warning("加载默认参数失败: %s", exc)
            if show_errors:
                QMessageBox.warning(
                    self, tr("app_title"), tr("err_params_file", err=exc))
            return False

    def _save_default_params(self):
        path = self._default_params_path()
        strategy, order = self._collect_params()
        try:
            save_params(path, strategy, order)
        except OSError as exc:
            QMessageBox.warning(
                self, tr("app_title"), tr("err_params_file", err=exc))
            return
        QMessageBox.information(
            self, tr("app_title"), tr("default_params_saved", path=path))

    def _collect_params(self):
        sp = StrategyParams(
            volume_enabled=self.chk_volume.isChecked(),
            volume_prev_n=self.sp_volume_prev_n.value(),
            volume_op=">=",
            volume_mult=self.sp_volume_mult.value(),
            single_change_enabled=self.chk_single.isChecked(),
            single_change_pct=self.sp_single_pct.value(),
            single_change_max_pct=self.sp_single_max_pct.value(),
            consecutive_enabled=self.chk_consec.isChecked(),
            consecutive_count=self.sp_consec_count.value(),
            cum_change_enabled=self.chk_cum.isChecked(),
            cum_klines=self.sp_cum_klines.value(),
            cum_change_pct=self.sp_cum_pct.value(),
            atr_enabled=self.chk_atr.isChecked(),
            atr_period=self.sp_atr_period.value(),
            atr_min_pct=self.sp_atr_min.value(),
            atr_max_pct=self.sp_atr_max.value(),
            shadow_body_enabled=self.chk_shadow.isChecked(),
            shadow_body_upper=self.sp_shadow_upper.value(),
            shadow_body_lower=self.sp_shadow_lower.value(),
        )
        op = OrderParams(
            total_capital=self.sp_total_capital.value(),
            split_count=self.sp_split_count.value(),
            leverage=self.sp_leverage.value(),
            fee_rate_pct=self.sp_fee.value(),
            stop_loss=self.sp_stop_loss.value(),
            stop_cooldown=self.sp_cooldown.value(),
            take_profit=self.sp_take_profit.value(),
            order_type="MARKET",
            direction=("BOTH", "LONG", "SHORT")[self.cmb_direction.currentIndex()],
            reverse_trading=False,
            add_interval_pct=self.sp_add_interval.value(),
            add_mult=self.sp_add_mult.value(),
            add_count=self.sp_add_count.value(),
            max_hold_klines=self.sp_max_hold.value(),
        )
        return sp, op

    def _export_params(self):
        params_dir = os.path.join(APP_DIR, "data")
        os.makedirs(params_dir, exist_ok=True)
        default_path = os.path.join(params_dir, "nexus_strategy_params.inf")
        path, _ = QFileDialog.getSaveFileName(
            self, tr("export_params"), default_path, "Nexus Params (*.inf)")
        if not path:
            return
        if not path.lower().endswith(".inf"):
            path += ".inf"
        sp, op = self._collect_params()
        try:
            save_params(path, sp, op)
        except OSError as exc:
            QMessageBox.warning(self, tr("app_title"), tr("err_params_file", err=exc))
            return
        QMessageBox.information(self, tr("app_title"), tr("params_exported", path=path))

    def _import_params(self):
        params_dir = os.path.join(APP_DIR, "data")
        os.makedirs(params_dir, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, tr("import_params"), params_dir, "Nexus Params (*.inf)")
        if not path:
            return
        try:
            sp, op = load_params(path)
        except (OSError, ParamsFileError) as exc:
            QMessageBox.warning(self, tr("app_title"), tr("err_params_file", err=exc))
            return
        self._apply_params(sp, op)
        QMessageBox.information(self, tr("app_title"), tr("params_imported", path=path))

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
        if self._worker is not None and self._worker.log_path:
            get_logger().info("本次回测日志: %s", self._worker.log_path)

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

    _TYPE_KEYS = {"TP": "type_tp", "SL": "type_sl", "TIMEOUT": "type_timeout",
                  "END": "type_end"}

    def _fill_table(self):
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.trades))
        for row, t in enumerate(self.trades):
            vals = (
                f"#{t.no}", f"[{tr(self._TYPE_KEYS.get(t.exit_type, 'type_tp'))}]", t.side,
                f"#{t.entry_kline}", f"{t.entry_price:.2f}",
                f"{t.amount:.2f}", f"{t.qty:.8f}",
                f"#{t.exit_kline}", f"{t.exit_price:.2f}",
                f"{t.pnl:+.2f}", f"{t.fee:.2f}",
            )
            # 编号列单独放，类型列带颜色
            items = [QTableWidgetItem(v) for v in vals]
            if t.exit_type == "SL":
                items[1].setForeground(QColor("#d32f2f"))
            else:
                items[1].setForeground(QColor("#388e3c"))
            items[9].setForeground(QColor("#d32f2f" if t.pnl < 0 else "#388e3c"))
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
                        tr("col_amount"), tr("col_qty"),
                        tr("col_exit_kline"), tr("col_exit_price"),
                        tr("col_pnl"), tr("col_fee")])
            for t in self.trades:
                w.writerow([t.no, tr(self._TYPE_KEYS.get(t.exit_type, "type_tp")), t.side,
                            t.entry_kline, f"{t.entry_price:.2f}",
                            f"{t.amount:.2f}", f"{t.qty:.8f}",
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
