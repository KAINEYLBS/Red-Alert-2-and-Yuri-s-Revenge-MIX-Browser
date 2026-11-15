from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings

from mix_browser.shared.application_identity import APPLICATION_DISPLAY_NAME


# @arch mix-browser.program-directory utility | en: Resolves the directory containing the application executable or source entry point | zh: 解析应用程序或源码入口所在目录
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
    if entrypoint.parent.name == "mix_browser":
        return entrypoint.parent.parent
    if (
        entrypoint.parent.name.casefold() == "scripts"
        and entrypoint.parent.parent.name.casefold() in {".venv", "venv"}
    ):
        return entrypoint.parents[2]
    return entrypoint.parent


# @arch mix-browser.user-data-directory utility | en: Resolves the portable folder containing user-specific application data | zh: 解析存放用户专属应用数据的便携式文件夹
def user_data_directory() -> Path:
    return application_directory() / "user-data"


# @arch mix-browser.application-settings adapter | en: Opens the INI settings file inside the portable user-data folder | zh: 打开便携式用户资料文件夹内的 INI 首选项
def create_application_settings() -> QSettings:
    profile_directory = user_data_directory()
    profile_directory.mkdir(parents=True, exist_ok=True)
    path = profile_directory / f"{APPLICATION_DISPLAY_NAME}.ini"
    return QSettings(str(path), QSettings.Format.IniFormat)
