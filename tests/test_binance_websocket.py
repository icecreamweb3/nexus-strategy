import json
import unittest
from unittest.mock import patch

from app.client.binance_websocket import OrdersMonitor


class BinanceWebsocketTests(unittest.TestCase):
    def test_closed_kline_callback_ignores_open_updates(self):
        received = []
        monitor = OrdersMonitor(
            object(), symbol="BTCUSDT", interval="1m",
            on_kline_closed=received.append,
        )
        payload = {"e": "kline", "k": {
            "t": 1, "o": "100", "h": "101", "l": "99",
            "c": "100", "v": "10", "x": False, "T": 999,
        }}

        monitor._on_kline_message(None, json.dumps(payload))
        payload["k"]["x"] = True
        payload["E"] = 1000
        monitor._on_kline_message(None, json.dumps(payload))

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["t"], 1)

    def test_kline_rejects_truthy_string_and_event_before_close(self):
        received = []
        monitor = OrdersMonitor(
            object(), symbol="BTCUSDT", interval="1m",
            on_kline_closed=received.append)
        payload = {"e": "kline", "E": 2000, "k": {
            "t": 1000, "T": 1999, "x": "false",
        }}
        monitor._on_kline_message(None, json.dumps(payload))
        payload["k"]["x"] = True
        payload["E"] = 1998
        monitor._on_kline_message(None, json.dumps(payload))

        self.assertEqual(received, [])

    @patch("app.client.binance_websoket.threading.Timer")
    @patch("app.client.binance_websoket.time.time", return_value=1.5)
    def test_final_kline_waits_until_local_close_boundary(self, _time, timer_class):
        received = []
        monitor = OrdersMonitor(
            object(), symbol="BTCUSDT", interval="1m",
            on_kline_closed=received.append)
        monitor.running = True
        payload = {"e": "kline", "E": 2000, "k": {
            "t": 1000, "T": 1999, "x": True,
        }}

        monitor._on_kline_message(None, json.dumps(payload))

        self.assertEqual(received, [])
        self.assertAlmostEqual(timer_class.call_args.args[0], 0.5, places=3)
        timer_class.call_args.args[1](*timer_class.call_args.kwargs["args"])
        self.assertEqual(len(received), 1)

    def test_order_update_callback_receives_raw_order(self):
        received = []
        monitor = OrdersMonitor(object(), on_order_update=received.append)
        order = {"i": 7, "X": "NEW", "x": "NEW", "z": "0",
                 "ap": "0", "o": "MARKET", "ps": "BOTH"}

        monitor._handle_order_update(order)

        self.assertEqual(received, [order])
        self.assertIn("7", monitor.order_status_cache)

    def test_perpetual_price_callback_uses_agg_trade_price(self):
        received = []
        monitor = OrdersMonitor(
            None, symbol="BTCUSDT", on_price_update=received.append)

        monitor._on_price_message(None, json.dumps({"p": "79744.80"}))

        self.assertEqual(received, [79744.80])

    def test_market_only_mode_does_not_request_listen_key(self):
        monitor = OrdersMonitor(None, symbol="BTCUSDT", on_price_update=lambda _: None)
        started = []
        monitor._start_price_stream = lambda: started.append(True)

        monitor.start_market_only()

        self.assertTrue(monitor.running)
        self.assertEqual(started, [True])
        monitor.stop()


if __name__ == "__main__":
    unittest.main()
