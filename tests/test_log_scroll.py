from app.ui.backtest_tab import BacktestTab


class FakeScrollBar:
    def __init__(self, value, maximum):
        self._value = value
        self._maximum = maximum

    def value(self):
        return self._value

    def maximum(self):
        return self._maximum

    def setValue(self, value):
        self._value = value


class FakeLogView:
    def __init__(self, value, maximum, new_maximum):
        self.scrollbar = FakeScrollBar(value, maximum)
        self.new_maximum = new_maximum
        self.text = ""

    def verticalScrollBar(self):
        return self.scrollbar

    def setPlainText(self, text):
        self.text = text
        self.scrollbar._maximum = self.new_maximum
        self.scrollbar._value = 0


def test_log_at_bottom_follows_new_bottom():
    view = FakeLogView(value=100, maximum=100, new_maximum=140)

    BacktestTab._set_log_text_preserving_scroll(view, "new log")

    assert view.scrollbar.value() == 140


def test_log_scrolled_up_keeps_position():
    view = FakeLogView(value=40, maximum=100, new_maximum=140)

    BacktestTab._set_log_text_preserving_scroll(view, "new log")

    assert view.scrollbar.value() == 40
