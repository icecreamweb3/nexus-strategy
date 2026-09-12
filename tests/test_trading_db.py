import sqlite3

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


def test_algo_update_reclassifies_existing_actual_market_order(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.upsert_order(_order(
        "FILLED", orderId="901", side="SELL", executedQty="0.01",
        avgPrice="99", realizedPnl="-1"))

    database.upsert_order(_order(
        "FINISHED", orderId="900", side="SELL", type="STOP_MARKET",
        ai="901", reduceOnly=True))

    actual = database.rows(
        "SELECT action_type, use_type, reduce_only FROM orders "
        "WHERE order_id='901'")[0]
    assert actual["action_type"] == "SL"
    assert actual["use_type"] == "SL_CLOSE"
    assert actual["reduce_only"] == 1


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


def test_position_open_time_survives_position_refresh(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    position = {
        "symbol": "BTCUSDT", "positionSide": "BOTH",
        "positionAmt": "-0.005", "entryPrice": "79221.8",
        "openTime": 1_788_946_870_609,
    }

    database.sync_positions([position])
    first = database.current_positions()[0]

    database.sync_positions([{**position, "openTime": 1_788_947_088_000}])
    refreshed = database.current_positions()[0]

    assert first["opened_at"] == "2026-09-09T09:41:10+00:00"
    assert refreshed["opened_at"] == first["opened_at"]
    assert refreshed["updated_at"] >= first["updated_at"]


def test_reopened_position_gets_a_new_open_time(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    base = {
        "symbol": "BTCUSDT", "positionSide": "BOTH",
        "positionAmt": "0.005", "entryPrice": "79000",
    }
    database.sync_positions([{**base, "openTime": 1_700_000_000_000}])
    database.sync_positions([], symbols=("BTCUSDT",))

    database.sync_positions([{**base, "openTime": 1_700_000_060_000}])

    assert database.current_positions()[0]["opened_at"] \
        == "2023-11-14T22:14:20+00:00"


def test_old_database_migration_restores_open_time_from_live_session(tmp_path):
    path = tmp_path / "trading.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE positions ("
            "id INTEGER PRIMARY KEY, exchange TEXT, symbol TEXT, "
            "position_side TEXT, status TEXT, updated_at TEXT)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX ux_positions_exchange_symbol_side "
            "ON positions(exchange, symbol, position_side)"
        )
        connection.execute(
            "CREATE TABLE live_session_state ("
            "id INTEGER PRIMARY KEY, active INTEGER, symbol TEXT, "
            "interval TEXT, strategy_capital REAL, entry_time_ms INTEGER, "
            "started_at TEXT, updated_at TEXT)"
        )
        connection.execute(
            "INSERT INTO positions VALUES "
            "(1, 'binance', 'BTCUSDT', 'SHORT', 'OPEN', "
            "'2026-09-09T09:47:47+00:00')"
        )
        connection.execute(
            "INSERT INTO live_session_state VALUES "
            "(1, 1, 'BTCUSDT', '1m', 100, 1788946870609, "
            "'2026-09-09T09:40:54+00:00', "
            "'2026-09-09T09:47:47+00:00')"
        )

    database = TradingDatabase(str(path))

    assert database.current_positions()[0]["opened_at"] \
        == "2026-09-09T09:41:10+00:00"


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
    assert (pnl, count) == (9.39, 1)
    assert database.claim_position_realized_pnl(["2002"]) == (0, 1)


def test_bnb_commission_uses_quote_value_for_net_pnl(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.upsert_order(_order(
        "FILLED", orderId="4002", side="SELL", reduceOnly=True,
        executedQty="0.01", avgPrice="61000"))

    database.sync_user_trades([
        {
            "id": 31, "orderId": 4001, "symbol": "BTCUSDT",
            "side": "BUY", "positionSide": "BOTH", "price": "60000",
            "qty": "0.01", "commission": "0.0001",
            "commissionAsset": "BNB", "commissionValue": "0.06",
            "realizedPnl": "0", "time": 1000,
        },
        {
            "id": 32, "orderId": 4002, "symbol": "BTCUSDT",
            "side": "SELL", "positionSide": "BOTH", "price": "61000",
            "qty": "0.01", "commission": "0.0001",
            "commissionAsset": "BNB", "commissionValue": "0.061",
            "realizedPnl": "10", "time": 2000,
        },
    ])

    history = database.position_history()[0]
    assert history["commission"] == 0.0002
    assert history["commission_asset"] == "BNB"
    assert history["commission_value"] == 0.121
    assert database.claim_position_realized_pnl(["4002"]) == (9.879, 1)


def test_native_fee_without_conversion_is_not_deducted_as_quote_currency(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.sync_user_trades([
        {
            "id": 41, "orderId": 4101, "symbol": "BTCUSDT",
            "side": "BUY", "positionSide": "BOTH", "price": "60000",
            "qty": "0.01", "commission": "0.0001",
            "commissionAsset": "BNB", "realizedPnl": "0", "time": 1000,
        },
        {
            "id": 42, "orderId": 4102, "symbol": "BTCUSDT",
            "side": "SELL", "positionSide": "BOTH", "price": "61000",
            "qty": "0.01", "commission": "0.0001",
            "commissionAsset": "BNB", "realizedPnl": "10", "time": 2000,
        },
    ])

    assert database.position_history()[0]["commission_value"] is None
    assert database.claim_position_realized_pnl(["4102"]) == (0, 0)


def test_commission_uses_raw_order_event_value():
    values = TradingDatabase._order_values(_order(
        "FILLED", fee="0.0006"))

    assert values["commission"] == 0.0006


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


def test_live_session_state_round_trip_and_deactivation(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))

    database.save_live_session(
        active=True, symbol="btcusdt", interval="1h",
        strategy_capital=123.45, entry_time_ms=1_700_000_000_000,
        started_at="2026-09-07T01:00:00+00:00",
    )

    session = database.load_live_session()
    assert session["active"] == 1
    assert session["symbol"] == "BTCUSDT"
    assert session["interval"] == "1h"
    assert session["strategy_capital"] == 123.45
    assert session["entry_time_ms"] == 1_700_000_000_000

    database.deactivate_live_session()
    assert database.load_live_session()["active"] == 0


def test_offline_session_pnl_is_claimed_once(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.sync_user_trades([
        {
            "id": 1, "orderId": 10, "symbol": "BTCUSDT", "side": "BUY",
            "positionSide": "BOTH", "price": "60000", "qty": "0.01",
            "commission": "0.30", "commissionAsset": "USDT",
            "realizedPnl": "0", "time": 1_700_000_000_000,
        },
        {
            "id": 2, "orderId": 11, "symbol": "BTCUSDT", "side": "SELL",
            "positionSide": "BOTH", "price": "61000", "qty": "0.01",
            "commission": "0.31", "commissionAsset": "USDT",
            "realizedPnl": "10", "time": 1_700_000_060_000,
        },
    ])

    assert database.claim_unapplied_session_pnl(
        "BTCUSDT", "2023-11-14T00:00:00+00:00") == (9.39, 1)
    assert database.claim_unapplied_session_pnl(
        "BTCUSDT", "2023-11-14T00:00:00+00:00") == (0, 0)


def test_open_order_snapshot_removes_stale_local_orders(tmp_path):
    database = TradingDatabase(str(tmp_path / "trading.sqlite3"))
    database.upsert_order(_order("NEW", orderId="1"))
    database.upsert_order(_order("NEW", orderId="2"))

    database.reconcile_open_orders("BTCUSDT", ["2"])

    assert [row["order_id"] for row in database.current_orders()] == ["2"]
    assert database.rows(
        "SELECT status FROM orders WHERE order_id='1'")[0]["status"] == "CANCELED"
