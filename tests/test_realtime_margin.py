import csv
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


def test_entry_time_is_mapped_back_to_reloaded_kline_index():
    klines = [
        SimpleNamespace(index=1, open_time=1_000),
        SimpleNamespace(index=2, open_time=2_000),
        SimpleNamespace(index=3, open_time=3_000),
    ]

    assert RealtimeStrategyTab._kline_index_for_time(klines, 2_000) == 2
    assert RealtimeStrategyTab._kline_index_for_time(klines, 3_500) == 4
    assert RealtimeStrategyTab._kline_index_for_time(klines, 0) == 0


def test_window_close_preserves_active_live_session():
    calls = []
    price_stream = SimpleNamespace(stop=lambda: calls.append("price-stop"))
    tab = SimpleNamespace(
        _price_stream=price_stream,
        _save_current_settings=lambda: calls.append("settings-save"),
        _persist_live_session=lambda: calls.append("session-save"),
        stop_live=lambda preserve_session=False: calls.append(
            ("live-stop", preserve_session)),
    )

    RealtimeStrategyTab.close_listener(tab)

    assert calls == [
        "settings-save", "session-save", "price-stop", ("live-stop", True),
    ]
    assert tab._price_stream is None


def test_empty_position_evaluates_signal_after_preload():
    signal = object()
    placed = []
    tab = SimpleNamespace(
        _processor=SimpleNamespace(evaluate_latest_closed=lambda: signal),
        _place_signal_order=placed.append,
    )

    RealtimeStrategyTab._evaluate_initial_signal_when_flat(tab, False)

    assert placed == [signal]


def test_existing_position_skips_initial_signal_after_preload():
    evaluated = []
    tab = SimpleNamespace(
        _processor=SimpleNamespace(
            evaluate_latest_closed=lambda: evaluated.append(True)),
        _place_signal_order=lambda _signal: None,
    )

    RealtimeStrategyTab._evaluate_initial_signal_when_flat(tab, True)

    assert evaluated == []


def test_startup_displays_active_session_strategy_capital():
    session = {"active": 1, "strategy_capital": 11234.56}

    value = RealtimeStrategyTab._initial_strategy_capital(session, 10000)

    assert value == 11234.56


def test_startup_displays_configured_capital_without_active_session():
    inactive_session = {"active": 0, "strategy_capital": 11234.56}

    assert RealtimeStrategyTab._initial_strategy_capital(
        inactive_session, 10000) == 10000
    assert RealtimeStrategyTab._initial_strategy_capital(None, 8000) == 8000


def test_existing_position_skips_all_position_mode_changes():
    calls = []
    client = SimpleNamespace(
        get_position_mode=lambda: calls.append("get-position-mode"),
        set_position_mode=lambda _mode: calls.append("set-position-mode"),
        get_multi_assets_mode=lambda: calls.append("get-assets-mode"),
        set_multi_assets_mode=lambda _mode: calls.append("set-assets-mode"),
        set_cross_margin=lambda _symbol: calls.append("set-cross-margin"),
        set_leverage=lambda symbol, leverage: calls.append(
            ("set-leverage", symbol, leverage)) or True,
    )

    RealtimeStrategyTab._configure_exchange_settings(
        client, "BTCUSDT", has_account_position=True,
        has_symbol_position=True)

    assert calls == [("set-leverage", "BTCUSDT", 100)]


def test_other_symbol_position_only_skips_account_level_mode_changes():
    calls = []
    client = SimpleNamespace(
        get_position_mode=lambda: calls.append("get-position-mode"),
        set_position_mode=lambda _mode: calls.append("set-position-mode"),
        get_multi_assets_mode=lambda: calls.append("get-assets-mode"),
        set_multi_assets_mode=lambda _mode: calls.append("set-assets-mode"),
        set_cross_margin=lambda symbol: calls.append(
            ("set-cross-margin", symbol)) or True,
        set_leverage=lambda symbol, leverage: calls.append(
            ("set-leverage", symbol, leverage)) or True,
    )

    RealtimeStrategyTab._configure_exchange_settings(
        client, "BTCUSDT", has_account_position=True,
        has_symbol_position=False)

    assert calls == [
        ("set-cross-margin", "BTCUSDT"),
        ("set-leverage", "BTCUSDT", 100),
    ]


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
        _persist_live_session=lambda: None,
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
        _persist_live_session=lambda: None,
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


def test_position_history_csv_exports_every_database_row(tmp_path, monkeypatch):
    output = tmp_path / "position_history.csv"
    rows = [{
        "symbol": "BTCUSDT", "side": "LONG",
        "entry_price": 60000 + index, "close_price": 61000 + index,
        "quantity": 0.01, "realized_pnl": 10.0,
        "commission": 0.0002, "commission_asset": "BNB",
        "commission_value": 0.12, "position_mode": "ONE_WAY",
        "updated_at": f"2026-09-08T00:00:{index:02d}+00:00",
    } for index in range(12)]
    messages = []
    tab = SimpleNamespace(
        _db=SimpleNamespace(all_position_history=lambda: rows),
        _format_local_time=lambda value: value,
    )
    monkeypatch.setattr(
        "app.ui.realtime_tab.QFileDialog.getSaveFileName",
        lambda *_args: (str(output), "CSV (*.csv)"))
    monkeypatch.setattr(
        "app.ui.realtime_tab.QMessageBox.information",
        lambda *_args: messages.append(_args[-1]))

    RealtimeStrategyTab._export_position_history(tab)

    with output.open(encoding="utf-8-sig", newline="") as file:
        exported = list(csv.reader(file))
    assert len(exported) == 13
    assert exported[1][0:2] == ["BTCUSDT", "LONG"]
    assert float(exported[1][9]) == pytest.approx(9.88)
    assert "12" in messages[0]
