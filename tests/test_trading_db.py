from app.storage.trading_db import TradingDatabase


def _order(status="NEW", **overrides):
    order = {
        "orderId": "1001",
        "clientOrderId": "client-1001",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "positionSide": "BOTH",
        "type": "MARKET",
        "origQty": "0.010",
        "executedQty": "0",
        "avgPrice": "0",
        "status": status,
        "updateTime": 1_700_000_000_000,
    }
    order.update(overrides)
    return order


def test_order_upsert_and_filled_trade_are_idempotent(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))

    _, newly_filled = database.upsert_order(_order())
    assert newly_filled is False
    _, newly_filled = database.upsert_order(_order(
        "FILLED", executedQty="0.010", avgPrice="60000"))
    assert newly_filled is True

    filled = _order("FILLED", executedQty="0.010", avgPrice="60000")
    first_trade_id = database.record_filled_trade(filled)
    assert database.record_filled_trade(filled) == first_trade_id
    assert len(database.order_history()) == 1
    assert database.rows("SELECT * FROM trades")[0]["cost"] == 600


def test_position_disappearing_from_exchange_moves_to_history(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.sync_positions([{
        "symbol": "BTCUSDT",
        "positionSide": "BOTH",
        "positionAmt": "-0.02",
        "entryPrice": "61000",
        "liquidationPrice": "80000",
        "unRealizedProfit": "-3.5",
        "leverage": "5",
        "marginType": "cross",
    }])

    assert database.current_positions()[0]["position_side"] == "SHORT"
    database.sync_positions([])
    assert database.current_positions() == []
    history = database.position_history()
    assert len(history) == 1
    assert history[0]["side"] == "SHORT"


def test_reduce_only_one_way_order_uses_position_direction(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    values, _ = database.upsert_order(_order(
        side="SELL", reduceOnly=True, type="TAKE_PROFIT_MARKET"))

    assert values["trade_direction"] == "LONG"
    assert values["action_type"] == "TP"
    assert values["use_type"] == "TP_CLOSE"
