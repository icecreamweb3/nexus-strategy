import unittest

from app.backtest.data_loader import Kline
from app.backtest.engine import LONG, OrderParams, StrategyParams
from app.live.signal_processor import LiveSignalProcessor


def bar(index, timestamp, close=100):
    return Kline(index, str(timestamp), 100, max(101, close), 99, close, 10)


class LiveSignalProcessorTests(unittest.TestCase):
    def setUp(self):
        self.strategy = StrategyParams(
            volume_enabled=False,
            single_change_enabled=True,
            single_change_pct=0,
            single_change_max_pct=100,
            consecutive_enabled=False,
            cum_change_enabled=False,
            atr_enabled=False,
            shadow_body_enabled=False,
        )

    def processor(self, klines, direction="BOTH"):
        return LiveSignalProcessor(
            klines, self.strategy, OrderParams(direction=direction),
            lambda *_args: None, lambda key, **kwargs: key.format(**kwargs),
        )

    def test_closed_kline_uses_existing_combined_signal_rules(self):
        processor = self.processor([bar(1, 0, 100)])

        signal = processor.add_closed_kline(bar(0, 60_000, 110))

        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, LONG)
        self.assertEqual(signal.kline.index, 2)

    def test_duplicate_or_older_kline_is_ignored(self):
        processor = self.processor([bar(1, 0), bar(2, 60_000)])

        self.assertIsNone(processor.add_closed_kline(bar(0, 60_000, 110)))
        self.assertEqual(len(processor.klines), 2)

    def test_direction_filter_is_kept(self):
        processor = self.processor([bar(1, 0, 100)], direction="SHORT")

        self.assertIsNone(processor.add_closed_kline(bar(0, 60_000, 110)))

    def test_required_history_uses_enabled_longest_lookback(self):
        strategy = StrategyParams(
            volume_enabled=True, volume_prev_n=10,
            consecutive_enabled=True, consecutive_count=3,
            cum_change_enabled=True, cum_klines=5,
            atr_enabled=True, atr_period=14,
        )

        self.assertEqual(
            LiveSignalProcessor.required_history_bars(strategy), 15)

    def test_latest_preheated_kline_is_evaluated_once(self):
        processor = self.processor([bar(1, 0, 100), bar(2, 60_000, 110)])

        signal = processor.evaluate_latest_closed()

        self.assertIsNotNone(signal)
        self.assertEqual(signal.kline.index, 2)
        self.assertIsNone(processor.evaluate_latest_closed())


if __name__ == "__main__":
    unittest.main()
