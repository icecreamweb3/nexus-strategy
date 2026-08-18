"""回测结果统计 / Backtest statistics."""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.backtest.engine import LONG, SHORT, Trade


@dataclass
class BacktestStats:
    total_trades: int = 0
    total_pnl: float = 0.0          # 总盈亏（净，扣手续费）
    total_fees: float = 0.0
    long_count: int = 0
    short_count: int = 0
    max_drawdown: float = 0.0       # 最大区间亏损值
    drawdown_interval: Optional[Tuple[int, int]] = None  # 最大亏损区间 (#i-#j)


def compute_stats(trades: List[Trade]) -> BacktestStats:
    stats = BacktestStats(
        total_trades=len(trades),
        total_pnl=sum(t.pnl for t in trades),
        total_fees=sum(t.fee for t in trades),
        long_count=sum(1 for t in trades if t.side == LONG),
        short_count=sum(1 for t in trades if t.side == SHORT),
    )

    # 最大区间亏损：逐笔累计净盈亏的最大回撤，记录笔数区间
    cum = 0.0
    peak = 0.0
    peak_idx = 0
    max_dd = 0.0
    interval = None
    for idx, t in enumerate(trades, start=1):
        cum += t.pnl
        if cum > peak:
            peak = cum
            peak_idx = idx
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
            interval = (peak_idx + 1, idx)
    stats.max_drawdown = -max_dd if max_dd > 0 else 0.0
    stats.drawdown_interval = interval
    return stats
