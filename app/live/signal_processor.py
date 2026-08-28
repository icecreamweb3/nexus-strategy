"""把实时收盘 K 线交给原回测条件检测机制。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from app.backtest.data_loader import Kline
from app.backtest.engine import BacktestEngine, OrderParams, StrategyParams


@dataclass(frozen=True)
class LiveSignal:
    direction: str
    kline: Kline


class LiveSignalProcessor:
    def __init__(self, klines: list[Kline], strategy: StrategyParams,
                 order: OrderParams, log: Callable[[str, bool], None],
                 translate: Callable[..., str]):
        self.klines = list(klines)
        self.strategy = strategy
        self.order = order
        self.log = log
        self.translate = translate
        self._last_open_time = self._time_key(self.klines[-1]) if self.klines else None
        self._last_evaluated_time = None

    @staticmethod
    def required_history_bars(strategy: StrategyParams) -> int:
        """返回对最新已收盘 K 线执行全部启用条件所需的最小历史根数。"""
        required = [2]
        if strategy.volume_enabled:
            required.append(strategy.volume_prev_n + 1)
        if strategy.consecutive_enabled and strategy.consecutive_count > 1:
            required.append(strategy.consecutive_count)
        if strategy.cum_change_enabled and strategy.cum_klines > 0:
            required.append(strategy.cum_klines + 1)
        if strategy.atr_enabled:
            required.append(strategy.atr_period + 1)
        return max(required)

    @staticmethod
    def _time_key(kline: Kline) -> int:
        value = str(kline.open_time)
        try:
            return int(value)
        except ValueError:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)

    def add_closed_kline(self, kline: Kline) -> Optional[LiveSignal]:
        key = self._time_key(kline)
        if self._last_open_time is not None and key <= self._last_open_time:
            return None
        kline.index = self.klines[-1].index + 1 if self.klines else 1
        self.klines.append(kline)
        self._last_open_time = key

        return self._evaluate(len(self.klines) - 1)

    def evaluate_latest_closed(self) -> Optional[LiveSignal]:
        """启动预热完成后立即检测最新一根已收盘 K 线。"""
        if not self.klines:
            return None
        return self._evaluate(len(self.klines) - 1)

    def _evaluate(self, index: int) -> Optional[LiveSignal]:
        kline = self.klines[index]
        key = self._time_key(kline)
        if key == self._last_evaluated_time:
            return None
        self._last_evaluated_time = key

        engine = BacktestEngine(
            self.klines, self.strategy, self.order, log=self.log,
            translate=self.translate)
        engine._log_kline(index)
        direction = engine._combined_signal(index)
        if direction is None:
            return None
        if self.order.direction != "BOTH" and direction != self.order.direction:
            return None
        self.log(self.translate(
            "log_signal", side=direction, kline=kline.index), True)
        return LiveSignal(direction, kline)
