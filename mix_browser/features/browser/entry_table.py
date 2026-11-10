from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QEventLoop,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QRect,
    QSignalBlocker,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLayoutItem,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mix_browser.features.browser.file_type_support import (
    CONFIGURABLE_BROWSER_TYPE_FILTERS,
    DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS,
    DEFAULT_FLAT_BROWSER_TYPE_FILTERS,
    FILTERABLE_BROWSER_TYPE_FILTERS,
    NON_ADJUSTABLE_BROWSER_TYPE_FILTERS,
    OTHER_FILE_TYPE_FILTER,
    browser_type_filter_label,
    browser_type_filter_key,
)
from mix_browser.features.browser.table_model import MixEntryTableModel
from mix_browser.shared.application_style import (
    BROWSER_TOOLBAR_CONTROL_HEIGHT,
    mark_menu_tool_button,
)


# Qt Widgets has no built-in layout that wraps controls across rows.
# @arch mix-browser.filter-flow-layout component | en: Wraps visible type filters to fit the available browser width | zh: 将可见类型筛选项自动换行以适应浏览器可用宽度
class _FilterFlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self) -> bool:
        return True

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations()

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize(0, 0)
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size += QSize(left + right, top + bottom)
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        x = rect.x() + left
        y = rect.y() + top
        right_edge = rect.x() + rect.width() - right
        line_height = 0
        has_item_on_line = False

        for item in self._items:
            if item.isEmpty():
                continue
            item_size = item.sizeHint()
            if (
                has_item_on_line
                and x + item_size.width() > right_edge
            ):
                x = rect.x() + left
                y += line_height + self.spacing()
                line_height = 0
                has_item_on_line = False

            if not test_only:
                item.setGeometry(
                    QRect(x, y, item_size.width(), item_size.height())
                )
            x += item_size.width() + self.spacing()
            line_height = max(line_height, item_size.height())
            has_item_on_line = True

        return y + line_height + bottom - rect.y()


# @arch mix-browser.visible-filters component | en: Lets users choose which type filters appear above the browser list | zh: 供用户选择浏览器列表上方显示的类型筛选项
class _VisibleFiltersDialog(QDialog):
    def __init__(self, visible_type_filters: set[str], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Visible Filters"))
        self.resize(360, 440)

        self.type_list = QListWidget(self)
        primary_filter_types = ("Folder", "MIX") + tuple(
            type_filter
            for type_filter in DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS
            if type_filter != OTHER_FILE_TYPE_FILTER
        )
        ordered_filter_types = primary_filter_types + tuple(
            type_filter
            for type_filter in CONFIGURABLE_BROWSER_TYPE_FILTERS
            if type_filter not in primary_filter_types
        ) + (OTHER_FILE_TYPE_FILTER,)
        self._items: dict[str, QListWidgetItem] = {}
        for type_filter in ordered_filter_types:
            item = QListWidgetItem(browser_type_filter_label(type_filter))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if type_filter in visible_type_filters
                else Qt.CheckState.Unchecked
            )
            if type_filter == OTHER_FILE_TYPE_FILTER:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(Qt.CheckState.Checked)
            self.type_list.addItem(item)
            self._items[type_filter] = item

        self.reset_button = QPushButton(self.tr("Reset"), self)
        self.reset_button.clicked.connect(self._reset_to_defaults)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addWidget(self.reset_button)
        button_row.addStretch(1)
        button_row.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("Choose the filters shown above the list:"), self))
        layout.addWidget(self.type_list, 1)
        layout.addLayout(button_row)

    def visible_type_filters(self) -> set[str]:
        return {
            type_filter
            for type_filter, item in self._items.items()
            if item.checkState() == Qt.CheckState.Checked
        }

    def _reset_to_defaults(self) -> None:
        defaults = set(DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS)
        for type_filter, item in self._items.items():
            item.setCheckState(
                Qt.CheckState.Checked
                if type_filter in defaults
                else Qt.CheckState.Unchecked
            )


