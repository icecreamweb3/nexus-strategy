from app.client.binance_client import BinanceClient, _log_filled_trade_response


class CapturingLogger:
    def __init__(self):
        self.messages = []

    def _capture(self, message, *args):
        self.messages.append(message % args)

    info = _capture
    warning = _capture
    error = _capture
    exception = _capture


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


def test_mode_setters_do_not_send_changes_while_positions_exist():
    calls = []

    class RawClient:
        @staticmethod
        def futures_position_information(**_kwargs):
            return [{"symbol": "BTCUSDT", "positionAmt": "0.001"}]

        @staticmethod
        def futures_change_position_mode(**_kwargs):
            calls.append("position-mode")

        @staticmethod
        def futures_change_multi_assets_mode(**_kwargs):
            calls.append("assets-mode")

        @staticmethod
        def futures_change_margin_type(**_kwargs):
            calls.append("margin-type")

    client = object.__new__(BinanceClient)
    client.client = RawClient()

    assert client.set_position_mode(False) is False
    assert client.set_multi_assets_mode(False) is False
    assert client.set_cross_margin("BTCUSDT") is False
    assert calls == []


def test_spot_account_info_uses_spot_account_endpoint():
    class RawClient:
        @staticmethod
        def get_account():
            return {"balances": [{"asset": "USDT", "free": "12"}]}

    client = object.__new__(BinanceClient)
    client.client = RawClient()

    assert client.get_spot_account_info()["balances"][0]["free"] == "12"


