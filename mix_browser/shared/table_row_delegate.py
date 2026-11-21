from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QRect, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QStyle,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
)
from mix_browser.shared.semantic_colors import color_with_text_contrast


# @arch mix-browser.application-table-row-delegate component | en: Paints unified table row states and adjusts item colors to maintain readable contrast | zh: 绘制统一的表格行状态，并调整项颜色以保持可读对比度
class ApplicationTableRowDelegate(QStyledItemDelegate):
    def __init__(self, view: QAbstractItemView) -> None:
        super().__init__(view)
        self._view: QAbstractItemView | None = view
        self._viewport = view.viewport()
        self._hovered_row = -1
        self._visible_row_parities: tuple[int, ...] | None = None
        self._viewport.setMouseTracking(True)
        self._viewport.installEventFilter(self)
        view.destroyed.connect(self._on_view_destroyed)
        if isinstance(view, QTableView):
            header = view.verticalHeader()
            header.geometriesChanged.connect(self.invalidate_visible_rows)
            header.sectionResized.connect(self.invalidate_visible_rows)
            header.sectionCountChanged.connect(self.invalidate_visible_rows)
            header.sectionMoved.connect(self.invalidate_visible_rows)
        model = view.model()
        if model is not None:
            for signal in (
                model.modelReset,
                model.rowsInserted,
                model.rowsRemoved,
                model.rowsMoved,
                model.layoutChanged,
            ):
                signal.connect(self.invalidate_visible_rows)

    def eventFilter(self, watched, event) -> bool:
        view = self._view
        if view is None:
            return False
        if watched is self._viewport:
            if event.type() == QEvent.Type.MouseMove and isinstance(
                event, QMouseEvent
            ):
                try:
                    index = view.indexAt(event.position().toPoint())
                except RuntimeError:
                    return False
                self.set_hovered_row(index.row() if index.isValid() else -1)
            elif event.type() == QEvent.Type.Leave:
                self.set_hovered_row(-1)
        return super().eventFilter(watched, event)

    def set_hovered_row(self, row: int) -> None:
        if row == self._hovered_row:
            return
        self._hovered_row = row
        if self._viewport is not None:
            try:
                self._viewport.update()
            except RuntimeError:
                pass

    def invalidate_visible_rows(self, *_args) -> None:
        self._visible_row_parities = None

    def _visible_row_parity(self, row: int) -> int:
        view = self._view
        if not isinstance(view, QTableView):
            return row % 2
        model = view.model()
        if model is None:
            return row % 2

        row_count = model.rowCount()
        parities = self._visible_row_parities
        if parities is None or len(parities) != row_count:
            next_parity = 0
            values = []
            for model_row in range(row_count):
                if view.isRowHidden(model_row):
                    values.append(-1)
                    continue
                values.append(next_parity)
                next_parity ^= 1
            parities = tuple(values)
            self._visible_row_parities = parities
        if 0 <= row < len(parities) and parities[row] >= 0:
            return parities[row]
        return row % 2

    @staticmethod
    def _selected_row_background(palette: QPalette) -> QColor:
        base = palette.color(QPalette.ColorRole.Base)
        highlight = palette.color(QPalette.ColorRole.Highlight)
        return ApplicationTableRowDelegate._blend_colors(base, highlight, 38)

    @staticmethod
    def _blend_colors(background: QColor, foreground: QColor, alpha: int) -> QColor:
        ratio = alpha / 255
        return QColor(
            round(background.red() * (1 - ratio) + foreground.red() * ratio),
            round(background.green() * (1 - ratio) + foreground.green() * ratio),
            round(background.blue() * (1 - ratio) + foreground.blue() * ratio),
        )

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        view = self._view
        if view is None or not index.isValid():
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(option.rect)

        background = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(background, QColor):
            painter.fillRect(option.rect, background)
        elif background is not None:
            painter.fillRect(option.rect, background)
        else:
            background_role = (
                QPalette.ColorRole.AlternateBase
                if view.alternatingRowColors()
                and self._visible_row_parity(index.row())
                else QPalette.ColorRole.Base
            )
            painter.fillRect(option.rect, option.palette.color(background_role))

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == self._hovered_row
        if selected or hovered:
            highlight = option.palette.color(QPalette.ColorRole.Highlight)
            border = QColor(highlight)
            if selected:
                fill = self._selected_row_background(option.palette)
            else:
                fill = QColor(highlight)
                fill.setAlpha(20)
                border.setAlpha(112)

            row_rect = QRect(
                view.viewport().rect().left() + 4,
                option.rect.top() + 2,
                max(0, view.viewport().width() - 8),
                max(0, option.rect.height() - 4),
            )
            painter.setPen(QPen(border, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(row_rect, 5, 5)

        text = index.data(Qt.ItemDataRole.DisplayRole)
        text_rect = option.rect.adjusted(8, 0, -8, 0)
        if (
            index.flags() & Qt.ItemFlag.ItemIsUserCheckable
            and option.widget is not None
        ):
            self._paint_check_indicator(painter, option, index)
            style_option = QStyleOptionViewItem(option)
            self.initStyleOption(style_option, index)
            check_rect = option.widget.style().subElementRect(
                QStyle.SubElement.SE_ItemViewItemCheckIndicator,
                style_option,
                option.widget,
            )
            text_rect.setLeft(max(text_rect.left(), check_rect.right() + 6))

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

        if text is not None:
            foreground = index.data(Qt.ItemDataRole.ForegroundRole)
            if foreground is None:
                color_role = QPalette.ColorRole.Text
                painter.setPen(option.palette.color(color_role))
            elif isinstance(foreground, QColor):
                background_color = self._effective_text_background(
                    index,
                    option,
                    selected=selected,
                    hovered=hovered,
                )
                adjusted = color_with_text_contrast(foreground, background_color)
                painter.setPen(QPen(adjusted))
            elif (
                isinstance(foreground, QBrush)
                and foreground.style() == Qt.BrushStyle.SolidPattern
            ):
                background_color = self._effective_text_background(
                    index,
                    option,
                    selected=selected,
                    hovered=hovered,
                )
                adjusted = color_with_text_contrast(
                    foreground.color(),
                    background_color,
                )
                painter.setPen(QPen(adjusted))
            else:
                painter.setPen(QPen(foreground))
            font = index.data(Qt.ItemDataRole.FontRole)
            painter.setFont(font if font is not None else option.font)
            alignment = index.data(Qt.ItemDataRole.TextAlignmentRole)
            if alignment is None:
                alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(text_rect, alignment, str(text))

        painter.restore()

    def _effective_text_background(
        self,
        index: QModelIndex,
        option: QStyleOptionViewItem,
        *,
        selected: bool,
        hovered: bool,
    ) -> QColor:
        background = index.data(Qt.ItemDataRole.BackgroundRole)
        if isinstance(background, QColor):
            color = QColor(background)
        elif (
            isinstance(background, QBrush)
            and background.style() == Qt.BrushStyle.SolidPattern
        ):
            color = background.color()
        else:
            view = self._view
            role = (
                QPalette.ColorRole.AlternateBase
                if view is not None
                and view.alternatingRowColors()
                and self._visible_row_parity(index.row())
                else QPalette.ColorRole.Base
            )
            color = option.palette.color(role)

        if selected:
            return self._selected_row_background(option.palette)
        if hovered:
            highlight = option.palette.color(QPalette.ColorRole.Highlight)
            color = self._blend_colors(color, highlight, 20)
        return color

    def _paint_check_indicator(self, painter, option, index) -> None:
        widget = option.widget
        if widget is None:
            return
        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        check_rect = widget.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemCheckIndicator,
            style_option,
            widget,
        )
        check_option = QStyleOptionButton()
        check_option.rect = check_rect
        check_option.palette = style_option.palette
        check_option.state = QStyle.StateFlag.State_None
        if option.state & QStyle.StateFlag.State_Enabled:
            check_option.state |= QStyle.StateFlag.State_Enabled
        if option.state & QStyle.StateFlag.State_MouseOver:
            check_option.state |= QStyle.StateFlag.State_MouseOver
        raw_check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        try:
            check_state = Qt.CheckState(raw_check_state)
        except (TypeError, ValueError):
            check_state = Qt.CheckState.Unchecked
        if check_state == Qt.CheckState.Checked:
            check_option.state |= QStyle.StateFlag.State_On
        elif check_state == Qt.CheckState.PartiallyChecked:
            check_option.state |= QStyle.StateFlag.State_NoChange
        else:
            check_option.state |= QStyle.StateFlag.State_Off
        widget.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorCheckBox,
            check_option,
            painter,
            widget,
        )

    def _on_view_destroyed(self, _object=None) -> None:
        self._view = None
        self._viewport = None
