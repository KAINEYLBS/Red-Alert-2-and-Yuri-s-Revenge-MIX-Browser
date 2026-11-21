from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

from PySide6.QtCore import (
    QAbstractItemModel,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QKeyEvent, QPainter, QPalette, QPolygon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyleOptionHeader,
    QTableView,
    QToolButton,
)

from mix_browser.shared.interaction_help import (
    InteractionHelpButton,
    InteractionHelpCatalog,
)


Row = TypeVar("Row")
SortKey = tuple[int, Qt.SortOrder]


# @arch mix-browser.stable-multi-sort utility | en: Applies stable ordered sort keys to table rows | zh: 按稳定顺序将多个排序键应用到表格行
def stable_multi_sort(
    rows: Iterable[Row],
    sort_keys: tuple[SortKey, ...],
    key_for_column: Callable[[int, Row], object],
) -> list[Row]:
    sorted_rows = list(rows)
    for column, order in reversed(sort_keys):
        sorted_rows.sort(
            key=lambda row, selected_column=column: key_for_column(
                selected_column,
                row,
            ),
            reverse=order == Qt.SortOrder.DescendingOrder,
        )
    return sorted_rows


# @arch mix-browser.persistent-row-reorder utility | en: Reorders table rows while remapping persistent indexes to the same row objects | zh: 重排表格行时将持久索引映射回原来的行对象
def reorder_model_rows_preserving_indexes(
    model: QAbstractItemModel,
    current_rows: Sequence[Row],
    sorted_rows: list[Row],
    replace_rows: Callable[[list[Row]], None],
) -> None:
    persistent_indexes = model.persistentIndexList()
    row_identities = [
        id(current_rows[index.row()])
        if index.isValid() and 0 <= index.row() < len(current_rows)
        else None
        for index in persistent_indexes
    ]

    model.layoutAboutToBeChanged.emit()
    replace_rows(sorted_rows)
    new_row_by_identity = {
        id(row): row_number for row_number, row in enumerate(sorted_rows)
    }
    new_indexes = []
    for old_index, identity in zip(persistent_indexes, row_identities):
        row = new_row_by_identity.get(identity)
        new_indexes.append(
            model.index(row, old_index.column())
            if row is not None and old_index.isValid()
            else QModelIndex()
        )
    model.changePersistentIndexList(persistent_indexes, new_indexes)
    model.layoutChanged.emit()


