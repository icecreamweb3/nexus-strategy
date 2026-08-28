"""策略回测引擎 / Backtest engine.

逐根K线推进：信号在当前K线收盘后确认，最早在下一根K线成交。
"""
from dataclasses import dataclass
from collections import Counter
from datetime import datetime
import re
from typing import Callable, List, Optional, Tuple

from app.backtest.data_loader import Kline
from app.i18n import tr

LONG = "LONG"
SHORT = "SHORT"


@dataclass
class StrategyParams:
    volume_enabled: bool = True
    volume_prev_n: int = 10            # 前N根K线均量
    volume_op: str = ">="              # 旧参数文件兼容；策略固定使用 >=
    volume_mult: float = 0.6           # 阈值（均量 × 倍数）
    single_change_enabled: bool = True
    single_change_pct: float = 0.04    # 单根绝对涨跌幅下限(%)，即 C
    single_change_max_pct: float = 100.0  # 单根绝对涨跌幅上限(%)，即 D
    consecutive_enabled: bool = True
    consecutive_count: int = 2         # 0/1 忽略，>=2 时检查（含信号K线）
    cum_change_enabled: bool = True
    cum_klines: int = 3                # 追涨追跌过滤回看K线数量（E）
    cum_change_pct: float = 0.06       # 同方向累计涨跌幅上限(%)
    atr_enabled: bool = True
    atr_period: int = 14               # ATR 回看K线数量
    atr_min_pct: float = 0.0           # ATR(N)/收盘价(%) 下限
    atr_max_pct: float = 100.0         # ATR(N)/收盘价(%) 上限
    shadow_body_enabled: bool = True
    shadow_body_upper: float = 0.5     # 逆势影线/实体上限（H）
    shadow_body_lower: float = 0.5     # 旧参数文件兼容，不再单独检查下影线


@dataclass
class OrderParams:
    total_capital: float = 100.0         # 初始总资金（USDT）
    split_count: int = 1                 # 总资金拆分份数
    leverage: float = 1.0                # 杠杆倍数（原 Order Rate）
    fee_rate_pct: float = 0.03
    stop_loss: float = 1.0              # 相对持仓均价的止损百分比；0 表示关闭
    stop_cooldown: int = 10             # K线数
    take_profit: float = 1.0            # 相对持仓均价的止盈百分比；0 表示关闭
    min_take_profit: float = 100.0       # 旧参数文件兼容，不再用于反转平仓
    order_type: str = "MARKET"          # 旧参数文件兼容；回测固定下一根开盘成交
    limit_offset: float = 100.0          # 旧参数文件兼容
    limit_valid_klines: int = 10         # 旧参数文件兼容
    direction: str = "BOTH"             # BOTH / LONG / SHORT
    reverse_trading: bool = False        # 旧参数文件兼容；持仓期间不再计算信号
    add_interval_pct: float = 0.0     # 加仓间隔(%)：相对持仓均价反向波动触发，0 表示不加仓
    add_mult: float = 1.0             # 每次加仓金额 = 当笔基础下单金额 × 倍数
    add_count: int = 1                # 含开仓的总次数：1 表示不加仓，2 表示加一仓
    max_hold_klines: int = 0          # 最长持仓K线数，到期按收盘价平仓；0 表示不限制


@dataclass
class Trade:
    no: int
    exit_type: str          # TP / SL / TIMEOUT / END
    side: str               # LONG / SHORT
    entry_kline: int
    entry_price: float
    amount: float           # 开仓名义金额（含加仓）
    qty: float              # 最终持仓数量（含加仓）
    exit_kline: int
    exit_price: float
    pnl: float              # 净盈亏（扣手续费）
    fee: float


@dataclass
class _Position:
    side: str
    entry_kline: int
    entry_price: float    # 平均开仓价（含加仓）
    qty: float            # 持仓总数量
    cost: float           # 入场侧总名义本金（含加仓）
    adds: int             # 已加仓次数


def _timestamp_seconds(value: str) -> Optional[float]:
    """将常见日期字符串或秒/毫秒时间戳转换为秒。"""
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
        if abs(number) >= 1e14:
            return number / 1_000_000
        if abs(number) >= 1e11:
            return number / 1_000
        return number
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


