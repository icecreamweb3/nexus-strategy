import unittest

from app.backtest.data_loader import Kline
from app.backtest.engine import BacktestEngine, LONG, SHORT, OrderParams, StrategyParams
from app.i18n import EN, i18n


def kline(index, open_=100, high=101, low=99, close=100, volume=10):
    return Kline(index, str(index), open_, high, low, close, volume)


def params(**overrides):
    values = dict(
        volume_enabled=False,
        single_change_enabled=False,
        consecutive_enabled=False,
        cum_change_enabled=False,
        atr_enabled=False,
        shadow_body_enabled=False,
    )
    values.update(overrides)
    return StrategyParams(**values)


class SignalRuleTests(unittest.TestCase):
    def test_volume_uses_previous_average_and_accepts_equal_threshold(self):
        ks = [kline(1, volume=10), kline(2, volume=20), kline(3, volume=15)]
        engine = BacktestEngine(ks, params(volume_prev_n=2, volume_mult=1), OrderParams())
        self.assertTrue(engine._volume_ok(2))

    def test_single_change_uses_strict_absolute_range_and_sets_direction(self):
        ks = [kline(1, close=100), kline(2, close=102), kline(3, close=99.96)]
        engine = BacktestEngine(
            ks,
            params(single_change_enabled=True,
                   single_change_pct=1,
                   single_change_max_pct=3),
            OrderParams(),
        )
        self.assertEqual(engine._single_change_dir(1), LONG)
        self.assertEqual(engine._single_change_dir(2), SHORT)

        engine.sp.single_change_pct = 2
        self.assertIsNone(engine._single_change_dir(1))  # 等于 C 不通过

    def test_consecutive_allows_doji_and_zero_or_one_disables_rule(self):
        ks = [
            kline(1, open_=100, close=101),
            kline(2, open_=101, close=101),
            kline(3, open_=101, close=102),
        ]
        engine = BacktestEngine(ks, params(consecutive_count=3), OrderParams())
        self.assertTrue(engine._consecutive_ok(2, LONG))
        self.assertFalse(engine._consecutive_ok(2, SHORT))
        engine.sp.consecutive_count = 0
        self.assertTrue(engine._consecutive_ok(0, LONG))
        engine.sp.consecutive_count = 1
        self.assertTrue(engine._consecutive_ok(0, SHORT))

    def test_cumulative_filter_uses_requested_base_and_opposite_move_passes(self):
        ks = [kline(i + 1, open_=100, close=100) for i in range(10)]
        ks[3].close = 100
        ks[9].close = 104
        engine = BacktestEngine(ks, params(cum_klines=6, cum_change_pct=5), OrderParams())
        self.assertTrue(engine._cum_change_ok(9, LONG))
        engine.sp.cum_change_pct = 4
        self.assertFalse(engine._cum_change_ok(9, LONG))  # 等于 F 不通过
        self.assertTrue(engine._cum_change_ok(9, SHORT))  # 空信号遇到上涨不算追空

        ks[0].open = 100
        ks[5].close = 103
        engine.sp.cum_change_pct = 4
        self.assertTrue(engine._cum_change_ok(5, LONG))  # 第6根对比首根开盘

    def test_atr_excludes_signal_candle_and_uses_previous_close_denominator(self):
        ks = [kline(i + 1, high=101, low=99, close=100) for i in range(14)]
        ks.append(kline(15, high=1000, low=1, close=900))
        engine = BacktestEngine(
            ks,
            params(atr_min_pct=1.9, atr_max_pct=2.1),
            OrderParams(),
        )
        self.assertTrue(engine._atr_ok(14))

    def test_atr_period_is_configurable(self):
        ks = [kline(i + 1, high=103, low=99, close=100) for i in range(3)]
        ks.append(kline(4, high=1000, low=1, close=900))
        engine = BacktestEngine(
            ks,
            params(atr_period=3, atr_min_pct=3.9, atr_max_pct=4.1),
            OrderParams(),
        )
        self.assertTrue(engine._atr_ok(3))

        engine.sp.atr_period = 4
        self.assertFalse(engine._atr_ok(3))

    def test_shadow_checks_only_adverse_side_and_rejects_zero_body(self):
        ks = [
            kline(1, open_=100, high=111, low=80, close=110),
            kline(2, open_=100, high=100, low=99, close=100),
        ]
        engine = BacktestEngine(ks, params(shadow_body_upper=0.2), OrderParams())
        self.assertTrue(engine._shadow_body_ok(0, LONG))   # 上影/实体 = 0.1
        self.assertFalse(engine._shadow_body_ok(0, SHORT))  # 下影/实体 = 2
        self.assertFalse(engine._shadow_body_ok(1, LONG))

    def test_market_entry_is_next_kline_open(self):
        ks = [
            kline(1, open_=100, high=101, low=99, close=100),
            kline(2, open_=100, high=111, low=99, close=110),
            kline(3, open_=150, high=152, low=149, close=151),
        ]
        engine = BacktestEngine(
            ks,
            params(single_change_enabled=True,
                   single_change_pct=0,
                   single_change_max_pct=100),
            OrderParams(order_type="MARKET", stop_loss=1000, take_profit=1000),
        )
        trades = engine.run()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].entry_kline, 3)
        self.assertEqual(trades[0].entry_price, 150)

    def test_data_gap_blocks_signal_even_when_row_history_is_long_enough(self):
        ks = [
            Kline(1, "0", 100, 101, 99, 100, 10),
            Kline(2, "60", 100, 102, 99, 101, 10),
            Kline(3, "120", 101, 103, 100, 102, 10),
            Kline(4, "300", 102, 104, 101, 103, 10),  # 缺少两根1分钟K线
            Kline(5, "360", 103, 105, 102, 104, 10),
            Kline(6, "420", 104, 106, 103, 105, 10),
        ]
        engine = BacktestEngine(
            ks,
            params(volume_enabled=True, volume_prev_n=3, volume_mult=0,
                   single_change_enabled=True, single_change_pct=0,
                   single_change_max_pct=100),
            OrderParams(),
        )
        self.assertIsNone(engine._combined_signal(5))

    def test_gap_after_signal_cancels_next_open_entry(self):
        ks = [
            Kline(1, "0", 100, 101, 99, 100, 10),
            Kline(2, "60", 100, 111, 99, 110, 10),
            Kline(3, "180", 150, 152, 149, 151, 10),
        ]
        engine = BacktestEngine(
            ks,
            params(single_change_enabled=True, single_change_pct=0,
                   single_change_max_pct=100),
            OrderParams(order_type="MARKET", stop_loss=0, take_profit=0),
        )
        self.assertEqual(engine.run(), [])

    def test_kline_log_uses_required_single_line_format(self):
        messages = []
        ks = [Kline(
            3, "2026-02-27T08:02:00.000000000",
            67432.3, 67450.4, 67404.0, 67409.8, 34.946,
        )]
        engine = BacktestEngine(
            ks, params(), OrderParams(),
            log=lambda message, triggered=False: messages.append(message),
        )
        engine._log_kline(0, (False, False, False, False))
        self.assertTrue(messages[0].startswith(
            "K线 #3 | 2026-02-27T08:02:00.000000000 | 收盘价: 67409.80 | "
            "成交量:34.946 | 趋势策略: ✗ | 形态策略: ✗ | 反转策略: ✗ | "
            "成交比策略: ✗ | 检测详情: "))
        self.assertIn("K线连续性: ✗ [1/2]", messages[0])
        self.assertIn("单根涨跌幅: ✓ [未启用]", messages[0])

    def test_kline_log_supports_english_display(self):
        messages = []
        ks = [Kline(
            3, "2026-02-27T08:02:00.000000000",
            67432.3, 67450.4, 67404.0, 67409.8, 34.946,
        )]
        engine = BacktestEngine(
            ks, params(), OrderParams(),
            log=lambda message, triggered=False: messages.append(message),
            translate=lambda key, **kwargs: i18n().tr_for(EN, key, **kwargs),
        )
        engine._log_kline(0, (False, False, False, False))
        self.assertTrue(messages[0].startswith(
            "K-line #3 | 2026-02-27T08:02:00.000000000 | Close: 67409.80 | "
            "Volume:34.946 | Trend Strategy: ✗ | Pattern Strategy: ✗ | "
            "Reversal Strategy: ✗ | Volume Ratio Strategy: ✗ | Check Details: "))
        self.assertIn("K-line Continuity: ✗ [1/2]", messages[0])
        self.assertIn("Single Change: ✓ [Disabled]", messages[0])

    def test_kline_log_details_include_values_and_condition_expressions(self):
        messages = []
        ks = [
            Kline(1, "0", 100, 101, 99, 100, 10),
            Kline(2, "60", 100, 102, 99, 101, 20),
            Kline(3, "120", 101, 102.2, 100.5, 102, 30),
        ]
        strategy = params(
            volume_enabled=True, volume_prev_n=2, volume_mult=1.5,
            single_change_enabled=True, single_change_pct=0.5,
            single_change_max_pct=2,
            consecutive_enabled=True, consecutive_count=2,
            cum_change_enabled=True, cum_klines=2, cum_change_pct=3,
            atr_enabled=True, atr_period=1, atr_min_pct=2, atr_max_pct=4,
            shadow_body_enabled=True, shadow_body_upper=0.5,
        )
        engine = BacktestEngine(
            ks, strategy, OrderParams(),
            log=lambda message, triggered=False: messages.append(message),
        )

        engine._log_kline(2, engine._strategy_statuses(2))

        detail = messages[0]
        self.assertIn("K线连续性: ✓ [3/2]", detail)
        self.assertIn("单根涨跌幅: ✓ [|0.990099%| ∈ (0.5%, 2%)]", detail)
        self.assertIn("连续同向K线: ✓ [2/2 (LONG)]", detail)
        self.assertIn("累计涨跌幅: ✓ [2% < 3%", detail)
        self.assertIn("ATR幅度: ✓ [2.9703% ∈ [2%, 4%]", detail)
        self.assertIn("逆势影线/实体比: ✓ [0.2 < 0.5", detail)
        self.assertIn("成交量倍数: ✓ [30 >= 22.5]", detail)

    def test_kline_log_simplifies_missing_atr_history(self):
        messages = []
        engine = BacktestEngine(
            [kline(1)], params(atr_enabled=True, atr_period=14), OrderParams(),
            log=lambda message, triggered=False: messages.append(message),
        )

        engine._log_kline(0, engine._strategy_statuses(0))

        self.assertIn("ATR幅度: ✗ [N/A (历史 1/15)]", messages[0])


if __name__ == "__main__":
    unittest.main()
