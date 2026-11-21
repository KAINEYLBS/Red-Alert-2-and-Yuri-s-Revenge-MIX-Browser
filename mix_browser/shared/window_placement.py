from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget


# @arch mix-browser.window-placement utility | en: Positions a top-level window before display with room for native window borders | zh: 在窗口首次显示前定位，并为系统标题栏和边框留出空间
def center_window_on_available_screen(
    window: QWidget,
    anchor: QWidget | None = None,
    *,
    constrain_size: bool = False,
) -> None:
    anchor_center = anchor.frameGeometry().center() if anchor is not None else None
    screen = (
        QGuiApplication.screenAt(anchor_center)
        if anchor_center is not None
        else None
    )
    screen = screen or QGuiApplication.primaryScreen()
    if screen is None:
        return

    # Native frame margins are not reliable until a window is shown. Reserve
    # enough space here so the title bar remains visible without moving later.
    available = screen.availableGeometry().adjusted(32, 32, -32, -32)
    max_width = max(1, available.width())
    max_height = max(1, available.height())
    minimum = window.minimumSize()
    maximum = window.maximumSize()
    limited_width = min(maximum.width(), max_width)
    limited_height = min(maximum.height(), max_height)
    if constrain_size or window.width() > max_width or window.height() > max_height:
        window.setMinimumSize(
            min(minimum.width(), limited_width),
            min(minimum.height(), limited_height),
        )
        window.setMaximumSize(limited_width, limited_height)
        window.resize(
            min(window.width(), limited_width),
            min(window.height(), limited_height),
        )

    target = (
        anchor_center
        if anchor_center is not None and available.contains(anchor_center)
        else available.center()
    )
    x = min(
        max(target.x() - window.width() // 2, available.left()),
        available.right() - window.width() + 1,
    )
    y = min(
        max(target.y() - window.height() // 2, available.top()),
        available.bottom() - window.height() + 1,
    )
    window.move(x, y)