class BacktestEngine:
    def __init__(self, klines: List[Kline], strategy: StrategyParams,
                 order: OrderParams, log: Optional[Callable[[str, bool], None]] = None,
                 translate: Optional[Callable[..., str]] = None):
        self.klines = klines
        self.sp = strategy
        self.op = order
        # log(message, is_trigger) — is_trigger=True 表示触发交易的日志
        self._log = log or (lambda msg, is_trigger=False: None)
        self._tr = translate or tr
        self.trades: List[Trade] = []
        self.current_capital = order.total_capital
        self.cancelled = False
        self._timestamps = [_timestamp_seconds(k.open_time) for k in klines]
        positive_deltas = [
            round(self._timestamps[i] - self._timestamps[i - 1], 6)
            for i in range(1, len(self._timestamps))
            if self._timestamps[i] is not None and self._timestamps[i - 1] is not None
            and self._timestamps[i] > self._timestamps[i - 1]
        ]
        self._expected_interval = Counter(positive_deltas).most_common(1)[0][0] \
            if positive_deltas else None
        self._continuous_bars = self._build_continuous_counts()

    def _build_continuous_counts(self) -> List[int]:
        """记录每根K线向前连续的根数（包含当前K线）。"""
        if not self.klines:
            return []
        counts = [1]
        for i in range(1, len(self.klines)):
            current = self._timestamps[i]
            previous = self._timestamps[i - 1]
            continuous = False
            if current is not None and previous is not None \
                    and self._expected_interval is not None:
                delta = current - previous
                tolerance = max(1e-6, self._expected_interval * 1e-6)
                continuous = abs(delta - self._expected_interval) <= tolerance
            counts.append(counts[-1] + 1 if continuous else 1)
        return counts

    def _has_continuous_history(self, i: int, bars: int) -> bool:
        return 0 <= i < len(self._continuous_bars) \
            and self._continuous_bars[i] >= bars

    # ---------------- 信号 ----------------

    def _volume_ok(self, i: int) -> bool:
        """当前成交量 >= 不含当前K线的前 A 根均量 × B。"""
        metrics = self._volume_metrics(i)
        return metrics is not None and self.klines[i].volume >= metrics[1]

    def _volume_metrics(self, i: int) -> Optional[Tuple[float, float]]:
        """返回前 A 根均量与成交量条件阈值。"""
        n = self.sp.volume_prev_n
        if n <= 0 or i < n:
            return None
        prev = [k.volume for k in self.klines[i - n:i]]
        avg = sum(prev) / len(prev)
        return avg, avg * self.sp.volume_mult

    def _single_change_pct(self, i: int) -> Optional[float]:
        """计算当前收盘相对上一收盘的有符号涨跌幅。"""
        if i < 1:
            return None
        prev_close = self.klines[i - 1].close
        if prev_close <= 0:
            return None
        return (self.klines[i].close - prev_close) / prev_close * 100

    def _single_change_dir(self, i: int) -> Optional[str]:
        """由当前/上一收盘涨跌确定方向，并应用 C < |涨跌幅| < D。"""
        chg = self._single_change_pct(i)
        if chg is None:
            return None
        if chg == 0:
            return None
        if self.sp.single_change_enabled:
            magnitude = abs(chg)
            if not (self.sp.single_change_pct < magnitude
                    < self.sp.single_change_max_pct):
                return None
        return LONG if chg > 0 else SHORT

    def _consecutive_ok(self, i: int, direction: str) -> bool:
        """最近 N 根与信号同向；十字线可同时视为涨向或跌向。"""
        n = self.sp.consecutive_count
        if n <= 1:
            return True
        if i < n - 1:
            return False
        seg = self.klines[i - n + 1:i + 1]
        if direction == LONG:
            return all(k.close >= k.open for k in seg)
        return all(k.close <= k.open for k in seg)

    def _cum_change_ok(self, i: int, direction: str) -> bool:
        """过滤同方向追涨追跌：方向化的 E 根累计幅度必须小于 F。"""
        value = self._directional_cum_change_pct(i, direction)
        return value is not None and value < self.sp.cum_change_pct

    def _directional_cum_change_pct(self, i: int, direction: str) -> Optional[float]:
        """返回相对交易方向的累计涨跌幅。"""
        lookback = self.sp.cum_klines
        if lookback <= 0:
            return 0.0
        # 例：第10根、E=6，对比第4根收盘；第6根则对比首根开盘。
        if i + 1 < lookback:
            return None
        if i + 1 == lookback:
            base = self.klines[0].open
        else:
            base = self.klines[i - lookback].close
        if base <= 0:
            return None
        cum = (self.klines[i].close - base) / base * 100
        return cum if direction == LONG else -cum

    def _atr_ok(self, i: int) -> bool:
        """用信号K线之前的 N 根TR计算 ATR/前一根收盘价。"""
        atr_pct = self._atr_pct(i)
        return atr_pct is not None \
            and self.sp.atr_min_pct <= atr_pct <= self.sp.atr_max_pct

    def _atr_pct(self, i: int) -> Optional[float]:
        """返回信号 K 线之前 N 根的 ATR 百分比。"""
        period = self.sp.atr_period
        if period <= 0 or i < period:
            return None
        trs = []
        for j in range(i - period, i):
            k = self.klines[j]
            if j == 0:
                trs.append(k.high - k.low)
                continue
            prev_close = self.klines[j - 1].close
            trs.append(max(k.high - k.low,
                           abs(k.high - prev_close),
                           abs(k.low - prev_close)))
        close = self.klines[i - 1].close
        if close <= 0:
            return None
        return sum(trs) / period / close * 100

    def _shadow_body_ok(self, i: int, direction: str) -> bool:
        """只检查逆势影线：做多看上影线，做空看下影线；实体为0失败。"""
        ratio = self._adverse_shadow_body_ratio(i, direction)
        return ratio is not None and ratio < self.sp.shadow_body_upper

    def _adverse_shadow_body_ratio(self, i: int, direction: str) -> Optional[float]:
        """返回对应交易方向的逆势影线/实体比。"""
        k = self.klines[i]
        body = abs(k.close - k.open)
        if body == 0:
            return None
        upper = k.high - max(k.open, k.close)
        lower = min(k.open, k.close) - k.low
        adverse_shadow = upper if direction == LONG else lower
        return adverse_shadow / body

    def _combined_signal(self, i: int) -> Optional[str]:
        """严格按连续性→量能→涨跌→连续K→方向→其余过滤的顺序计算。"""
        sp = self.sp

        # 2. 当前K线必须与上一根K线连续。
        if not self._has_continuous_history(i, 2):
            return None

        # 3-4. 先确认有连续的 A 根成交量历史，再计算成交量倍数。
        if sp.volume_enabled:
            if sp.volume_prev_n <= 0 \
                    or not self._has_continuous_history(i, sp.volume_prev_n + 1):
                return None
            if not self._volume_ok(i):
                return None

        # 5. 计算收盘涨跌幅并应用 C、D 范围。
        change_pct = self._single_change_pct(i)
        if change_pct is None or change_pct == 0:
            return None
        if sp.single_change_enabled and not (
                sp.single_change_pct < abs(change_pct) < sp.single_change_max_pct):
            return None

        # 6. 在确定交易方向前，分别计算多、空连续K线条件。
        if sp.consecutive_enabled and sp.consecutive_count > 1 \
                and not self._has_continuous_history(i, sp.consecutive_count):
            return None
        long_consecutive = not sp.consecutive_enabled \
            or self._consecutive_ok(i, LONG)
        short_consecutive = not sp.consecutive_enabled \
            or self._consecutive_ok(i, SHORT)

        # 7. 由第5步的有符号涨跌幅确定方向，再选择对应连续K线结果。
        direction = LONG if change_pct > 0 else SHORT
        if direction == LONG and not long_consecutive:
            return None
        if direction == SHORT and not short_consecutive:
            return None

        # 8. 计算 E 根累计涨跌，且不允许历史窗口跨越数据缺口。
        if sp.cum_change_enabled:
            lookback = sp.cum_klines
            required = lookback if i + 1 == lookback else lookback + 1
            if lookback > 0 and not self._has_continuous_history(i, required):
                return None
            if not self._cum_change_ok(i, direction):
                return None

        # 9. ATR使用信号前 N 根，连同信号K线共需连续 N+1 根数据。
        if sp.atr_enabled:
            if not self._has_continuous_history(i, sp.atr_period + 1) \
                    or not self._atr_ok(i):
                return None

        # 10-12. 实体→对应方向逆势影线→影线/实体比例。
        if sp.shadow_body_enabled:
            k = self.klines[i]
            body = abs(k.close - k.open)
            if body == 0:
                return None
            upper = k.high - max(k.open, k.close)
            lower = min(k.open, k.close) - k.low
            adverse_shadow = upper if direction == LONG else lower
            if adverse_shadow / body >= sp.shadow_body_upper:
                return None

        # 13. 所有启用条件同时通过后才返回并记录方向信号。
        return direction

    @staticmethod
    def _fmt_metric(value: Optional[float], suffix: str = "") -> str:
        if value is None:
            return "N/A"
        return f"{value:.6g}{suffix}"

    def _check_detail(self, name_key: str, enabled: bool, passed: bool,
                      expression: str) -> str:
        name = self._tr(name_key)
        if not enabled:
            return self._tr("log_check_disabled", name=name)
        return self._tr(
            "log_check_detail", name=name, mark="✓" if passed else "✗",
            expression=expression,
        )

    def _history_short(self, actual: int, required: int) -> str:
        return self._tr("check_history_short", actual=actual, required=required)

    def _strategy_details(self, i: int) -> str:
        """生成当前 K 线各项检查的计算值与条件表达式。"""
        sp = self.sp
        continuous = self._continuous_bars[i] if 0 <= i < len(self._continuous_bars) else 0
        details = [self._check_detail(
            "check_continuity", True, continuous >= 2,
            f"{continuous}/2",
        )]

        # 按 UI 第一行：成交量与前 N 根平均量倍数。
        volume_metrics = self._volume_metrics(i)
        _, volume_threshold = volume_metrics or (None, None)
        volume_history = sp.volume_prev_n > 0 \
            and self._has_continuous_history(i, sp.volume_prev_n + 1)
        volume_ok = volume_history and volume_threshold is not None \
            and self.klines[i].volume >= volume_threshold
        volume_expr = (
            f"{self.klines[i].volume:g} >= {self._fmt_metric(volume_threshold)}"
        )
        if not volume_history or volume_threshold is None:
            volume_expr = self._history_short(continuous, sp.volume_prev_n + 1)
        details.append(self._check_detail(
            "check_volume", sp.volume_enabled, volume_ok,
            volume_expr,
        ))

        # 按 UI 第二行起：单根涨跌、连续同向、累计幅度、ATR、影线比例。
        change = self._single_change_pct(i)
        direction = None if change is None or change == 0 \
            else (LONG if change > 0 else SHORT)
        single_ok = change is not None and change != 0 \
            and sp.single_change_pct < abs(change) < sp.single_change_max_pct
        details.append(self._check_detail(
            "check_single_change", sp.single_change_enabled, single_ok,
            f"|{self._fmt_metric(change, '%')}| ∈ "
            f"({sp.single_change_pct:g}%, {sp.single_change_max_pct:g}%)",
        ))
        details.append(self._check_detail(
            "check_signal_direction", True, direction is not None,
            direction or "N/A",
        ))

        n = sp.consecutive_count
        consecutive_history = n <= 1 or self._has_continuous_history(i, n)
        if direction is not None and n > 1 and i >= n - 1:
            segment = self.klines[i - n + 1:i + 1]
            matched = sum(
                k.close >= k.open if direction == LONG else k.close <= k.open
                for k in segment
            )
        elif n <= 1:
            matched = max(n, 0)
        else:
            matched = 0
        consecutive_ok = direction is not None and consecutive_history \
            and self._consecutive_ok(i, direction)
        consecutive_expr = f"{matched}/{max(n, 0)} ({direction or 'N/A'})"
        if not consecutive_history:
            consecutive_expr = self._history_short(continuous, max(n, 1))
        details.append(self._check_detail(
            "check_consecutive", sp.consecutive_enabled, consecutive_ok,
            consecutive_expr,
        ))

        lookback = sp.cum_klines
        required = lookback if i + 1 == lookback else lookback + 1
        cumulative = self._directional_cum_change_pct(i, direction) \
            if direction is not None else None
        cumulative_ok = direction is not None \
            and (lookback <= 0 or self._has_continuous_history(i, required)) \
            and cumulative is not None and cumulative < sp.cum_change_pct
        cumulative_expr = (
            f"{self._fmt_metric(cumulative, '%')} < {sp.cum_change_pct:g}%"
        )
        if lookback > 0 and not self._has_continuous_history(i, required):
            cumulative_expr = self._history_short(continuous, required)
        details.append(self._check_detail(
            "check_cumulative", sp.cum_change_enabled, cumulative_ok,
            cumulative_expr,
        ))

        atr = self._atr_pct(i)
        atr_history = self._has_continuous_history(i, sp.atr_period + 1)
        atr_ok = atr_history and atr is not None \
            and sp.atr_min_pct <= atr <= sp.atr_max_pct
        atr_expr = (
            f"{self._fmt_metric(atr, '%')} ∈ "
            f"[{sp.atr_min_pct:g}%, {sp.atr_max_pct:g}%]"
        )
        if not atr_history or atr is None:
            atr_expr = f"N/A ({self._history_short(continuous, sp.atr_period + 1)})"
        details.append(self._check_detail(
            "check_atr", sp.atr_enabled, atr_ok,
            atr_expr,
        ))

        shadow_ratio = self._adverse_shadow_body_ratio(i, direction) \
            if direction is not None else None
        shadow_ok = shadow_ratio is not None and shadow_ratio < sp.shadow_body_upper
        details.append(self._check_detail(
            "check_shadow", sp.shadow_body_enabled, shadow_ok,
            f"{self._fmt_metric(shadow_ratio)} < {sp.shadow_body_upper:g}",
        ))

        return " ; ".join(details)

    def _log_kline(self, i: int):
        k = self.klines[i]
        try:
            raw_time = re.sub(
                r"(T\d{2}:\d{2}:\d{2})\.\d+", r"\1",
                str(k.open_time).strip())
            timestamp = datetime.fromisoformat(
                raw_time.replace("Z", "+00:00"))
            time_text = timestamp.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            time_text = str(k.open_time)
        self._log(self._tr(
            "log_kline", index=k.index, time=time_text, close=f"{k.close:.2f}",
            volume=f"{k.volume:g}", details=self._strategy_details(i),
        ))

    # ---------------- 成交与平仓 ----------------

    def _base_order_amount(self) -> float:
        """按最新总资金、拆分份数和杠杆计算本次名义下单金额。"""
        if self.op.split_count <= 0 or self.current_capital <= 0:
            return 0.0
        return self.current_capital / self.op.split_count * self.op.leverage

    def _new_position(self, side: str, entry_kline: int, price: float) -> _Position:
        initial_amount = self._base_order_amount()
        qty = initial_amount / price
        return _Position(side, entry_kline, price, qty, initial_amount, 0)

    def _try_add_position(self, position: _Position, k: Kline) -> bool:
        """按金额倍数加一仓；间隔/倍数为0或总次数不超过1时禁用。"""
        op = self.op
        if op.add_interval_pct <= 0 or op.add_mult <= 0 or op.add_count <= 1:
            return False
        if position.adds >= op.add_count - 1:
            return False
        trigger = position.entry_price * (1 - op.add_interval_pct / 100) \
            if position.side == LONG \
            else position.entry_price * (1 + op.add_interval_pct / 100)
        hit = k.low <= trigger if position.side == LONG else k.high >= trigger
        if not hit or trigger <= 0:
            return False
        add_amount = self._base_order_amount() * op.add_mult
        if add_amount <= 0:
            return False
        add_qty = add_amount / trigger
        position.qty += add_qty
        position.cost += add_amount
        position.entry_price = position.cost / position.qty
        position.adds += 1
        self._log(self._tr(
            "log_add", add_no=position.adds, side=position.side, kline=k.index,
            price=f"{trigger:.2f}", amount=f"{add_amount:.2f}",
            average=f"{position.entry_price:.2f}",
        ), True)
        return True

    def _close_trade(self, pos: _Position, exit_kline: int, exit_price: float, exit_type: str):
        sign = 1 if pos.side == LONG else -1
        gross = pos.qty * (exit_price - pos.entry_price) * sign
        rate = self.op.fee_rate_pct / 100
        fee = pos.cost * rate + pos.qty * exit_price * rate
        trade = Trade(
            no=len(self.trades) + 1,
            exit_type=exit_type,
            side=pos.side,
            entry_kline=pos.entry_kline,
            entry_price=pos.entry_price,
            amount=pos.cost,
            qty=pos.qty,
            exit_kline=exit_kline,
            exit_price=exit_price,
            pnl=gross - fee,
            fee=fee,
        )
        self.trades.append(trade)
        # 平仓后将净盈亏计入总资金，下一次下单随实际剩余资金动态调整。
        self.current_capital += trade.pnl
        exit_key = {"TP": "type_tp", "SL": "type_sl", "TIMEOUT": "type_timeout",
                    "END": "type_end"}.get(exit_type, exit_type)
        self._log(self._tr(
            "log_close", exit_type=self._tr(exit_key), side=trade.side, no=trade.no,
            entry_kline=trade.entry_kline, entry_price=f"{trade.entry_price:.2f}",
            exit_kline=trade.exit_kline, exit_price=f"{trade.exit_price:.2f}",
            pnl=f"{trade.pnl:+.2f}", fee=f"{trade.fee:.2f}",
            capital=f"{self.current_capital:.2f}",
        ), True)

    # ---------------- 主循环 ----------------

    def run(self) -> List[Trade]:
        ks = self.klines
        op = self.op
        position: Optional[_Position] = None
        entry_signal: Optional[Tuple[str, int]] = None
        cooldown_until = -1

        for i, k in enumerate(ks):
            if self.cancelled:
                break

            # 持仓或等待开仓时不运行信号策略，日志中的策略状态记为未通过。
            can_scan = position is None and entry_signal is None \
                and k.index > cooldown_until
            bar_signal = self._combined_signal(i) if can_scan else None
            self._log_kline(i)

            # 14. 信号只在下一根连续K线开盘价成交；遇到数据缺口则取消。
            if entry_signal is not None and position is None:
                side, signal_kline = entry_signal
                if k.index == signal_kline + 1 and self._has_continuous_history(i, 2):
                    position = self._new_position(side, k.index, k.open)
                    self._log(self._tr(
                        "log_entry", side=side, kline=k.index, price=f"{k.open:.2f}",
                        signal_kline=signal_kline, amount=f"{position.cost:.2f}",
                    ), True)
                else:
                    self._log(self._tr("log_gap_cancel", signal_kline=signal_kline))
                entry_signal = None

            # 15-16. 持仓检查优先级：加仓 > 止损 > 止盈 > 最长持仓。
            if position is not None:
                self._try_add_position(position, k)

                sl_price = position.entry_price * (1 - op.stop_loss / 100) \
                    if position.side == LONG \
                    else position.entry_price * (1 + op.stop_loss / 100)
                tp_price = position.entry_price * (1 + op.take_profit / 100) \
                    if position.side == LONG \
                    else position.entry_price * (1 - op.take_profit / 100)
                stopped = op.stop_loss > 0 and (
                    k.low <= sl_price if position.side == LONG else k.high >= sl_price)
                taken = op.take_profit > 0 and (
                    k.high >= tp_price if position.side == LONG else k.low <= tp_price)
                if stopped:
                    self._close_trade(position, k.index, sl_price, "SL")
                    position = None
                    cooldown_until = k.index + op.stop_cooldown
                elif taken:
                    self._close_trade(position, k.index, tp_price, "TP")
                    position = None
                # 未平仓时检查最长持仓时间：到期按当根K线收盘价平仓
                if position is not None and op.max_hold_klines > 0 \
                        and k.index - position.entry_kline + 1 >= op.max_hold_klines:
                    self._close_trade(position, k.index, k.close, "TIMEOUT")
                    position = None
                if position is not None:
                    continue
                # 平仓后同根K线不再开仓
                continue

            # 1、17. 仅空仓时寻找信号；平仓当根已在上方 continue。
            if k.index <= cooldown_until:
                continue
            sig = bar_signal
            if sig is None:
                continue
            if op.direction != "BOTH" and sig != op.direction:
                continue
            entry_signal = (sig, k.index)
            self._log(self._tr("log_signal", side=sig, kline=k.index))

        # 数据结束仍有持仓：按最后收盘价平仓
        if position is not None and ks:
            self._close_trade(position, ks[-1].index, ks[-1].close, "END")
        if entry_signal is not None:
            self._log(self._tr("log_no_entry_bar", signal_kline=entry_signal[1]))
        return self.trades
