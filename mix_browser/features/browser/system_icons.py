from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QStyle


# @arch mix-browser.system-file-icon utility | en: Returns standard file and folder icons from the active system style | zh: 返回当前系统样式提供的标准文件与文件夹图标
def system_icon_for_object(*, is_directory: bool) -> QIcon:
    return _standard_icon(is_directory)


@lru_cache(maxsize=2)
def _standard_icon(is_directory: bool) -> QIcon:
    application = QApplication.instance()
    if application is None:
        return QIcon()
    pixmap = (
        QStyle.StandardPixmap.SP_DirIcon
        if is_directory
        else QStyle.StandardPixmap.SP_FileIcon
    )
    return application.style().standardIcon(pixmap)
