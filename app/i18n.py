"""中英文国际化 / Chinese-English i18n with runtime switching."""
import json
import os

from PyQt5.QtCore import QObject, pyqtSignal

LANG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang")
ZH = "zh_CN"
EN = "en_US"


class I18n(QObject):
    language_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._lang = ZH
        self._catalogs = {}
        for code in (ZH, EN):
            path = os.path.join(LANG_DIR, code + ".json")
            with open(path, encoding="utf-8") as f:
                self._catalogs[code] = json.load(f)

    @property
    def lang(self) -> str:
        return self._lang

    def set_language(self, code: str):
        if code in self._catalogs and code != self._lang:
            self._lang = code
            self.language_changed.emit(code)

    def tr(self, key: str, **kwargs) -> str:
        return self.tr_for(self._lang, key, **kwargs)

    def tr_for(self, code: str, key: str, **kwargs) -> str:
        """使用指定语言翻译，不改变当前界面语言。"""
        text = self._catalogs.get(code, {}).get(key)
        if text is None:
            text = self._catalogs.get(ZH, {}).get(key, key)
        return text.format(**kwargs) if kwargs else text


_i18n = I18n()


def i18n() -> I18n:
    return _i18n


def tr(key: str, **kwargs) -> str:
    return _i18n.tr(key, **kwargs)