# @arch mix-browser.application-sort-header component | en: Draws shared primary and secondary sorting controls for sortable tables | zh: 为可排序表格绘制统一的主次排序指示和清除控件
class ApplicationSortHeaderView(QHeaderView):
    sort_keys_changed = Signal(object)

    def __init__(
        self,
        parent=None,
        *,
        interaction_help: InteractionHelpCatalog | None = None,
    ) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._sort_keys: tuple[SortKey, ...] = ()
        self._release_modifiers = Qt.KeyboardModifier.NoModifier
        self._interaction_help = interaction_help
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(False)
        self.sectionClicked.connect(self._on_section_clicked)

        self._clear_button = QToolButton(self.viewport())
        self._clear_button.setObjectName("ClearSortButton")
        self._clear_button.setAutoRaise(True)
        self._clear_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        self._clear_button.setIconSize(QSize(14, 14))
        self._clear_button.setFixedSize(22, 22)
        self._clear_button.setToolTip(self.tr("Clear sorting"))
        self._clear_button.setAccessibleName(self.tr("Clear sorting"))
        self._clear_button.clicked.connect(lambda: self.set_sort_keys(()))
        self._clear_button.setEnabled(bool(self._sort_keys))

        self._help_button = (
            InteractionHelpButton(
                interaction_help,
                self.tr("Table sorting"),
                self.viewport(),
                group=self.tr("Table sorting"),
                align_popup_right=False,
            )
            if interaction_help is not None
            else QToolButton(self.viewport())
        )
        self._help_button.setVisible(interaction_help is not None)
        if interaction_help is None:
            self._help_button.setFixedSize(22, 22)
            self._help_button.hide()

        self.sectionResized.connect(self._position_header_buttons)
        self.sectionMoved.connect(self._position_header_buttons)
        self.geometriesChanged.connect(self._position_header_buttons)
        self.sectionCountChanged.connect(self._position_header_buttons)

    @property
    def sort_keys(self) -> tuple[SortKey, ...]:
        return self._sort_keys

    def set_sort_keys(self, sort_keys: tuple[SortKey, ...]) -> None:
        normalized: list[SortKey] = []
        for column, order in sort_keys:
            if not 0 <= column < self.count() or any(
                existing_column == column for existing_column, _ in normalized
            ):
                continue
            normalized.append((column, order))
            if len(normalized) == 2:
                break
        value = tuple(normalized)
        if value == self._sort_keys:
            return
        self._sort_keys = value
        self._clear_button.setEnabled(bool(value))
        self.viewport().update()
        self.sort_keys_changed.emit(value)

    def paintSection(self, painter: QPainter, rect, logical_index: int) -> None:
        if not rect.isValid():
            return
        option = QStyleOptionHeader()
        self.initStyleOption(option)
        self.initStyleOptionForIndex(option, logical_index)
        option.rect = rect
        option.sortIndicator = QStyleOptionHeader.SortIndicator.None_
        self.style().drawControl(
            QStyle.ControlElement.CE_HeaderSection,
            option,
            painter,
            self,
        )

        label_option = QStyleOptionHeader(option)
        label_rect = rect.adjusted(5, 0, -5, 0)
        sort_index = next(
            (
                index
                for index, (column, _order) in enumerate(self._sort_keys)
                if column == logical_index
            ),
            -1,
        )
        if sort_index >= 0:
            label_rect.adjust(0, 0, -16, 0)
        if logical_index == self._first_visible_section():
            label_rect.adjust(50, 0, 0, 0)
        label_option.rect = label_rect
        self.style().drawControl(
            QStyle.ControlElement.CE_HeaderLabel,
            label_option,
            painter,
            self,
        )

        if sort_index >= 0:
            self._paint_sort_arrow(painter, rect, sort_index, self._sort_keys[sort_index][1])

    def mouseReleaseEvent(self, event) -> None:
        self._release_modifiers = event.modifiers()
        try:
            super().mouseReleaseEvent(event)
        finally:
            self._release_modifiers = Qt.KeyboardModifier.NoModifier

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_header_buttons()

    def _on_section_clicked(self, column: int) -> None:
        current = list(self._sort_keys)
        existing_index = next(
            (index for index, (selected, _order) in enumerate(current) if selected == column),
            -1,
        )
        shift_pressed = bool(
            self._release_modifiers & Qt.KeyboardModifier.ShiftModifier
        )

        if shift_pressed:
            if existing_index >= 0:
                selected_column, order = current[existing_index]
                current[existing_index] = (selected_column, self._reverse(order))
            elif current:
                secondary = (column, Qt.SortOrder.AscendingOrder)
                current = [current[0], secondary]
            else:
                current = [(column, Qt.SortOrder.AscendingOrder)]
        elif existing_index == 0:
            selected_column, order = current[0]
            current = [(selected_column, self._reverse(order))]
        else:
            order = (
                current[existing_index][1]
                if existing_index > 0
                else Qt.SortOrder.AscendingOrder
            )
            current = [(column, order)]
        self.set_sort_keys(tuple(current))

    def _first_visible_section(self) -> int:
        for visual_index in range(self.count()):
            logical_index = self.logicalIndex(visual_index)
            if not self.isSectionHidden(logical_index):
                return logical_index
        return -1

    def _position_header_buttons(self, *_args) -> None:
        logical_index = self._first_visible_section()
        if logical_index < 0:
            self._clear_button.hide()
            self._help_button.hide()
            return
        section_left = self.sectionViewportPosition(logical_index)
        y = max(0, (self.viewport().height() - self._clear_button.height()) // 2)
        self._clear_button.move(section_left + 2, y)
        self._help_button.move(section_left + 26, y)
        self._clear_button.show()
        self._help_button.setVisible(self._interaction_help is not None)

    def _paint_sort_arrow(
        self,
        painter: QPainter,
        rect,
        priority: int,
        order: Qt.SortOrder,
    ) -> None:
        center_x = rect.right() - 9
        center_y = rect.center().y()
        width = 8
        height = 5
        if order == Qt.SortOrder.AscendingOrder:
            points = (
                QPoint(center_x - width // 2, center_y + height // 2),
                QPoint(center_x + width // 2, center_y + height // 2),
                QPoint(center_x, center_y - height // 2),
            )
        else:
            points = (
                QPoint(center_x - width // 2, center_y - height // 2),
                QPoint(center_x + width // 2, center_y - height // 2),
                QPoint(center_x, center_y + height // 2),
            )
        color_role = (
            QPalette.ColorRole.Highlight
            if priority == 0
            else QPalette.ColorRole.ButtonText
        )
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(color_role))
        painter.drawPolygon(QPolygon(points))
        painter.restore()

    @staticmethod
    def _reverse(order: Qt.SortOrder) -> Qt.SortOrder:
        return (
            Qt.SortOrder.DescendingOrder
            if order == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )


# @arch mix-browser.application-sortable-table component | en: Applies shared multi-column sorting behavior to sortable table views | zh: 为可排序表格统一应用多列排序行为
class ApplicationSortableTableView(QTableView):
    def __init__(
        self,
        parent=None,
        *,
        interaction_help: InteractionHelpCatalog | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSortingEnabled(False)
        self._sort_header = ApplicationSortHeaderView(
            self,
            interaction_help=interaction_help,
        )
        self.setHorizontalHeader(self._sort_header)
        self._sort_header.sort_keys_changed.connect(self._apply_sort_keys)
        self._sort_model = None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            selection = self.selectionModel()
            if selection is not None and len(selection.selectedRows()) > 1:
                event.accept()
                return
        super().keyPressEvent(event)

    def set_sort_keys(self, sort_keys: tuple[SortKey, ...]) -> None:
        self._sort_header.set_sort_keys(sort_keys)

    def setModel(self, model) -> None:
        if self._sort_model is not None:
            try:
                self._sort_model.modelReset.disconnect(self._reapply_sort_keys)
            except (RuntimeError, TypeError):
                pass
        super().setModel(model)
        self._sort_model = model
        if model is not None:
            model.modelReset.connect(self._reapply_sort_keys)
            self._sort_header._position_header_buttons()
        if self._sort_header.sort_keys:
            self._apply_sort_keys(self._sort_header.sort_keys)

    def _apply_sort_keys(self, sort_keys: tuple[SortKey, ...]) -> None:
        model = self.model()
        sort_rows = getattr(model, "sort_by_columns", None)
        row_object_at = getattr(model, "row_object_at", None)
        selection = self.selectionModel()
        if not callable(sort_rows) or not callable(row_object_at) or selection is None:
            return

        selected_row_numbers = sorted(
            {index.row() for index in selection.selectedIndexes()}
        )
        selected_objects = tuple(
            row_object_at(row) for row in selected_row_numbers
        )
        selected_objects = tuple(item for item in selected_objects if item is not None)
        current = selection.currentIndex()
        current_object = (
            row_object_at(current.row())
            if current.isValid()
            else None
        )
        current_column = current.column()

        sort_rows(sort_keys)

        row_count = model.rowCount()
        row_for_identity = {
            id(item): row
            for row in range(row_count)
            if (item := row_object_at(row)) is not None
        }
        selection.clearSelection()
        for item in selected_objects:
            row = row_for_identity.get(id(item))
            if row is not None:
                selection.select(
                    model.index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )

        current_row = row_for_identity.get(id(current_object))
        target = QModelIndex()
        if current_row is not None and model.columnCount() > 0:
            target = model.index(
                current_row,
                min(max(current_column, 0), model.columnCount() - 1),
            )
            selection.setCurrentIndex(
                target,
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        elif selected_objects:
            selected_row = row_for_identity.get(id(selected_objects[0]))
            if selected_row is not None and model.columnCount() > 0:
                target = model.index(selected_row, 0)
                selection.setCurrentIndex(
                    target,
                    QItemSelectionModel.SelectionFlag.NoUpdate,
                )
        if target.isValid():
            self.scrollTo(target, QAbstractItemView.ScrollHint.EnsureVisible)

    def _reapply_sort_keys(self) -> None:
        if self._sort_header.sort_keys:
            self._apply_sort_keys(self._sort_header.sort_keys)
