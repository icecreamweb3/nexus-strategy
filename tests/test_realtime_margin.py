from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ui.realtime_tab import RealtimeStrategyTab


def test_single_asset_balance_matches_selected_symbol_quote():
    account = {
        "multiAssetsMargin": False,
        "availableBalance": "65",
        "assets": [
            {"asset": "USDT", "availableBalance": "0"},
            {"asset": "USDC", "availableBalance": "65.5"},
        ],
    }

    assert RealtimeStrategyTab._available_margin_balance(
        account, "BTCUSDT") == ("USDT", 0.0)
    assert RealtimeStrategyTab._available_margin_balance(
        account, "BTCUSDC") == ("USDC", 65.5)


def test_multi_asset_balance_uses_account_available_balance():
    account = {
        "multiAssetsMargin": True,
        "availableBalance": "42.25",
        "assets": [{"asset": "USDT", "availableBalance": "0"}],
    }

    assert RealtimeStrategyTab._available_margin_balance(
        account, "BTCUSDT") == ("USDT", 42.25)


def test_displayed_account_balance_uses_wallet_balance():
    account = {
        "availableBalance": "42.25",
        "assets": [{
            "asset": "USDT", "availableBalance": "40",
            "walletBalance": "123.45",
        }],
    }

    assert RealtimeStrategyTab._wallet_balance(
        account, "BTCUSDT") == ("USDT", 123.45)


def test_live_price_calculates_long_unrealized_pnl():
    position = {
        "position_side": "LONG",
        "quantity": 0.001,
        "avg_entry_price": 77577.5,
    }

    pnl = RealtimeStrategyTab._calculate_unrealized_pnl(position, 77589.8)

    assert pnl == pytest.approx(0.0123)


def test_live_price_calculates_short_unrealized_pnl():
    position = {
        "position_side": "SHORT",
        "quantity": 0.02,
        "avg_entry_price": 2000,
    }

    pnl = RealtimeStrategyTab._calculate_unrealized_pnl(position, 1990)

    assert pnl == pytest.approx(0.2)


def test_order_time_is_displayed_in_system_local_timezone():
    utc_time = datetime(2026, 8, 29, 4, 31, 30, tzinfo=timezone.utc)
    expected = utc_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")

    assert RealtimeStrategyTab._format_local_time(
        "2026-08-29T04:31:30+00:00") == expected
    assert RealtimeStrategyTab._format_local_time(
        "2026-08-29 04:31:30") == expected
    assert RealtimeStrategyTab._format_local_time(
        1787977890000) == expected


def test_close_trade_event_detects_reduce_only_and_saved_tp():
    assert RealtimeStrategyTab._is_close_trade_event(
        {"x": "TRADE", "rp": "0"},
        {"reduce_only": 1, "action_type": "OPEN"},
    )
    assert RealtimeStrategyTab._is_close_trade_event(
        {"x": "TRADE", "rp": "0"},
        {"reduce_only": 0, "action_type": "TP"},
    )


def test_close_trade_event_ignores_opening_trade():
    assert not RealtimeStrategyTab._is_close_trade_event(
        {"x": "TRADE", "rp": "0"},
        {"reduce_only": 0, "action_type": "OPEN"},
    )


def test_zero_pnl_protection_exit_still_marks_exit_kline():
    canceled = []
    client = SimpleNamespace(
        has_open_position=lambda _symbol: False,
        cancel_all_open_orders=lambda symbol: canceled.append(symbol),
    )
    tab = SimpleNamespace(
        _pending_realized_pnl=0.0,
        _pending_close_order_ids={"42"},
        _pending_protection_exit=True,
        _exit_since_last_closed_kline=False,
        _strategy_capital=100.0,
        _gateway=SimpleNamespace(client=client),
        _entry_kline_index=4,
        _update_strategy_capital_label=lambda: None,
        _record_log=lambda *_args: None,
        _sync_user_trades=lambda *_args, **_kwargs: None,
        _db=SimpleNamespace(
            claim_position_realized_pnl=lambda _ids: (0.0, 1)),
    )

    RealtimeStrategyTab._reconcile_strategy_capital(tab, "BTCUSDT")

    assert tab._exit_since_last_closed_kline is True
    assert tab._pending_protection_exit is False
    assert tab._entry_kline_index is None
    assert canceled == ["BTCUSDT"]


def test_strategy_capital_uses_claimed_position_history_pnl():
    client = SimpleNamespace(
        has_open_position=lambda _symbol: False,
        cancel_all_open_orders=lambda _symbol: None,
    )
    tab = SimpleNamespace(
        _pending_realized_pnl=999.0,
        _pending_close_order_ids={"42"},
        _pending_protection_exit=False,
        _exit_since_last_closed_kline=False,
        _strategy_capital=100.0,
        _gateway=SimpleNamespace(client=client),
        _entry_kline_index=4,
        _update_strategy_capital_label=lambda: None,
        _record_log=lambda *_args: None,
        _sync_user_trades=lambda *_args, **_kwargs: None,
        _db=SimpleNamespace(
            claim_position_realized_pnl=lambda _ids: (12.5, 1)),
    )

    RealtimeStrategyTab._reconcile_strategy_capital(tab, "BTCUSDT")

    assert tab._strategy_capital == 112.5
    assert tab._pending_realized_pnl == 0
    assert tab._pending_close_order_ids == set()


def test_algo_order_is_normalized_for_the_shared_order_table():
    normalized = RealtimeStrategyTab._normalize_algo_order({
        "algoId": 88,
        "clientAlgoId": "sl-88",
        "symbol": "BTCUSDT",
        "side": "SELL",
        "positionSide": "BOTH",
        "orderType": "STOP_MARKET",
        "algoStatus": "NEW",
        "triggerPrice": "59000",
        "quantity": "0.01",
        "closePosition": True,
        "createTime": 1000,
    })

    assert normalized["orderId"] == "algo:88"
    assert normalized["type"] == "STOP_MARKET"
    assert normalized["status"] == "NEW"
    assert normalized["stopPrice"] == "59000"
    assert normalized["reduceOnly"] is True
