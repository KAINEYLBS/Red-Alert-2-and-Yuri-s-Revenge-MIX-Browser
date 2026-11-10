from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QStyledItemDelegate, QTableView


# @arch mix-browser.rounded-row-delegate component | en: Paints shared rounded row states and tracks table hover | zh: 绘制统一的圆角行状态并跟踪表格悬停
class RoundedRowDelegate(QStyledItemDelegate):
    def __init__(self, view: QTableView) -> None:
        super().__init__(view)
        self._view: QTableView | None = view
        self._viewport = view.viewport()
        self._hovered_row = -1
        self._viewport.setMouseTracking(True)
        self._viewport.installEventFilter(self)
        view.destroyed.connect(self._on_view_destroyed)

    def set_hovered_row(self, row: int) -> None:
        if row == self._hovered_row:
            return
        self._hovered_row = row
        if self._viewport is not None:
            try:
                self._viewport.update()
            except RuntimeError:
                pass

    def _on_view_destroyed(self, _object=None) -> None:
        self._view = None
        self._viewport = None

    def eventFilter(self, watched, event) -> bool:
        view = self._view
        if view is None:
            return False
        if watched is self._viewport:
            if event.type() == QEvent.Type.MouseMove:
                try:
                    index = view.indexAt(event.position().toPoint())
                except RuntimeError:
                    return False
                self.set_hovered_row(index.row() if index.isValid() else -1)
            elif event.type() == QEvent.Type.Leave:
                self.set_hovered_row(-1)
        return super().eventFilter(watched, event)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        view = self._view
        if view is None or not index.isValid():
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(option.rect)

        palette = option.palette
        background_role = (
            QPalette.ColorRole.AlternateBase
            if view.alternatingRowColors() and index.row() % 2
            else QPalette.ColorRole.Base
        )
        painter.fillRect(option.rect, palette.color(background_role))

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == self._hovered_row
        if selected or hovered:
            highlight = palette.color(QPalette.ColorRole.Highlight)
            fill = QColor(highlight)
            border = QColor(highlight)
            if selected:
                fill.setAlpha(224)
                border = highlight.lighter(135)
            else:
                fill.setAlpha(28)
                border.setAlpha(112)

            row_rect = QRect(
                view.viewport().rect().left() + 4,
                option.rect.top() + 2,
                view.viewport().width() - 8,
                option.rect.height() - 4,
            )
            painter.setPen(QPen(border, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(row_rect, 5, 5)

        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text is not None:
            text_color = palette.color(
                QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
            )
            painter.setPen(text_color)
            painter.setFont(option.font)
            alignment = index.data(Qt.ItemDataRole.TextAlignmentRole)
            if alignment is None:
                alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            text_rect = option.rect.adjusted(8, 0, -8, 0)
            decoration = index.data(Qt.ItemDataRole.DecorationRole)
            if isinstance(decoration, QIcon) and not decoration.isNull():
                icon_size = view.iconSize()
                if icon_size.width() > 0 and icon_size.height() > 0:
                    icon_rect = QRect(
                        text_rect.left(),
                        option.rect.center().y() - icon_size.height() // 2,
                        icon_size.width(),
                        icon_size.height(),
                    )
                    decoration.paint(painter, icon_rect)
                    text_rect.adjust(icon_size.width() + 6, 0, 0, 0)
            painter.drawText(text_rect, alignment, str(text))

        painter.restore()
