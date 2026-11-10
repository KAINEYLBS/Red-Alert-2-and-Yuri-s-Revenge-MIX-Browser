from __future__ import annotations

from PySide6.QtCore import QLocale


# @arch mix-browser.byte-size-format utility | en: Formats byte counts with readable IEC units | zh: 使用易读的 IEC 单位格式化字节数
def format_byte_size(size: int) -> str:
    return QLocale.c().formattedDataSize(
        size,
        1,
        QLocale.DataSizeFormat.DataSizeIecFormat,
    )
