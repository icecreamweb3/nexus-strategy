from datetime import datetime, timezone

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
