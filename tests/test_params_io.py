import configparser
import os
import tempfile
import unittest

from app.backtest.engine import OrderParams, StrategyParams
from app.backtest.params_io import ParamsFileError, load_params, save_params


class ParamsIoTests(unittest.TestCase):
    def test_strategy_and_order_round_trip_in_one_inf_file(self):
        strategy = StrategyParams(
            volume_enabled=False,
            volume_prev_n=23,
            volume_mult=1.75,
            single_change_pct=0.12,
            single_change_max_pct=2.5,
            consecutive_count=4,
            cum_klines=6,
            cum_change_pct=3.2,
            atr_min_pct=0.2,
            atr_max_pct=1.8,
            shadow_body_upper=0.35,
        )
        order = OrderParams(
            position_size=2500,
            fee_rate_pct=0.04,
            stop_loss=1.2,
            stop_cooldown=8,
            take_profit=2.4,
            direction="LONG",
            add_interval_pct=0.8,
            add_mult=1.5,
            add_count=3,
            max_hold_klines=120,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "params.inf")
            save_params(path, strategy, order)
            loaded_strategy, loaded_order = load_params(path)

            self.assertEqual(loaded_strategy.volume_enabled, False)
            self.assertEqual(loaded_strategy.volume_prev_n, 23)
            self.assertEqual(loaded_strategy.shadow_body_upper, 0.35)
            self.assertEqual(loaded_order.position_size, 2500)
            self.assertEqual(loaded_order.direction, "LONG")
            self.assertEqual(loaded_order.add_count, 3)

            config = configparser.ConfigParser()
            config.read(path, encoding="utf-8")
            self.assertTrue(config.has_section("strategy"))
            self.assertTrue(config.has_section("order"))

    def test_invalid_inf_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "invalid.inf")
            with open(path, "w", encoding="utf-8") as output:
                output.write("[strategy]\nvolume_enabled = true\n")
            with self.assertRaises(ParamsFileError):
                load_params(path)


if __name__ == "__main__":
    unittest.main()
