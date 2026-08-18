"""策略回测引擎 / Backtest engine.

逐根K线推进：
1. 平仓检查（止盈/止损价差触价、反转信号平仓）
2. 限价单成交检查（有效K线数内触价成交，否则撤单）
3. 信号检测（启用的策略需全部同向）→ 开单
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from app.backtest.data_loader import Kline

LONG = "LONG"
SHORT = "SHORT"


@dataclass
class StrategyParams:
    trend_enabled: bool = True
    trend_kline_count: int = 2
    trend_cum_pct: float = 0.06
    trend_last_n: int = 1
    trend_single_pct: float = 0.04

    pattern_enabled: bool = True
    long_bear_count: int = 2
    long_bear_body_upper: float = 0.8
    long_bear_body_lower: float = 0.7
    rev_bull_body_upper: float = 0.6
    rev_bull_body_lower: float = 0.5
    short_bull_count: int = 2
    short_bull_body_upper: float = 0.7
    short_bull_body_lower: float = 0.8
    rev_bear_body_upper: float = 0.5
    rev_bear_body_lower: float = 0.6

    reverse_enabled: bool = True
    body_ratio_min: float = 1.0
    body_ratio_max: float = 1000000.0

    volume_enabled: bool = True
    volume_ratio: float = 0.6


@dataclass
class OrderParams:
    position_size: float = 10000.0      # USDT
    fee_rate_pct: float = 0.03
    stop_loss: float = 500.0            # 价差
    stop_cooldown: int = 10             # K线数
    take_profit: float = 500.0          # 价差
    min_take_profit: float = 100.0
    order_type: str = "LIMIT"           # LIMIT / MARKET
    limit_offset: float = 100.0
    limit_valid_klines: int = 10
    direction: str = "BOTH"             # BOTH / LONG / SHORT
    reverse_trading: bool = True
    short_lookback_enabled: bool = True
    short_lookback_n: int = 10
    short_deviation: float = 100.0
    long_lookback_enabled: bool = True
    long_lookback_n: int = 10
    long_deviation: float = 100.0
    reverse_volume_enabled: bool = True
    reverse_volume_n: int = 10
    reverse_volume_mult: float = 1.2
    reverse_body_edge_enabled: bool = True
    body_edge_long_n: int = 10
    body_edge_short_n: int = 10


@dataclass
class Trade:
    no: int
    exit_type: str          # TP / SL / REVERSE
    side: str               # LONG / SHORT
    entry_kline: int
    entry_price: float
    exit_kline: int
    exit_price: float
    pnl: float              # 净盈亏（扣手续费）
    fee: float


@dataclass
class _Position:
    side: str
    entry_kline: int
    entry_price: float


@dataclass
class _PendingOrder:
    side: str
    limit_price: float
    placed_kline: int


def _body(k: Kline) -> float:
    return abs(k.close - k.open)


def _upper_shadow(k: Kline) -> float:
    return k.high - max(k.open, k.close)


def _lower_shadow(k: Kline) -> float:
    return min(k.open, k.close) - k.low


def _ratio_ge(body: float, shadow: float, threshold: float) -> bool:
    """body/shadow >= threshold；影线为 0 时视为无穷大（通过）。"""
    if shadow <= 0:
        return True
    return body / shadow >= threshold


class BacktestEngine:
    def __init__(self, klines: List[Kline], strategy: StrategyParams,
                 order: OrderParams, log: Optional[Callable[[str, bool], None]] = None):
        self.klines = klines
        self.sp = strategy
        self.op = order
        # log(message, is_trigger) — is_trigger=True 表示触发交易的日志
        self._log = log or (lambda msg, is_trigger=False: None)
        self.trades: List[Trade] = []
        self.cancelled = False

    # ---------------- 信号 ----------------

    def _trend_signal(self, i: int) -> Optional[str]:
        sp = self.sp
        n = sp.trend_kline_count
        if i < n - 1:
            return None
        seg = self.klines[i - n + 1:i + 1]
        cum = (seg[-1].close - seg[0].open) / seg[0].open * 100
        last = seg[-sp.trend_last_n:] if sp.trend_last_n <= n else seg
        singles_ok = all(
            abs(k.close - k.open) / k.open * 100 >= sp.trend_single_pct for k in last
        )
        if not singles_ok:
            return None
        if all(k.close > k.open for k in seg) and cum >= sp.trend_cum_pct:
            return LONG
        if all(k.close < k.open for k in seg) and -cum >= sp.trend_cum_pct:
            return SHORT
        return None

    def _pattern_signal(self, i: int) -> Optional[str]:
        sp = self.sp
        k = self.klines[i]
        # 做多：此前连续 long_bear_count 根阴线满足实体/影线比，当前反转为阳线
        m = sp.long_bear_count
        if i >= m:
            bears = self.klines[i - m:i]
            if all(b.close < b.open for b in bears) and all(
                _ratio_ge(_body(b), _upper_shadow(b), sp.long_bear_body_upper)
                and _ratio_ge(_body(b), _lower_shadow(b), sp.long_bear_body_lower)
                for b in bears
            ):
                if k.close > k.open \
                        and _ratio_ge(_body(k), _upper_shadow(k), sp.rev_bull_body_upper) \
                        and _ratio_ge(_body(k), _lower_shadow(k), sp.rev_bull_body_lower):
                    return LONG
        # 做空：此前连续 short_bull_count 根阳线满足比率，当前反转为阴线
        m = sp.short_bull_count
        if i >= m:
            bulls = self.klines[i - m:i]
            if all(b.close > b.open for b in bulls) and all(
                _ratio_ge(_body(b), _upper_shadow(b), sp.short_bull_body_upper)
                and _ratio_ge(_body(b), _lower_shadow(b), sp.short_bull_body_lower)
                for b in bulls
            ):
                if k.close < k.open \
                        and _ratio_ge(_body(k), _upper_shadow(k), sp.rev_bear_body_upper) \
                        and _ratio_ge(_body(k), _lower_shadow(k), sp.rev_bear_body_lower):
                    return SHORT
        return None

    def _reverse_confirm_ok(self, i: int) -> bool:
        # 实体比阈值按实体绝对值（价格差）判断，与参数面板上下限量纲一致
        return self.sp.body_ratio_min <= _body(self.klines[i]) <= self.sp.body_ratio_max

    def _volume_ok(self, i: int) -> bool:
        if i < 10:
            return False
        prev = [k.volume for k in self.klines[i - 10:i]]
        avg = sum(prev) / len(prev)
        if avg <= 0:
            return True
        return self.klines[i].volume / avg > self.sp.volume_ratio

    def _combined_signal(self, i: int) -> Optional[str]:
        sp = self.sp
        signals = []
        if sp.trend_enabled:
            signals.append(self._trend_signal(i))
        if sp.pattern_enabled:
            signals.append(self._pattern_signal(i))
        if sp.reverse_enabled and not self._reverse_confirm_ok(i):
            return None
        if sp.volume_enabled and not self._volume_ok(i):
            return None
        # 各策略相互独立：任一给出方向即可（多个同向才算一致，None 视为弃权）
        directional = [s for s in signals if s is not None]
        if not directional:
            return None
        return directional[0] if all(s == directional[0] for s in directional) else None

    def _entry_checks_ok(self, side: str, i: int) -> bool:
        op = self.op
        k = self.klines[i]
        if op.long_lookback_enabled and side == LONG and i >= op.long_lookback_n:
            lowest = min(x.low for x in self.klines[i - op.long_lookback_n + 1:i + 1])
            if k.close - lowest > op.long_deviation:
                return False
        if op.short_lookback_enabled and side == SHORT and i >= op.short_lookback_n:
            highest = max(x.high for x in self.klines[i - op.short_lookback_n + 1:i + 1])
            if highest - k.close > op.short_deviation:
                return False
        if op.reverse_volume_enabled and i >= op.reverse_volume_n:
            prev_max = max(x.volume for x in self.klines[i - op.reverse_volume_n:i])
            if prev_max > 0 and k.volume <= op.reverse_volume_mult * prev_max:
                return False
        if op.reverse_body_edge_enabled:
            if side == LONG and i >= op.body_edge_long_n:
                edge = max(max(x.open, x.close) for x in self.klines[i - op.body_edge_long_n:i])
                if k.close <= edge:
                    return False
            if side == SHORT and i >= op.body_edge_short_n:
                edge = min(min(x.open, x.close) for x in self.klines[i - op.body_edge_short_n:i])
                if k.close >= edge:
                    return False
        return True

    # ---------------- 成交与平仓 ----------------

    def _close_trade(self, pos: _Position, exit_kline: int, exit_price: float, exit_type: str):
        qty = self.op.position_size / pos.entry_price
        sign = 1 if pos.side == LONG else -1
        gross = qty * (exit_price - pos.entry_price) * sign
        rate = self.op.fee_rate_pct / 100
        fee = qty * pos.entry_price * rate + qty * exit_price * rate
        trade = Trade(
            no=len(self.trades) + 1,
            exit_type=exit_type,
            side=pos.side,
            entry_kline=pos.entry_kline,
            entry_price=pos.entry_price,
            exit_kline=exit_kline,
            exit_price=exit_price,
            pnl=gross - fee,
            fee=fee,
        )
        self.trades.append(trade)
        self._log(
            f"[{exit_type}] {trade.side} #{trade.no} 开仓K线#{trade.entry_kline} "
            f"@ {trade.entry_price:.2f} → 平仓K线#{trade.exit_kline} @ {trade.exit_price:.2f} "
            f"盈亏 {trade.pnl:+.2f} 手续费 {trade.fee:.2f}",
            True,
        )

    # ---------------- 主循环 ----------------

    def run(self) -> List[Trade]:
        ks = self.klines
        op = self.op
        position: Optional[_Position] = None
        pending: Optional[_PendingOrder] = None
        cooldown_until = -1

        for i, k in enumerate(ks):
            if self.cancelled:
                break

            # 1. 持仓平仓检查
            if position is not None:
                sl_price = position.entry_price - op.stop_loss if position.side == LONG \
                    else position.entry_price + op.stop_loss
                tp_price = position.entry_price + op.take_profit if position.side == LONG \
                    else position.entry_price - op.take_profit
                stopped = (k.low <= sl_price) if position.side == LONG else (k.high >= sl_price)
                taken = (k.high >= tp_price) if position.side == LONG else (k.low <= tp_price)
                if stopped:
                    self._close_trade(position, k.index, sl_price, "SL")
                    position = None
                    cooldown_until = k.index + op.stop_cooldown
                elif taken:
                    self._close_trade(position, k.index, tp_price, "TP")
                    position = None
                elif op.reverse_trading:
                    sig = self._combined_signal(i)
                    if sig is not None and sig != position.side:
                        sign = 1 if position.side == LONG else -1
                        unrealized = (k.close - position.entry_price) * sign
                        if unrealized >= op.min_take_profit:
                            self._close_trade(position, k.index, k.close, "REVERSE")
                            position = None
                if position is not None:
                    continue
                # 平仓后同根K线不再开仓
                continue

            # 2. 限价单成交检查
            if pending is not None:
                if k.index > pending.placed_kline + op.limit_valid_klines:
                    self._log(f"限价单失效撤销 {pending.side} @ {pending.limit_price:.2f}")
                    pending = None
                else:
                    filled = (k.low <= pending.limit_price) if pending.side == LONG \
                        else (k.high >= pending.limit_price)
                    if filled:
                        position = _Position(pending.side, k.index, pending.limit_price)
                        self._log(
                            f"限价单成交 {pending.side} K线#{k.index} @ {pending.limit_price:.2f}",
                            True,
                        )
                        pending = None
                        continue
                    continue
                continue

            # 3. 信号开单
            if k.index <= cooldown_until:
                continue
            sig = self._combined_signal(i)
            if sig is None:
                continue
            if op.direction != "BOTH" and sig != op.direction:
                continue
            if not self._entry_checks_ok(sig, i):
                continue
            if op.order_type == "MARKET":
                position = _Position(sig, k.index, k.close)
                self._log(f"市价开仓 {sig} K线#{k.index} @ {k.close:.2f}", True)
            else:
                limit_price = k.close - op.limit_offset if sig == LONG else k.close + op.limit_offset
                pending = _PendingOrder(sig, limit_price, k.index)
                self._log(f"挂限价单 {sig} @ {limit_price:.2f}（信号K线#{k.index} @ {k.close:.2f}）")

        # 数据结束仍有持仓：按最后收盘价平仓
        if position is not None and ks:
            self._close_trade(position, ks[-1].index, ks[-1].close, "TP")
        if pending is not None:
            self._log(f"回测结束，未成交限价单撤销 {pending.side} @ {pending.limit_price:.2f}")
        return self.trades
