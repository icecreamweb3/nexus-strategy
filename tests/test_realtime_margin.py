import csv
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.ui.realtime_tab as realtime_tab_module
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


def test_spot_balance_includes_free_and_locked_quote_asset():
    account = {"balances": [
        {"asset": "USDT", "free": "12.25", "locked": "0.75"},
        {"asset": "USDC", "free": "99", "locked": "1"},
    ]}

    assert RealtimeStrategyTab._spot_balance(
        account, "BTCUSDT") == ("USDT", 13.0)
    assert RealtimeStrategyTab._spot_balance(
        account, "BTCUSDC") == ("USDC", 100.0)


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


def test_utc_entry_time_is_mapped_without_timezone_offset():
    entry = datetime(2026, 9, 9, 5, 15, tzinfo=timezone.utc)
    klines = [
        SimpleNamespace(
            index=index,
            open_time=(datetime(2026, 9, 9, 5, 7 + index - 1,
                                tzinfo=timezone.utc)
                       .isoformat(timespec="seconds")),
        )
        for index in range(1, 10)
    ]

    assert RealtimeStrategyTab._kline_index_for_time(
        klines, int(entry.timestamp() * 1000)) == 9


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


class _ComboStub:
    def __init__(self):
        self.value = ""

    def setCurrentText(self, value):
        self.value = value


def _resume_tab(session):
    calls = []
    database = SimpleNamespace(
        load_live_session=lambda: session,
        deactivate_live_session=lambda: calls.append("deactivate"),
    )
    tab = SimpleNamespace(
        _running=False,
        _db=database,
        cmb_symbol=_ComboStub(),
        cmb_interval=_ComboStub(),
        _start_live=lambda value: calls.append(("start", value)),
    )
    return tab, calls


def test_empty_position_waits_for_manual_start_on_app_launch(monkeypatch):
    session = {"active": 1, "symbol": "BTCUSDT", "interval": "1h"}
    tab, calls = _resume_tab(session)
    client = SimpleNamespace(has_open_position=lambda _symbol: False)
    monkeypatch.setattr(
        realtime_tab_module, "load_config",
        lambda: SimpleNamespace(has_credentials=True))
    monkeypatch.setattr(
        realtime_tab_module, "BinanceLiveGateway",
        lambda _config: SimpleNamespace(client=client))

    RealtimeStrategyTab._resume_live_session(tab)

    assert calls == ["deactivate"]
    assert tab.cmb_symbol.value == "BTCUSDT"
    assert tab.cmb_interval.value == "1h"


def test_existing_position_still_resumes_on_app_launch(monkeypatch):
    session = {"active": 1, "symbol": "BTCUSDT", "interval": "1h"}
    tab, calls = _resume_tab(session)
    client = SimpleNamespace(has_open_position=lambda _symbol: True)
    monkeypatch.setattr(
        realtime_tab_module, "load_config",
        lambda: SimpleNamespace(has_credentials=True))
    monkeypatch.setattr(
        realtime_tab_module, "BinanceLiveGateway",
        lambda _config: SimpleNamespace(client=client))

    RealtimeStrategyTab._resume_live_session(tab)

    assert calls == [("start", session)]


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


def test_algo_stop_actual_market_order_keeps_sl_classification():
    tab = SimpleNamespace(_protection_actions_by_order_id={})

    algo = RealtimeStrategyTab._classify_protection_execution(tab, {
        "i": "900", "ai": "901", "x": "ALGO_UPDATE",
        "o": "STOP_MARKET", "X": "FINISHED",
    })
    actual = RealtimeStrategyTab._classify_protection_execution(tab, {
        "i": "901", "x": "TRADE", "o": "MARKET", "X": "FILLED",
    })

    assert algo["action_type"] == "SL"
    assert actual["action_type"] == "SL"
    assert actual["use_type"] == "SL_CLOSE"


def test_exit_event_time_matches_only_its_own_kline():
    previous = SimpleNamespace(index=40, open_time=0)
    current = SimpleNamespace(index=41, open_time=60_000)
    tab = SimpleNamespace(
        _exit_event_times_ms={30_000, 90_000},
        _processor=SimpleNamespace(klines=[previous, current]),
    )

    assert RealtimeStrategyTab._consume_exit_for_kline(tab, current)
    assert tab._exit_event_times_ms == set()

    following = SimpleNamespace(index=42, open_time=120_000)
    tab._processor.klines.append(following)
    assert not RealtimeStrategyTab._consume_exit_for_kline(tab, following)


