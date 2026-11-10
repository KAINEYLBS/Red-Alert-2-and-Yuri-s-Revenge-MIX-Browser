from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings

from mix_browser.shared.application_identity import APPLICATION_DISPLAY_NAME


# @arch mix-browser.program-directory utility | en: Resolves the directory that owns portable application data | zh: 解析便携式应用数据所属的程序目录
def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    entrypoint = Path(sys.argv[0] if sys.argv else __file__).expanduser()
    if not entrypoint.is_absolute():
        entrypoint = Path.cwd() / entrypoint
    entrypoint = entrypoint.resolve()
    if (
        entrypoint.name == "application.py"
        and entrypoint.parent.name == "app"
        and entrypoint.parent.parent.name == "mix_browser"
    ):
        return entrypoint.parents[2]
    return entrypoint.parent


# @arch mix-browser.application-settings adapter | en: Opens the INI settings file beside the application | zh: 打开与程序文件并存的 INI 设置文件
def create_application_settings() -> QSettings:
    path = application_directory() / f"{APPLICATION_DISPLAY_NAME}.ini"
    return QSettings(str(path), QSettings.Format.IniFormat)
