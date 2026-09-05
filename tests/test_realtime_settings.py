from types import SimpleNamespace

from app.backtest.engine import OrderParams, StrategyParams
from app.backtest.params_io import load_market_params, load_params
from app.ui.realtime_tab import RealtimeStrategyTab


class FakeCombo:
    def __init__(self, value=""):
        self.value = value

    def currentText(self):
        return self.value

    def setCurrentText(self, value):
        self.value = value


def test_realtime_settings_save_strategy_order_and_market(tmp_path):
    path = tmp_path / "defaults.inf"
    tab = SimpleNamespace(
        _collect_params=lambda: (
            StrategyParams(volume_enabled=False),
            OrderParams(total_capital=1234, exit_bar_signal_enabled=False),
        ),
        _default_params_path=lambda: str(path),
        cmb_symbol=FakeCombo("ethusdt"),
        cmb_interval=FakeCombo("4h"),
    )

    RealtimeStrategyTab._save_current_settings(tab)

    strategy, order = load_params(str(path))
    assert strategy.volume_enabled is False
    assert order.total_capital == 1234
    assert order.exit_bar_signal_enabled is False
    assert load_market_params(str(path)) == {
        "symbol": "ETHUSDT", "interval": "4h"}


def test_realtime_market_settings_are_restored(tmp_path):
    path = tmp_path / "defaults.inf"
    source = SimpleNamespace(
        _collect_params=lambda: (StrategyParams(), OrderParams()),
        _default_params_path=lambda: str(path),
        cmb_symbol=FakeCombo("BTCUSDT"),
        cmb_interval=FakeCombo("1h"),
    )
    RealtimeStrategyTab._save_current_settings(source)
    source.cmb_symbol.value = "SOLUSDT"
    source.cmb_interval.value = "8h"
    RealtimeStrategyTab._save_current_settings(source)

    target = SimpleNamespace(
        _default_params_path=lambda: str(path),
        cmb_symbol=FakeCombo(),
        cmb_interval=FakeCombo(),
    )
    RealtimeStrategyTab._restore_market_settings(target)

    assert target.cmb_symbol.currentText() == "SOLUSDT"
    assert target.cmb_interval.currentText() == "8h"
