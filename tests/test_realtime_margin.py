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
