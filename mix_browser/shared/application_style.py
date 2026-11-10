from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QToolButton


BROWSER_TOOLBAR_CONTROL_HEIGHT = 28


# @arch mix-browser.application-visual-style utility | en: Applies shared application-wide control and section hierarchy styles | zh: 应用统一的控件样式与分组层级
def apply_application_style(application: QApplication) -> None:
    """Apply application-wide button and section hierarchy styles."""
    palette = application.palette()
    button_background = palette.color(QPalette.ColorRole.Button).name()
    button_text = palette.color(QPalette.ColorRole.ButtonText).name()
    normal_border = palette.color(QPalette.ColorRole.Mid).name()
    hover_background = palette.color(QPalette.ColorRole.Midlight).name()
    active_border = palette.color(QPalette.ColorRole.Highlight).name()
    active_text = palette.color(QPalette.ColorRole.HighlightedText).name()
    pressed_background = palette.color(QPalette.ColorRole.Dark).name()
    disabled_background = palette.color(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Button,
    ).name()
    disabled_text = palette.color(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
    ).name()
    disabled_border = palette.color(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Mid,
    ).name()
    description_text = palette.color(QPalette.ColorRole.PlaceholderText).name()
    application.setStyleSheet(
        f"""
        QPushButton, QToolButton {{
            color: {button_text};
            background-color: {button_background};
            border: 1px solid {normal_border};
            border-radius: 4px;
            padding: 4px 9px;
        }}
        QToolButton {{
            padding: 3px 6px;
        }}
        QToolButton[menuButton="true"] {{
            padding: 3px 18px 3px 6px;
        }}
        QPushButton:hover, QToolButton:hover,
        QPushButton:focus, QToolButton:focus {{
            background-color: {hover_background};
            border-color: {active_border};
        }}
        QPushButton:pressed, QToolButton:pressed {{
            background-color: {pressed_background};
            border-color: {active_border};
        }}
        QPushButton:default {{
            border: 2px solid {active_border};
        }}
        QPushButton:disabled, QToolButton:disabled {{
            color: {disabled_text};
            background-color: {disabled_background};
            border-color: {disabled_border};
        }}
        QToolButton#BreadcrumbButton {{
            background-color: transparent;
            border-color: transparent;
            border-bottom-color: {normal_border};
            border-radius: 0px;
            padding: 3px 6px;
        }}
        QToolButton#BreadcrumbButton:hover,
        QToolButton#BreadcrumbButton:focus,
        QToolButton#BreadcrumbButton:pressed {{
            background-color: {hover_background};
            border-color: {active_border};
        }}
        QGroupBox {{
            font-weight: normal;
            border: 1px solid {normal_border};
            border-radius: 4px;
            margin-top: 12px;
            padding: 12px 10px 10px 10px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 8px;
            padding: 0px 4px;
            font-weight: 600;
        }}
        QLabel[visualRole="description"] {{
            color: {description_text};
        }}
        """
    )


# @arch mix-browser.mark-menu-tool-button utility | en: Marks a tool button for the shared application menu-button spacing rule | zh: 标记工具按钮以应用全局菜单按钮间距规则
def mark_menu_tool_button(button: QToolButton) -> None:
    button.setProperty("menuButton", True)
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.updateGeometry()
