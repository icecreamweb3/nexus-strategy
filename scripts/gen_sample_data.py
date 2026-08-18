#!/usr/bin/env python3
"""生成示例 1m K线 CSV（随机游走 + 趋势段），用于回测自测。"""
import csv
import math
import os
import random
from datetime import datetime, timedelta

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "sample_1m.csv")


def main(count: int = 20000):
    random.seed(42)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    price = 30000.0
    ts = datetime(2025, 1, 1)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close", "volume"])
        for i in range(count):
            drift = math.sin(i / 300.0) * 8 + random.uniform(-25, 25)
            open_ = price
            close = price + drift
            high = max(open_, close) + random.uniform(0, 20)
            low = min(open_, close) - random.uniform(0, 20)
            vol = random.uniform(5, 50) * (1 + abs(drift) / 30)
            w.writerow([ts.strftime("%Y-%m-%d %H:%M:%S"),
                        f"{open_:.2f}", f"{high:.2f}", f"{low:.2f}",
                        f"{close:.2f}", f"{vol:.4f}"])
            price = close
            ts += timedelta(minutes=1)
    print(f"written {count} klines -> {OUT}")


if __name__ == "__main__":
    main()
