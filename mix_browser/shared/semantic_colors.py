from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget


_MIN_TEXT_CONTRAST = 4.5
_STATUS_COLORS = {
    "success": "#1a7f37",
    "info": "#0969da",
    "pending": "#0969da",
    "warning": "#b45309",
    "error": "#cf222e",
}


def _relative_luminance(color: QColor) -> float:
    def linear_component(value: int) -> float:
        normalized = value / 255
        return (
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )

    return (
        0.2126 * linear_component(color.red())
        + 0.7152 * linear_component(color.green())
        + 0.0722 * linear_component(color.blue())
    )


def _contrast_ratio(first: QColor, second: QColor) -> float:
    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _composite_color(foreground: QColor, background: QColor) -> QColor:
    alpha = foreground.alpha() / 255
    return QColor(
        round(foreground.red() * alpha + background.red() * (1 - alpha)),
        round(foreground.green() * alpha + background.green() * (1 - alpha)),
        round(foreground.blue() * alpha + background.blue() * (1 - alpha)),
    )


@lru_cache(maxsize=4096)
def _contrast_adjusted_rgba(foreground_rgba: int, background_rgb: int) -> int:
    foreground = QColor.fromRgba(foreground_rgba)
    background = QColor.fromRgb(background_rgb)
    visible_foreground = _composite_color(foreground, background)
    if _contrast_ratio(visible_foreground, background) >= _MIN_TEXT_CONTRAST:
        return foreground_rgba

    hue, saturation, lightness, alpha = foreground.getHsl()
    best_color = foreground
    best_ratio = _contrast_ratio(visible_foreground, background)
    best_distance = 256
    for candidate_lightness in range(256):
        candidate = QColor.fromHsl(hue, saturation, candidate_lightness, alpha)
        visible_candidate = _composite_color(candidate, background)
        ratio = _contrast_ratio(visible_candidate, background)
        distance = abs(candidate_lightness - lightness)
        if ratio >= _MIN_TEXT_CONTRAST and distance < best_distance:
            best_color = candidate
            best_distance = distance
        elif best_distance == 256 and ratio > best_ratio:
            best_color = candidate
            best_ratio = ratio
    return best_color.rgba()


def color_with_text_contrast(foreground: QColor, background: QColor) -> QColor:
    return QColor.fromRgba(
        _contrast_adjusted_rgba(foreground.rgba(), background.rgb())
    )


def base_status_color(role: str) -> QColor:
    return QColor(_STATUS_COLORS[role])


# @arch mix-browser.semantic-status-color utility | en: Applies theme-aware semantic status text colors while preserving their meaning | zh: 应用随主题背景调整的语义状态文字颜色并保留状态含义
def set_semantic_status_style(
    widget: QWidget,
    role: str,
    *,
    bold: bool = False,
    background_role: QPalette.ColorRole = QPalette.ColorRole.Window,
) -> None:
    widget.setProperty("_semanticStatusRole", role)
    widget.setProperty("_semanticStatusBold", bold)
    widget.setProperty("_semanticStatusBackgroundRole", background_role.value)
    refresh_semantic_status_style(widget)


def refresh_semantic_status_style(widget: QWidget) -> None:
    role = widget.property("_semanticStatusRole")
    if not role:
        return
    try:
        background_role = QPalette.ColorRole(
            widget.property("_semanticStatusBackgroundRole")
        )
    except (TypeError, ValueError):
        background_role = QPalette.ColorRole.Window
    background = widget.palette().color(background_role)
    foreground = (
        widget.palette().color(QPalette.ColorRole.WindowText)
        if role == "neutral"
        else base_status_color(str(role))
    )
    color = color_with_text_contrast(foreground, background)
    weight = "600" if widget.property("_semanticStatusBold") else "normal"
    style = (
        f"font-weight: {weight};"
        if role == "neutral"
        else f"color: {color.name()}; font-weight: {weight};"
    )
    if widget.styleSheet() != style:
        widget.setStyleSheet(style)
