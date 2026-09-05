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


def test_position_protection_prices_survive_position_refresh(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    position = {
        "symbol": "BTCUSDT", "positionSide": "BOTH",
        "positionAmt": "0.001", "entryPrice": "77500",
        "leverage": "100", "marginType": "cross",
    }
    database.sync_positions([position])
    database.set_position_protection(
        "BTCUSDT", "LONG", tp_price=78275, sl_price=76725)

    database.sync_positions([position])

    current = database.current_positions()[0]
    assert current["tp_price"] == 78275
    assert current["sl_price"] == 76725


def test_user_trades_rebuild_closed_position_and_update_order(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.sync_positions([{
        "symbol": "BTCUSDT", "positionSide": "BOTH",
        "positionAmt": "0.01", "entryPrice": "60000",
    }])
    database.upsert_order(_order(
        "FILLED", orderId="2002", side="SELL", reduceOnly=True,
        executedQty="0.01", avgPrice="61000"))

    user_trades = [
        {
            "id": 11, "orderId": 2001, "symbol": "BTCUSDT",
            "side": "BUY", "positionSide": "BOTH", "price": "60000",
            "qty": "0.01", "commission": "0.30",
            "commissionAsset": "USDT", "realizedPnl": "0", "time": 1000,
        },
        {
            "id": 12, "orderId": 2002, "symbol": "BTCUSDT",
            "side": "SELL", "positionSide": "BOTH", "price": "61000",
            "qty": "0.01", "commission": "0.31",
            "commissionAsset": "USDT", "realizedPnl": "10", "time": 2000,
        },
    ]
    completed = database.sync_user_trades(user_trades)
    database.sync_positions([], symbols=("BTCUSDT",))

    assert completed == 1
    history = database.position_history()
    assert len(history) == 1
    assert history[0]["side"] == "LONG"
    assert history[0]["entry_price"] == 60000
    assert history[0]["close_price"] == 61000
    assert history[0]["realized_pnl"] == 10
    assert history[0]["commission"] == 0.61
    order = database.rows("SELECT * FROM orders WHERE order_id='2002'")[0]
    assert order["realized_pnl"] == 10
    assert order["commission"] == 0.31

    # Repeating a manual synchronization updates the same official cycle.
    assert database.sync_user_trades(user_trades) == 1
    assert len(database.position_history()) == 1

    pnl, count = database.claim_position_realized_pnl(["2002"])
    assert (pnl, count) == (10, 1)
    assert database.claim_position_realized_pnl(["2002"]) == (0, 1)


def test_websocket_limit_update_keeps_saved_tp_classification(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.upsert_order(_order(
        orderId="3001", side="SELL", type="LIMIT",
        action_type="TP", use_type="TP_CLOSE"))

    values, _ = database.upsert_order(_order(
        "FILLED", orderId="3001", side="SELL", type="LIMIT",
        executedQty="0.01", avgPrice="61000"))

    assert values["action_type"] == "TP"
    assert values["use_type"] == "TP_CLOSE"
    database.record_filled_trade(_order(
        "FILLED", orderId="3001", side="SELL", type="LIMIT",
        executedQty="0.01", avgPrice="61000"))
    assert database.rows("SELECT * FROM trades")[0]["trade_type"] == "TAKE_PROFIT"


def test_symbol_scoped_position_sync_does_not_close_other_symbols(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.sync_positions([
        {"symbol": "BTCUSDT", "positionSide": "BOTH", "positionAmt": "0.01"},
        {"symbol": "ETHUSDT", "positionSide": "BOTH", "positionAmt": "0.5"},
    ])

    database.sync_positions([], symbols=("BTCUSDT",))

    assert [row["symbol"] for row in database.current_positions()] == ["ETHUSDT"]


def test_order_history_defaults_to_latest_ten(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    for order_id in range(12):
        database.upsert_order(_order(
            "FILLED", orderId=str(order_id), updateTime=order_id * 1000))

    history = database.order_history()

    assert len(history) == 10
    assert [row["order_id"] for row in history[:2]] == ["11", "10"]


def test_open_order_snapshot_removes_stale_local_orders(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.upsert_order(_order("NEW", orderId="1"))
    database.upsert_order(_order("NEW", orderId="2"))

    database.reconcile_open_orders("BTCUSDT", ["2"])

    assert [row["order_id"] for row in database.current_orders()] == ["2"]
    assert database.rows(
        "SELECT status FROM orders WHERE order_id='1'")[0]["status"] == "CANCELED"