def test_closed_kline_skips_signal_when_order_event_is_late_but_position_is_flat():
    evaluated = []
    placed = []
    previous = SimpleNamespace(index=40, open_time=0)
    order = SimpleNamespace(
        exit_bar_signal_enabled=False, max_hold_klines=0)

    class Processor:
        def __init__(self):
            self.order = order
            self.klines = [previous]

        def add_closed_kline(self, kline, evaluate=False):
            kline.index = 41
            self.klines.append(kline)

        def evaluate_latest_closed(self):
            evaluated.append(True)
            return object()

    tab = SimpleNamespace(
        _running=True,
        _processor=Processor(),
        _gateway=SimpleNamespace(client=SimpleNamespace(
            has_open_position=lambda _symbol: False)),
        _entry_kline_index=41,
        _exit_since_last_closed_kline=False,
        _exit_event_times_ms=set(),
        cmb_symbol=SimpleNamespace(currentText=lambda: "BTCUSDT"),
        _close_on_time_limit=lambda _index: False,
        _consume_exit_for_kline=lambda _kline: False,
        _place_signal_order=placed.append,
    )
    kline = SimpleNamespace(
        index=0, open_time=60_000, close=100.0)

    RealtimeStrategyTab._on_closed_kline(tab, kline)

    assert evaluated == []
    assert placed == []


def test_zero_pnl_protection_exit_still_marks_exit_kline():
    canceled = []
    refreshed = []
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
        _refresh_balances=lambda **_kwargs: refreshed.append(True) or True,
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
    assert refreshed == [True]


def test_closed_position_uses_refreshed_account_total_without_adding_pnl():
    refreshed = []
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
        _refresh_balances=None,
        _persist_live_session=lambda: None,
        _record_log=lambda *_args: None,
        _sync_user_trades=lambda *_args, **_kwargs: None,
        _db=SimpleNamespace(
            claim_position_realized_pnl=lambda _ids: (12.5, 1)),
    )
    def refresh_balances(**_kwargs):
        refreshed.append(True)
        tab._strategy_capital = 250.0
        return True
    tab._refresh_balances = refresh_balances

    RealtimeStrategyTab._reconcile_strategy_capital(tab, "BTCUSDT")

    assert tab._strategy_capital == 250.0
    assert tab._pending_realized_pnl == 0
    assert tab._pending_close_order_ids == set()
    assert refreshed == [True]


def test_balance_is_futures_and_strategy_balance_is_spot_plus_futures():
    class ValueWidget:
        def __init__(self, value=0):
            self.current = value

        def setText(self, value):
            self.current = value

        def value(self):
            return self.current

        def setValue(self, value):
            self.current = value

    tab = SimpleNamespace(
        _strategy_capital=None,
        _strategy_capital_from_account=False,
        _strategy_capital_asset=None,
        lbl_balance_value=ValueWidget(),
        lbl_strategy_capital_value=ValueWidget(),
        lbl_spot_bnb_value=ValueWidget(),
        lbl_futures_bnb_value=ValueWidget(),
        sp_total_capital=ValueWidget(),
        _spot_balance=lambda _account, _symbol: ("USDT", 20.0),
        _wallet_balance=lambda _account, _symbol: ("USDT", 80.0),
        _spot_asset_total=RealtimeStrategyTab._spot_asset_total,
        _futures_asset_wallet_balance=(
            RealtimeStrategyTab._futures_asset_wallet_balance),
    )
    tab._update_strategy_capital_label = lambda: (
        RealtimeStrategyTab._update_strategy_capital_label(tab))
    client = SimpleNamespace(get_spot_account_info=lambda: {"balances": [
        {"asset": "BNB", "free": "1.25", "locked": "0.05"},
    ]})

    asset, futures_balance = RealtimeStrategyTab._refresh_balance_labels(
        tab, client, {"assets": [{
            "asset": "BNB", "walletBalance": "2.5",
        }]}, "BTCUSDT")

    assert (asset, futures_balance) == ("USDT", 80.0)
    assert tab.lbl_balance_value.current == "80.00 USDT"
    assert tab.lbl_strategy_capital_value.current == "100.00 USDT"
    assert tab.lbl_spot_bnb_value.current == "1.3000 BNB"
    assert tab.lbl_futures_bnb_value.current == "2.5000 BNB"
    assert tab._strategy_capital == 100.0


def test_balance_timer_refreshes_even_when_strategy_is_stopped():
    refreshed = []
    tab = SimpleNamespace(
        _running=False,
        _refresh_balances=lambda **kwargs: refreshed.append(kwargs),
    )

    RealtimeStrategyTab._auto_refresh_account(tab)

    assert refreshed == [{"show_errors": False}]


def test_running_balance_timer_does_not_trigger_full_account_sync():
    calls = []
    tab = SimpleNamespace(
        _running=True,
        _refresh_balances=lambda **kwargs: calls.append(
            ("balances", kwargs)),
        _refresh_account=lambda **kwargs: calls.append(("account", kwargs)),
        _reconcile_strategy_capital=lambda symbol: calls.append(
            ("reconcile", symbol)),
        cmb_symbol=SimpleNamespace(
            currentText=lambda: "BTCUSDT"),
    )

    RealtimeStrategyTab._auto_refresh_account(tab)

    assert calls == [
        ("balances", {"show_errors": False}),
        ("reconcile", "BTCUSDT"),
    ]


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