def test_futures_account_snapshot_retries_transient_failure(monkeypatch):
    calls = []

    class RawClient:
        @staticmethod
        def futures_account(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ConnectionError("proxy temporarily unavailable")
            return {"assets": [{"asset": "USDT", "walletBalance": "88"}]}

    client = object.__new__(BinanceClient)
    client.client = RawClient()
    client.MAX_RETRIES = 1
    client.DEFAULT_RECV_WINDOW = 60_000
    monkeypatch.setattr("app.client.binance_client.time.sleep", lambda _delay: None)

    result = client.get_account_info()

    assert result["assets"][0]["walletBalance"] == "88"
    assert calls == [{"recvWindow": 60_000}, {"recvWindow": 60_000}]
    assert client.last_futures_account_error is None


def test_futures_account_snapshot_preserves_original_error(monkeypatch):
    class RawClient:
        @staticmethod
        def futures_account(**_kwargs):
            raise TimeoutError("proxy unavailable")

    client = object.__new__(BinanceClient)
    client.client = RawClient()
    client.MAX_RETRIES = 1
    client.DEFAULT_RECV_WINDOW = 60_000
    monkeypatch.setattr("app.client.binance_client.time.sleep", lambda _delay: None)

    assert client.get_account_info() == {}
    assert client.last_futures_account_error == \
        "TimeoutError: proxy unavailable"


def test_filled_trade_log_contains_fee_fields_but_not_credentials(monkeypatch):
    summaries = []
    details = []

    class FakeLogger:
        def __init__(self, messages):
            self.messages = messages

        def info(self, message, *args):
            self.messages.append(message % args)

        def debug(self, message, *args):
            self.messages.append(message % args)

    monkeypatch.setattr(
        "app.client.binance_client.get_logger", lambda: FakeLogger(summaries))
    monkeypatch.setattr(
        "app.client.binance_client.get_trade_detail_logger",
        lambda: FakeLogger(details))

    _log_filled_trade_response("get_user_trades", {
        "symbol": "BTCUSDT", "limit": 20,
        "timestamp": 123, "signature": "secret",
    }, [{
        "id": 1, "orderId": 2, "symbol": "BTCUSDT", "price": "80000",
        "qty": "0.006", "commission": "0.144",
        "commissionAsset": "USDT", "realizedPnl": "1.2",
    }])

    assert len(summaries) == 1
    assert "count=1" in summaries[0]
    output = "\n".join(details)
    assert "commission': '0.144'" in output
    assert "commissionAsset': 'USDT'" in output
    assert "signature" not in output
    assert "secret" not in output


def test_filled_trade_detail_log_can_be_disabled(monkeypatch):
    summaries = []

    class FakeSystemLogger:
        def info(self, message, *args):
            summaries.append(message % args)

    monkeypatch.setattr(
        "app.client.binance_client.get_logger", lambda: FakeSystemLogger())
    monkeypatch.setattr(
        "app.client.binance_client.get_trade_detail_logger", lambda: None)

    _log_filled_trade_response("get_user_trades", {"symbol": "BTCUSDT"}, [{
        "id": 1, "orderId": 2, "symbol": "BTCUSDT",
    }])

    assert len(summaries) == 1
    assert "count=1" in summaries[0]


def test_bnb_fee_is_valued_in_symbol_quote_asset_at_fill_minute():
    calls = []

    class RawClient:
        @staticmethod
        def futures_klines(**kwargs):
            calls.append(kwargs)
            return [[1788367740000, "600", "602", "598", "601", "1"]]

    client = object.__new__(BinanceClient)
    client.client = RawClient()
    trades = client._enrich_trade_fee_values([{
        "symbol": "BTCUSDT", "price": "77244.20", "time": 1788367741177,
        "commission": "0.00030366", "commissionAsset": "BNB",
    }])

    assert trades[0]["commissionValue"] == 0.00030366 * 601
    assert trades[0]["commissionValueAsset"] == "USDT"
    assert calls == [{
        "symbol": "BNBUSDT", "interval": "1m",
        "startTime": 1788367740000, "endTime": 1788367799999, "limit": 1,
    }]


def test_quote_asset_fee_needs_no_price_request():
    client = object.__new__(BinanceClient)
    trades = client._enrich_trade_fee_values([{
        "symbol": "BTCUSDT", "price": "77244.20", "time": 1788367741177,
        "commission": "0.25", "commissionAsset": "USDT",
    }])

    assert trades[0]["commissionValue"] == 0.25
    assert trades[0]["commissionValueAsset"] == "USDT"


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


def test_close_position_writes_request_and_result_to_system_log(monkeypatch):
    captured = CapturingLogger()
    client = object.__new__(BinanceClient)
    client.get_position_mode = lambda: False
    client.place_market_order = lambda **_kwargs: {
        "orderId": 123, "status": "FILLED", "executedQty": "0.01",
        "avgPrice": "80000",
    }
    monkeypatch.setattr(
        "app.client.binance_client.get_logger", lambda: captured)

    result = BinanceClient.close_position(client, "BTCUSDT", 0.01, "LONG")

    assert result["orderId"] == 123
    output = "\n".join(captured.messages)
    assert "提交市价平仓订单" in output
    assert "市价平仓订单已提交" in output
    assert "order_id=123" in output


def test_close_all_positions_logs_completion_summary(monkeypatch):
    captured = CapturingLogger()
    client = FakePositionClient()
    monkeypatch.setattr(
        "app.client.binance_client.get_logger", lambda: captured)

    BinanceClient.close_all_positions(client)

    output = "\n".join(captured.messages)
    assert "开始关闭账户全部头寸" in output
    assert "关闭头寸订单核验" in output
    assert "closed=2 failed=0" in output


def test_cancel_all_open_orders_cancels_regular_and_algo_then_confirms():
    class FakeOrderClient:
        def __init__(self):
            self.regular_reads = 0
            self.algo_reads = 0
            self.calls = []

        def get_open_orders(self, symbol=None):
            self.regular_reads += 1
            return ([{"symbol": "BTCUSDT", "orderId": 11}]
                    if self.regular_reads == 1 else [])

        def get_all_algo_orders(self, symbol=None):
            self.algo_reads += 1
            return ([{"symbol": "BTCUSDT", "algoId": 22}]
                    if self.algo_reads == 1 else [])

        def cancel_order(self, symbol, order_id):
            self.calls.append(("regular", symbol, order_id))
            return {"orderId": int(order_id), "status": "CANCELED"}

        def cancel_algo_order(self, **kwargs):
            self.calls.append(("algo", kwargs["symbol"], kwargs["algo_id"]))
            return {"algoId": kwargs["algo_id"], "status": "CANCELED"}

    client = FakeOrderClient()

    summary = BinanceClient.cancel_all_open_orders(client, "BTCUSDT")

    assert client.calls == [
        ("regular", "BTCUSDT", "11"),
        ("algo", "BTCUSDT", 22),
    ]
    assert len(summary["canceled"]) == 2
    assert summary["failed"] == []
    assert summary["remaining_regular"] == []
    assert summary["remaining_algo"] == []
