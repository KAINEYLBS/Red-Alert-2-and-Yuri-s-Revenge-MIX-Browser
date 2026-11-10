from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLocale, QLibraryInfo, QTranslator
from PySide6.QtWidgets import QApplication


SUPPORTED_UI_LANGUAGES = frozenset({"system", "en", "zh_CN"})


# @arch mix-browser.localization service | en: Loads application and Qt translations for the selected UI language | zh: 为所选界面语言加载应用与 Qt 翻译
def install_translations(application: QApplication, language: str) -> str:
    if language not in SUPPORTED_UI_LANGUAGES:
        language = "system"
    if language == "system":
        language = "zh_CN" if QLocale.system().name().startswith("zh") else "en"

    if language != "zh_CN":
        return language

    qt_translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    qt_translator = QTranslator(application)
    if qt_translator.load("qtbase_zh_CN.qm", qt_translations):
        application.installTranslator(qt_translator)

    app_catalog = Path(__file__).resolve().parents[1] / "translations"
    app_translator = QTranslator(application)
    if app_translator.load(str(app_catalog / "ra2ayrmb_zh_CN.qm")):
        application.installTranslator(app_translator)

    return language
