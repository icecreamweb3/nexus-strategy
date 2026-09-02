import unittest

from app.backtest.data_loader import Kline
from app.backtest.engine import (
    BacktestEngine, LONG, OrderParams, StrategyParams,
    base_order_notional, required_order_margin,
)


def kline(index, open_, high, low, close):
    return Kline(index, str(index), open_, high, low, close, 10)


def signal_params():
    return StrategyParams(
        volume_enabled=False,
        single_change_enabled=True,
        single_change_pct=0,
        single_change_max_pct=100,
        consecutive_enabled=False,
        cum_change_enabled=False,
        atr_enabled=False,
        shadow_body_enabled=False,
    )


class OrderLogicTests(unittest.TestCase):
    def test_default_leverage_is_one_hundred(self):
        self.assertEqual(OrderParams().leverage, 100.0)

    def test_order_amount_uses_capital_split_count_and_leverage_multiplier(self):
        engine = BacktestEngine(
            [], signal_params(),
            OrderParams(total_capital=100000, split_count=5, leverage=6),
        )

        position = engine._new_position(LONG, 1, 100)

        self.assertEqual(position.cost, 120000)
        self.assertEqual(position.qty, 1200)

    def test_documented_position_size_example(self):
        engine = BacktestEngine(
            [], signal_params(),
            OrderParams(total_capital=1000, split_count=10, leverage=5),
        )

        position = engine._new_position(LONG, 1, 78000)

        self.assertEqual(position.cost, 500)
        self.assertAlmostEqual(position.qty, 500 / 78000)

    def test_one_hundred_x_reduces_margin_without_increasing_notional(self):
        notional = base_order_notional(100, 1)

        required = required_order_margin(notional, 100, 0.03)

        self.assertEqual(notional, 100)
        self.assertAlmostEqual(required, 1.035)

    def test_next_order_uses_capital_remaining_after_close(self):
        cases = (("SL", 90, 88000, 105600), ("TP", 110, 112000, 134400))
        for exit_type, exit_price, capital, next_amount in cases:
            with self.subTest(exit_type=exit_type):
                engine = BacktestEngine(
                    [], signal_params(),
                    OrderParams(total_capital=100000, split_count=5, leverage=6,
                                fee_rate_pct=0),
                )
                first = engine._new_position(LONG, 1, 100)

                engine._close_trade(first, 2, exit_price, exit_type)
                second = engine._new_position(LONG, 3, 100)

                self.assertEqual(first.cost, 120000)
                self.assertEqual(engine.current_capital, capital)
                self.assertEqual(second.cost, next_amount)

    def test_exit_kline_is_scanned_and_signal_enters_on_next_open(self):
        ks = [
            kline(1, 90, 91, 89, 90),
            kline(2, 90, 101, 89, 100),   # signal; first entry on #3
            kline(3, 100, 111, 94, 110),  # SL and a valid LONG signal
            kline(4, 123, 124, 122, 123), # re-entry must happen here
            kline(5, 123, 124, 122, 123),
        ]
        trades = BacktestEngine(
            ks, signal_params(),
            OrderParams(leverage=1, fee_rate_pct=0, stop_loss=5,
                        take_profit=0, stop_cooldown=10),
        ).run()

        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].exit_type, "SL")
        self.assertEqual(trades[0].exit_kline, 3)
        self.assertEqual(trades[1].entry_kline, 4)

    def test_add_then_stop_then_take_profit_priority_on_entry_kline(self):
        logs = []
        ks = [
            kline(1, 90, 91, 89, 90),
            kline(2, 90, 101, 89, 100),
            kline(3, 100, 110, 80, 100),
        ]
        engine = BacktestEngine(
            ks,
            signal_params(),
            OrderParams(
                total_capital=10000,
                leverage=1,
                fee_rate_pct=0,
                order_type="MARKET",
                add_interval_pct=10,
                add_mult=1,
                add_count=2,
                stop_loss=10,
                take_profit=10,
                reverse_trading=False,
            ),
            log=lambda message, triggered=False: logs.append(message),
        )
        trades = engine.run()

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].exit_type, "SL")
        self.assertEqual(trades[0].entry_kline, 3)
        self.assertAlmostEqual(trades[0].entry_price, 94.7368421053)
        self.assertEqual(trades[0].amount, 20000)
        self.assertAlmostEqual(trades[0].qty, 211.1111111111)
        self.assertLess(logs.index(next(x for x in logs if x.startswith("加仓"))),
                        logs.index(next(x for x in logs if "止损" in x)))

    def test_zero_add_parameter_or_total_count_one_disables_adding(self):
        bar = kline(2, 100, 120, 80, 100)
        disabled_values = (
            dict(add_interval_pct=0, add_mult=1, add_count=2),
            dict(add_interval_pct=10, add_mult=0, add_count=2),
            dict(add_interval_pct=10, add_mult=1, add_count=0),
            dict(add_interval_pct=10, add_mult=1, add_count=1),
        )
        for values in disabled_values:
            with self.subTest(values=values):
                engine = BacktestEngine([], signal_params(), OrderParams(**values))
                position = engine._new_position(LONG, 1, 100)
                self.assertFalse(engine._try_add_position(position, bar))
                self.assertEqual(position.adds, 0)

    def test_market_entry_kline_checks_percentage_stop_loss(self):
        ks = [
            kline(1, 90, 91, 89, 90),
            kline(2, 90, 101, 89, 100),
            kline(3, 100, 101, 94, 100),
        ]
        trades = BacktestEngine(
            ks,
            signal_params(),
            OrderParams(order_type="MARKET", stop_loss=5, take_profit=20,
                        reverse_trading=False),
        ).run()
        self.assertEqual(trades[0].exit_type, "SL")
        self.assertEqual(trades[0].entry_kline, 3)
        self.assertEqual(trades[0].exit_kline, 3)
        self.assertEqual(trades[0].exit_price, 95)

    def test_legacy_limit_setting_still_uses_next_open_and_checks_stop(self):
        ks = [
            kline(1, 90, 91, 89, 90),
            kline(2, 90, 101, 89, 100),
            kline(3, 100, 101, 90, 100),
        ]
        trades = BacktestEngine(
            ks,
            signal_params(),
            OrderParams(order_type="LIMIT", limit_offset=0, stop_loss=5,
                        take_profit=20, reverse_trading=False),
        ).run()
        self.assertEqual(trades[0].exit_type, "SL")
        self.assertEqual(trades[0].entry_kline, 3)
        self.assertEqual(trades[0].exit_kline, 3)
        self.assertEqual(trades[0].entry_price, 100)

    def test_direction_one_ignores_short_and_waits_for_long(self):
        ks = [
            kline(1, 100, 101, 99, 100),
            kline(2, 100, 101, 89, 90),   # SHORT，忽略
            kline(3, 90, 100, 89, 99),    # LONG，采用
            kline(4, 123, 125, 122, 124),
        ]
        trades = BacktestEngine(
            ks,
            signal_params(),
            OrderParams(order_type="MARKET", direction="LONG", stop_loss=0,
                        take_profit=0, reverse_trading=False),
        ).run()
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].side, LONG)
        self.assertEqual(trades[0].entry_kline, 4)
        self.assertEqual(trades[0].entry_price, 123)

    def test_entry_bar_is_first_max_hold_kline(self):
        ks = [
            kline(1, 90, 91, 89, 90),
            kline(2, 90, 101, 89, 100),
            kline(3, 100, 101, 99, 100),
            kline(4, 100, 102, 99, 101),
        ]
        trades = BacktestEngine(
            ks,
            signal_params(),
            OrderParams(order_type="MARKET", stop_loss=0, take_profit=0,
                        max_hold_klines=2, reverse_trading=False),
        ).run()
        self.assertEqual(trades[0].exit_type, "TIMEOUT")
        self.assertEqual(trades[0].entry_kline, 3)
        self.assertEqual(trades[0].exit_kline, 4)
        self.assertEqual(trades[0].exit_price, 101)


if __name__ == "__main__":
    unittest.main()