# @arch mix-browser.entry-table-view component | en: Preserves browser selections during copy drags and excludes DAT rows from MIX multiselection | zh: 拖拽复制时保留浏览表格选中项，并禁止 MIX 内的 DAT 进入多选
class _EntryTableView(QTableView):
    drag_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drag_start_active = False
        self._drag_selection_rows: tuple[int, ...] = ()
        self._drag_current_index = QModelIndex()
        self._blocked_dat_press = False
        self._enforcing_selection_rules = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._drag_selection_rows = ()
        self._drag_current_index = QModelIndex()
        if event.button() == Qt.MouseButton.LeftButton:
            selection = self.selectionModel()
            if selection is not None:
                selected_rows = selection.selectedRows()
                if len(selected_rows) > 1 and self._is_dat_at(event.position().toPoint()):
                    self._blocked_dat_press = True
                    event.accept()
                    return
                preservable_rows = tuple(
                    index.row()
                    for index in selected_rows
                    if not self._is_dat_row(index.row())
                )
                if len(preservable_rows) > 1:
                    self._drag_selection_rows = preservable_rows
                    self._drag_current_index = self.currentIndex()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        selection = self.selectionModel()
        if (
            selection is not None
            and len(selection.selectedRows()) > 1
            and self._is_dat_at(event.position().toPoint())
        ):
            self._blocked_dat_press = True
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._blocked_dat_press and event.button() == Qt.MouseButton.LeftButton:
            self._blocked_dat_press = False
            self._drag_selection_rows = ()
            self._drag_current_index = QModelIndex()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._drag_selection_rows = ()
        self._drag_current_index = QModelIndex()

    def startDrag(self, _supported_actions) -> None:
        if self._drag_start_active:
            return
        self._drag_start_active = True
        try:
            self._restore_drag_selection()
            selection = self.selectionModel()
            if selection is not None and selection.selectedRows():
                self.drag_requested.emit()
        finally:
            self._drag_start_active = False

    def enforce_multi_selection_rules(self, *_args) -> None:
        if self._enforcing_selection_rules:
            return
        selection = self.selectionModel()
        if selection is None:
            return
        selected_rows = selection.selectedRows()
        if len(selected_rows) < 2:
            return
        dat_rows = [index for index in selected_rows if self._is_dat_row(index.row())]
        if not dat_rows:
            return
        self._enforcing_selection_rules = True
        try:
            for index in dat_rows:
                selection.select(
                    index,
                    QItemSelectionModel.SelectionFlag.Deselect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        finally:
            self._enforcing_selection_rules = False

    def _restore_drag_selection(self) -> None:
        if len(self._drag_selection_rows) < 2:
            return
        model = self.model()
        selection = self.selectionModel()
        if model is None or selection is None:
            return
        selection.clearSelection()
        for row in self._drag_selection_rows:
            if 0 <= row < model.rowCount():
                selection.select(
                    model.index(row, 0),
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
        if self._drag_current_index.isValid():
            selection.setCurrentIndex(
                self._drag_current_index,
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        self._drag_selection_rows = ()
        self._drag_current_index = QModelIndex()

    def _is_dat_row(self, row: int) -> bool:
        model = self.model()
        if not isinstance(model, MixEntryTableModel):
            return False
        entry = model.entry_at(row)
        if entry is None:
            return False
        return (
            Path(entry.name or "").suffix.casefold() == ".dat"
            or (entry.file_type or "").casefold() == "dat"
        )

    def _is_dat_at(self, position) -> bool:
        index = self.indexAt(position)
        return index.isValid() and self._is_dat_row(index.row())


# @arch mix-browser.entry-table component | en: Displays and filters browser entries while forwarding table interactions | zh: 显示并筛选浏览对象，同时转发表格交互事件
class EntryTable(QWidget):
    context_menu_requested = Signal(object)
    drag_requested = Signal()
    drag_cancelled = Signal()
    filter_changed = Signal()
    visible_type_filters_changed = Signal(object)

    def __init__(
        self,
        source_model: QAbstractItemModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_model = source_model
        self.table = _EntryTableView(self)
        self.table.setModel(source_model)
        self.table.setDragEnabled(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.table.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.table.drag_requested.connect(self._on_drag_requested)
        self._drag_pending = False
        self._drag_wait_loop: QEventLoop | None = None
        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.selectionModel().selectionChanged.connect(
            self.table.enforce_multi_selection_rules
        )
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setIconSize(QSize(16, 16))
        self.table.setMouseTracking(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate((360, 110, 120, 130)):
            if column < source_model.columnCount():
                header.resizeSection(column, width)
        self.table.setMinimumWidth(360)

        self._visible_type_filters = set(DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS)
        self._enabled_type_filters = set(FILTERABLE_BROWSER_TYPE_FILTERS) | {
            OTHER_FILE_TYPE_FILTER
        } | set(NON_ADJUSTABLE_BROWSER_TYPE_FILTERS)
        self._type_filter_checkboxes = {}
        self._row_type_filters: tuple[str, ...] = ()
        self.filter_options_widget = QWidget(self)
        self.filter_options_layout = _FilterFlowLayout(self.filter_options_widget)
        self.filter_options_layout.setContentsMargins(0, 0, 0, 0)
        ordered_filter_types = tuple(
            type_filter
            for type_filter in DEFAULT_FLAT_BROWSER_TYPE_FILTERS
            if type_filter != OTHER_FILE_TYPE_FILTER
        ) + tuple(
            type_filter
            for type_filter in FILTERABLE_BROWSER_TYPE_FILTERS
            if type_filter not in DEFAULT_FLAT_BROWSER_TYPE_FILTERS
        )
        for type_filter in (
            "Folder",
            "MIX",
            *ordered_filter_types,
            OTHER_FILE_TYPE_FILTER,
        ):
            checkbox = QCheckBox(
                browser_type_filter_label(type_filter),
                self.filter_options_widget,
            )
            checkbox.setFixedHeight(BROWSER_TOOLBAR_CONTROL_HEIGHT)
            checkbox.setChecked(True)
            checkbox.setVisible(type_filter in self._visible_type_filters)
            if type_filter in NON_ADJUSTABLE_BROWSER_TYPE_FILTERS:
                checkbox.setEnabled(False)
            checkbox.toggled.connect(
                lambda checked, selected_type=type_filter: self._on_type_filter_toggled(
                    selected_type,
                    checked,
                )
            )
            self.filter_options_layout.addWidget(checkbox)
            self._type_filter_checkboxes[type_filter] = checkbox

        self.filter_options_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self.filter_selection_button = QToolButton(self)
        self.filter_selection_button.setText(self.tr("Filter selection..."))
        self.filter_selection_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.filter_selection_menu = QMenu(self.filter_selection_button)
        check_all_action = self.filter_selection_menu.addAction(
            self.tr("Check all shown filters")
        )
        uncheck_all_action = self.filter_selection_menu.addAction(
            self.tr("Uncheck all shown filters")
        )
        check_all_action.triggered.connect(
            lambda _checked=False: self._set_visible_filter_states(True)
        )
        uncheck_all_action.triggered.connect(
            lambda _checked=False: self._set_visible_filter_states(False)
        )
        self.filter_selection_button.setMenu(self.filter_selection_menu)
        self.filter_selection_button.setToolTip(
            self.tr("Set the checked state of all filters shown above the list")
        )
        mark_menu_tool_button(self.filter_selection_button)

        self.visible_filters_button = QPushButton(self.tr("Visible filters..."), self)
        self.visible_filters_button.clicked.connect(self._open_visible_filters_dialog)
        filter_button_width = max(
            self.filter_selection_button.sizeHint().width(),
            self.visible_filters_button.sizeHint().width(),
        )
        self.filter_selection_button.setFixedSize(
            filter_button_width,
            BROWSER_TOOLBAR_CONTROL_HEIGHT,
        )
        self.visible_filters_button.setFixedSize(
            filter_button_width,
            BROWSER_TOOLBAR_CONTROL_HEIGHT,
        )
        self.filter_actions_widget = QWidget(self)
        self.filter_actions_layout = QHBoxLayout(self.filter_actions_widget)
        self.filter_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.filter_actions_layout.setSpacing(6)
        self.filter_actions_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.filter_actions_layout.addWidget(self.filter_selection_button)
        self.filter_actions_layout.addWidget(self.visible_filters_button)

        source_model.modelReset.connect(self._refresh_type_filter_state)
        source_model.rowsInserted.connect(self._refresh_type_filter_state)
        source_model.rowsRemoved.connect(self._refresh_type_filter_state)
        source_model.layoutChanged.connect(self._refresh_type_filter_state)
        source_model.dataChanged.connect(self._refresh_type_filter_state)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(6)
        filter_row.addWidget(
            self.filter_options_widget,
            1,
        )
        filter_row.addWidget(
            self.filter_actions_widget,
            0,
            Qt.AlignmentFlag.AlignTop,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(filter_row)
        layout.addWidget(self.table, 1)
        self._refresh_type_filter_state()

    @property
    def visible_row_count(self) -> int:
        return sum(
            self._is_row_type_visible(type_filter)
            for type_filter in self._row_type_filters
        )

    def set_visible_type_filters(
        self,
        visible_type_filters: Iterable[str],
    ) -> None:
        supported_types = set(CONFIGURABLE_BROWSER_TYPE_FILTERS)
        visible = set(visible_type_filters) & supported_types
        visible.add(OTHER_FILE_TYPE_FILTER)
        previous_visible = self._visible_type_filters
        changed_types = previous_visible ^ visible
        self._visible_type_filters = visible

        for type_filter in changed_types:
            self._enabled_type_filters.add(type_filter)
            checkbox = self._type_filter_checkboxes.get(type_filter)
            if checkbox is not None:
                blocker = QSignalBlocker(checkbox)
                checkbox.setChecked(True)
                del blocker

        for type_filter, checkbox in self._type_filter_checkboxes.items():
            checkbox.setVisible(type_filter in visible)
        self.filter_options_layout.invalidate()
        self.filter_options_widget.updateGeometry()
        self._apply_type_filters()
        if visible != previous_visible:
            self.filter_changed.emit()
            self.visible_type_filters_changed.emit(frozenset(visible))

    def _type_filter_for_row(self, row: int) -> str:
        name = self.source_model.data(
            self.source_model.index(row, 0),
            Qt.ItemDataRole.DisplayRole,
        )
        type_label = self.source_model.data(
            self.source_model.index(row, 1),
            Qt.ItemDataRole.UserRole,
        )
        return browser_type_filter_key(
            str(type_label or ""),
            str(name or ""),
        )

    def _on_type_filter_toggled(self, type_filter: str, checked: bool) -> None:
        if type_filter in NON_ADJUSTABLE_BROWSER_TYPE_FILTERS:
            return
        if checked:
            self._enabled_type_filters.add(type_filter)
        else:
            self._enabled_type_filters.discard(type_filter)
        self._apply_type_filters()
        self.filter_changed.emit()

    def _refresh_type_filter_state(self, *_args) -> None:
        previous_visible_count = self.visible_row_count
        self._row_type_filters = tuple(
            self._type_filter_for_row(row)
            for row in range(self.source_model.rowCount())
        )
        for type_filter, checkbox in self._type_filter_checkboxes.items():
            checkbox.setVisible(type_filter in self._visible_type_filters)
            if type_filter in NON_ADJUSTABLE_BROWSER_TYPE_FILTERS:
                blocker = QSignalBlocker(checkbox)
                checkbox.setChecked(True)
                del blocker
                checkbox.setEnabled(False)
            else:
                checkbox.setEnabled(True)
        self.filter_options_layout.invalidate()
        self.filter_options_widget.updateGeometry()
        self._apply_type_filters()
        if self.visible_row_count != previous_visible_count:
            self.filter_changed.emit()

    def _open_visible_filters_dialog(self) -> None:
        dialog = _VisibleFiltersDialog(self._visible_type_filters, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_visible_type_filters(dialog.visible_type_filters())

    def _set_visible_filter_states(self, checked: bool) -> None:
        changed = False
        for type_filter, checkbox in self._type_filter_checkboxes.items():
            if (
                type_filter not in self._visible_type_filters
                or type_filter in NON_ADJUSTABLE_BROWSER_TYPE_FILTERS
            ):
                continue
            if checkbox.isChecked() == checked:
                continue
            blocker = QSignalBlocker(checkbox)
            checkbox.setChecked(checked)
            del blocker
            if checked:
                self._enabled_type_filters.add(type_filter)
            else:
                self._enabled_type_filters.discard(type_filter)
            changed = True

        if changed:
            self._apply_type_filters()
            self.filter_changed.emit()

    def _is_row_type_visible(self, type_filter: str) -> bool:
        if type_filter in NON_ADJUSTABLE_BROWSER_TYPE_FILTERS:
            return True
        if type_filter not in self._visible_type_filters:
            type_filter = OTHER_FILE_TYPE_FILTER
        return type_filter in self._enabled_type_filters

    def _apply_type_filters(self) -> None:
        for row, type_filter in enumerate(self._row_type_filters):
            visible = self._is_row_type_visible(type_filter)
            self.table.setRowHidden(row, not visible)

        selection = self.table.selectionModel()
        selected_rows = selection.selectedRows()
        if any(self.table.isRowHidden(index.row()) for index in selected_rows):
            selection.clearSelection()

        current = self.table.currentIndex()
        if current.isValid() and self.table.isRowHidden(current.row()):
            self.table.setCurrentIndex(QModelIndex())

    def _on_drag_requested(self) -> None:
        self._drag_pending = True
        self.drag_requested.emit()
        if self._drag_pending:
            self._wait_for_drag()

    @property
    def drag_pending(self) -> bool:
        return self._drag_pending

    def _wait_for_drag(self) -> None:
        if not self._drag_pending:
            return
        loop = QEventLoop(self)
        self._drag_wait_loop = loop
        if self._drag_pending:
            loop.exec()
        self._drag_wait_loop = None

    def _finish_waiting_drag(self) -> None:
        if self._drag_wait_loop is not None:
            self._drag_wait_loop.quit()

    def start_drag(self, paths: tuple[Path, ...]) -> Qt.DropAction:
        if not paths:
            self._drag_pending = False
            self._finish_waiting_drag()
            return Qt.DropAction.IgnoreAction
        self._drag_pending = False
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        drag = QDrag(self.table)
        drag.setMimeData(mime_data)
        try:
            return drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
        finally:
            self._finish_waiting_drag()

    def cancel_pending_drag(self) -> None:
        self._drag_pending = False
        self._finish_waiting_drag()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.table.viewport() and event.type() == QEvent.Type.ContextMenu:
            self.context_menu_requested.emit(event.pos())
            return True
        if (
            watched in (self.table, self.table.viewport())
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self._drag_pending
        ):
            self.cancel_pending_drag()
            self.drag_cancelled.emit()
        return super().eventFilter(watched, event)
