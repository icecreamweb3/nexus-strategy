"""主窗口 / Main window: Tab + 语言切换菜单."""
from PyQt5.QtWidgets import QAction, QMainWindow, QTabWidget

from app.i18n import EN, ZH, i18n, tr
from app.ui.backtest_tab import BacktestTab
from app.ui.live_tab import LiveTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1280, 860)

        self.tabs = QTabWidget()
        self.backtest_tab = BacktestTab()
        self.live_tab = LiveTab()
        self.tabs.addTab(self.backtest_tab, "")
        self.tabs.addTab(self.live_tab, "")
        self.setCentralWidget(self.tabs)

        self.menu_lang = self.menuBar().addMenu("")
        self.action_zh = QAction(self)
        self.action_zh.triggered.connect(lambda: self._switch_language(ZH))
        self.action_en = QAction(self)
        self.action_en.triggered.connect(lambda: self._switch_language(EN))
        self.menu_lang.addAction(self.action_zh)
        self.menu_lang.addAction(self.action_en)

        i18n().language_changed.connect(self.retranslate)
        self.retranslate()

    def _switch_language(self, code: str):
        i18n().set_language(code)

    def retranslate(self, *_args):
        self.setWindowTitle(tr("app_title"))
        self.tabs.setTabText(0, tr("tab_backtest"))
        self.tabs.setTabText(1, tr("tab_live"))
        self.menu_lang.setTitle(tr("menu_language"))
        self.action_zh.setText(tr("lang_zh"))
        self.action_en.setText(tr("lang_en"))
        self.backtest_tab.retranslate()
        self.live_tab.retranslate()
        self.statusBar().showMessage(tr("version_info"))

    def closeEvent(self, event):
        self.live_tab.close_listener()
        super().closeEvent(event)
