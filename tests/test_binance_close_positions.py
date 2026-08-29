from app.client.binance_client import BinanceClient


class FakePositionClient:
    def __init__(self, failed_symbol=None):
        self.failed_symbol = failed_symbol
        self.close_calls = []
        self.status_calls = []

    def get_positions(self):
        return [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.001",
                "positionSide": "BOTH",
            },
            {
                "symbol": "ETHUSDT",
                "positionAmt": "-0.02",
                "positionSide": "SHORT",
            },
            {
                "symbol": "BNBUSDT",
                "positionAmt": "0",
                "positionSide": "BOTH",
            },
        ]

    def close_position(self, symbol, quantity, side):
        self.close_calls.append((symbol, quantity, side))
        if symbol == self.failed_symbol:
            return {"error": True, "error_message": "rejected"}
        return {"symbol": symbol, "orderId": len(self.close_calls), "status": "NEW"}

    def get_order_status(self, symbol, order_id):
        self.status_calls.append((symbol, order_id))
        return {"symbol": symbol, "orderId": int(order_id), "status": "FILLED"}


def test_close_all_positions_closes_one_way_and_hedge_positions():
    client = FakePositionClient()

    summary = BinanceClient.close_all_positions(client)

    assert client.close_calls == [
        ("BTCUSDT", 0.001, "LONG"),
        ("ETHUSDT", 0.02, "SHORT"),
    ]
    assert client.status_calls == [("BTCUSDT", "1"), ("ETHUSDT", "2")]
    assert summary["failed"] == []
    assert [item["order"]["status"] for item in summary["closed"]] == [
        "FILLED", "FILLED",
    ]


def test_close_all_positions_continues_after_one_position_fails():
    client = FakePositionClient(failed_symbol="BTCUSDT")

    summary = BinanceClient.close_all_positions(client)

    assert client.close_calls == [
        ("BTCUSDT", 0.001, "LONG"),
        ("ETHUSDT", 0.02, "SHORT"),
    ]
    assert [item["symbol"] for item in summary["closed"]] == ["ETHUSDT"]
    assert summary["failed"] == [{
        "symbol": "BTCUSDT",
        "side": "LONG",
        "quantity": 0.001,
        "error": "rejected",
    }]
