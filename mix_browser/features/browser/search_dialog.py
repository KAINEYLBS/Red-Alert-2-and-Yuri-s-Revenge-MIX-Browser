from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QEventLoop,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QPoint,
    QRegularExpression,
    QT_TRANSLATE_NOOP,
    Qt,
    QSignalBlocker,
    Signal,
    QUrl,
)
from PySide6.QtGui import QAction, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from mix_browser.features.browser.file_type_support import (
    ALL_BROWSER_TYPE_FILTERS,
    OTHER_FILE_TYPE_FILTER,
    browser_file_type_label,
    browser_type_filter_label,
    browser_type_filter_key,
)
from mix_browser.features.browser.recursive_search import SearchHit, SearchOutcome
from mix_browser.features.browser.rounded_row_delegate import RoundedRowDelegate


# @arch mix-browser.search-results-model model | en: Filters recursive search hits by type and palette state | zh: 按文件类型与色盘状态筛选递归搜索结果
class SearchResultsTableModel(QAbstractTableModel):
    HEADERS = tuple(
        QT_TRANSLATE_NOOP("SearchResultsTableModel", label)
        for label in ("Relative path", "Type")
    )
    OTHER_FILTER = OTHER_FILE_TYPE_FILTER

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all_hits: tuple[SearchHit, ...] = ()
        self._hits: tuple[SearchHit, ...] = ()
        self._type_filter: str | None = None
        self._fallback_palette_filter = False

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._hits)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )

    def hit_at(self, row: int) -> SearchHit | None:
        return self._hits[row] if 0 <= row < len(self._hits) else None

    @property
    def total_count(self) -> int:
        return len(self._all_hits)

    @property
    def type_filter(self) -> str | None:
        return self._type_filter

    @property
    def fallback_palette_filter(self) -> bool:
        return self._fallback_palette_filter

    def set_hits(self, hits: tuple[SearchHit, ...]) -> None:
        self.beginResetModel()
        self._all_hits = hits
        self._apply_filters()
        self.endResetModel()

    def available_type_filters(self) -> tuple[str, ...]:
        return ALL_BROWSER_TYPE_FILTERS

    def present_type_filters(self) -> frozenset[str]:
        values = {
            browser_type_filter_key(hit.type_label, hit.relative_path)
            for hit in self._all_hits
        }
        return frozenset(values)

    def set_type_filter(self, type_filter: str | None) -> None:
        if type_filter == self._type_filter:
            return
        self.beginResetModel()
        self._type_filter = type_filter
        self._apply_filters()
        self.endResetModel()

    def set_fallback_palette_filter(self, enabled: bool) -> None:
        if enabled == self._fallback_palette_filter:
            return
        self.beginResetModel()
        self._fallback_palette_filter = enabled
        self._apply_filters()
        self.endResetModel()

    def _apply_filters(self) -> None:
        hits = self._all_hits
        if self._fallback_palette_filter:
            hits = tuple(hit for hit in hits if hit.uses_fallback_palette is True)
        if self._type_filter is None:
            self._hits = hits
        elif self._type_filter == self.OTHER_FILTER:
            self._hits = tuple(
                hit
                for hit in hits
                if browser_type_filter_key(hit.type_label, hit.relative_path)
                == self.OTHER_FILTER
            )
        else:
            self._hits = tuple(
                hit
                for hit in hits
                if browser_type_filter_key(hit.type_label, hit.relative_path) == self._type_filter
            )

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._hits):
            return None
        hit = self._hits[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                hit.relative_path
                if index.column() == 0
                else browser_file_type_label(hit.type_label, hit.relative_path)
            )
        if role == Qt.ItemDataRole.ToolTipRole:
            return hit.relative_path
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and 0 <= section < len(self.HEADERS)
        ):
            return self.tr(self.HEADERS[section])
        return None


# @arch mix-browser.search-results-table-view component | en: Starts copy-only drags from selected search results | zh: 从选中的搜索结果启动仅复制拖拽
class _SearchResultsTableView(QTableView):
    drag_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drag_start_active = False

    def startDrag(self, _supported_actions) -> None:
        if self._drag_start_active:
            return
        self._drag_start_active = True
        try:
            selection = self.selectionModel()
            if selection is not None and selection.selectedRows():
                self.drag_requested.emit()
        finally:
            self._drag_start_active = False


# @arch mix-browser.search-results-dialog component | en: Collects recursive search criteria and presents matching paths | zh: 收集递归搜索条件并显示匹配路径
class SearchResultsDialog(QDialog):
    search_requested = Signal(str, bool, bool)
    result_selected = Signal(object)
    result_open_requested = Signal(object)
    copy_context_changed = Signal(object)
    result_drag_requested = Signal(object)
    drag_cancelled = Signal()

    def __init__(
        self,
        root_label: str,
        parent=None,
        *,
        developer_tools_enabled: bool = False,
        copy_action: QAction,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Search from Root"))
        self.resize(900, 600)
        self.setMinimumSize(600, 360)
        self.selected_hit: SearchHit | None = None
        self.developer_tools_enabled = developer_tools_enabled
        self.copy_action = copy_action

        self.root_label = QLabel(self.tr("Root: {0}").format(root_label), self)
        self.root_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.root_label.setWordWrap(True)
        self.query_field = QLineEdit(self)
        self.query_field.setClearButtonEnabled(True)
        self.query_field.setPlaceholderText(
            self.tr(
                "Search names and paths (optional for fallback palette filter)"
                if developer_tools_enabled
                else "Search names and relative paths"
            )
        )
        self.regex_toggle = QCheckBox(self.tr("Regular expression"), self)
        self.search_button = QPushButton(self.tr("Search"), self)
        self.search_button.setDefault(True)
        search_row = QHBoxLayout()
        search_row.addWidget(self.query_field, 1)
        search_row.addWidget(self.regex_toggle)
        search_row.addWidget(self.search_button)

        self.status_label = QLabel(self.tr("Enter a search term."), self)
        self.status_label.setWordWrap(True)
        self._status_summary = (
            self.tr("Enter a search term or select the fallback palette filter.")
            if developer_tools_enabled
            else self.tr("Enter a search term.")
        )
        self.model = SearchResultsTableModel(self)
        self.model.modelAboutToBeReset.connect(self._clear_selected_hit)
        self.type_filter_label = QLabel(self.tr("File type:"), self)
        self.type_filter_combo = QComboBox(self)
        self.type_filter_combo.addItem(self.tr("All types"), None)
        self.type_filter_combo.currentIndexChanged.connect(self._on_type_filter_changed)
        self.palette_filter_label = QLabel(self.tr("Palette:"), self)
        self.palette_filter_combo = QComboBox(self)
        self.palette_filter_combo.addItem(self.tr("All palettes"), False)
        self.palette_filter_combo.addItem(
            self.tr("Fallback grayscale only"),
            True,
        )
        self.palette_filter_label.setVisible(developer_tools_enabled)
        self.palette_filter_combo.setVisible(developer_tools_enabled)
        self.palette_filter_combo.currentIndexChanged.connect(
            self._on_palette_filter_changed
        )
        type_filter_row = QHBoxLayout()
        type_filter_row.addStretch(1)
        type_filter_row.addWidget(self.palette_filter_label)
        type_filter_row.addWidget(self.palette_filter_combo)
        type_filter_row.addWidget(self.type_filter_label)
        type_filter_row.addWidget(self.type_filter_combo)
        self.table = _SearchResultsTableView(self)
        self.table.setModel(self.model)
        self.table.addAction(copy_action)
        self.table.setDragEnabled(True)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.table.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.table.drag_requested.connect(self._on_drag_requested)
        self._drag_pending = False
        self._drag_wait_loop: QEventLoop | None = None
        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self._row_delegate = RoundedRowDelegate(self.table)
        self.table.setItemDelegate(self._row_delegate)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.table.selectionModel().currentChanged.connect(
            self._on_current_result_changed
        )
        self.table.doubleClicked.connect(self._open_result)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.root_label)
        layout.addLayout(search_row)
        layout.addWidget(self.status_label)
        layout.addLayout(type_filter_row)
        layout.addWidget(self.table, 1)
        layout.addWidget(buttons)
        self.search_button.clicked.connect(self._request_search)
        self.query_field.returnPressed.connect(self._request_search)
        self._refresh_type_filter_options()

    def set_search_running(self, running: bool) -> None:
        self.query_field.setEnabled(not running)
        self.regex_toggle.setEnabled(not running)
        self.search_button.setEnabled(not running)
        self.palette_filter_combo.setEnabled(not running)
        if running:
            self.model.set_hits(())
            self._set_status_summary(self.tr("Searching from the root..."))

    def show_outcome(self, outcome: SearchOutcome) -> None:
        self.set_search_running(False)
        self.model.set_hits(outcome.hits)
        self._refresh_type_filter_options()
        self._refresh_palette_filter_options()
        if outcome.error:
            self._set_status_summary(
                self.tr("Invalid regular expression: {0}").format(outcome.error)
            )
            return
        status = self.tr("{0:,} results").format(len(outcome.hits))
        if outcome.cancelled:
            status += self.tr("; search cancelled, showing partial results")
        if outcome.truncated:
            status += self.tr(
                "; some nested MIX branches were skipped to prevent excessive recursion"
            )
        if not outcome.hits:
            status = (
                self.tr("No results")
                if not outcome.cancelled
                else self.tr("No results before cancellation")
            )
        self._set_status_summary(status)

    def show_search_error(self, message: str) -> None:
        self.set_search_running(False)
        self._set_status_summary(self.tr("Search failed: {0}").format(message))

    def _refresh_type_filter_options(self) -> None:
        selected_filter = self.model.type_filter
        present_filters = self.model.present_type_filters()
        if selected_filter is not None and selected_filter not in present_filters:
            selected_filter = None
            self.model.set_type_filter(None)
        blocker = QSignalBlocker(self.type_filter_combo)
        self.type_filter_combo.clear()
        self.type_filter_combo.addItem(self.tr("All types"), None)
        for type_filter in self.model.available_type_filters():
            label = browser_type_filter_label(type_filter)
            self.type_filter_combo.addItem(label, type_filter)
            item = self.type_filter_combo.model().item(self.type_filter_combo.count() - 1)
            item.setEnabled(type_filter in present_filters)
        selected_index = self.type_filter_combo.findData(selected_filter)
        self.type_filter_combo.setCurrentIndex(max(0, selected_index))
        del blocker
        self.model.set_type_filter(self.type_filter_combo.currentData())
        self._refresh_status_label()

    def _refresh_palette_filter_options(self) -> None:
        self._refresh_status_label()

    def _on_type_filter_changed(self, _index: int) -> None:
        self.model.set_type_filter(self.type_filter_combo.currentData())
        self._refresh_status_label()

    def _on_palette_filter_changed(self, _index: int) -> None:
        self.model.set_fallback_palette_filter(
            bool(self.palette_filter_combo.currentData())
        )
        self._refresh_status_label()

    def _set_status_summary(self, summary: str) -> None:
        self._status_summary = summary
        self._refresh_status_label()

    def _refresh_status_label(self) -> None:
        summary = self._status_summary
        if (
            (self.model.type_filter is not None or self.model.fallback_palette_filter)
            and self.model.total_count
        ):
            summary += self.tr("; showing {0:,} of {1:,}").format(
                self.model.rowCount(),
                self.model.total_count,
            )
        self.status_label.setText(summary)

    def _request_search(self) -> None:
        query = self.query_field.text()
        fallback_only = self.model.fallback_palette_filter
        if not query and not (self.developer_tools_enabled and fallback_only):
            self._set_status_summary(
                self.tr("Enter a search term or select the fallback palette filter.")
                if self.developer_tools_enabled
                else self.tr("Enter a search term.")
            )
            return
        if query and self.regex_toggle.isChecked():
            expression = QRegularExpression(
                query,
                QRegularExpression.PatternOption.CaseInsensitiveOption,
            )
            if not expression.isValid():
                self._set_status_summary(
                    self.tr("Invalid regular expression: {0}").format(
                        expression.errorString()
                    )
                )
                return
        self.selected_hit = None
        self.set_search_running(True)
        self.search_requested.emit(
            query,
            self.regex_toggle.isChecked(),
            fallback_only,
        )

    def _on_current_result_changed(
        self,
        current: QModelIndex,
        _previous: QModelIndex,
    ) -> None:
        hit = self.model.hit_at(current.row()) if current.isValid() else None
        if hit is None:
            self.selected_hit = None
            return
        if hit == self.selected_hit:
            return
        self.selected_hit = hit
        self.result_selected.emit(hit)

    def _clear_selected_hit(self) -> None:
        self.selected_hit = None

    def _open_result(self, index: QModelIndex) -> None:
        hit = self.model.hit_at(index.row())
        if hit is None:
            return
        self.selected_hit = hit
        self.result_open_requested.emit(hit)

    @property
    def drag_pending(self) -> bool:
        return self._drag_pending

    def _on_drag_requested(self) -> None:
        self._drag_pending = True
        self.result_drag_requested.emit(self.selected_hits())
        if self._drag_pending:
            self._wait_for_drag()

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
        if watched in (self.table, self.table.viewport()):
            if event.type() == QEvent.Type.FocusIn:
                self.copy_context_changed.emit(self)
            elif event.type() == QEvent.Type.FocusOut:
                self.copy_context_changed.emit(None)
        if watched is self.table.viewport() and event.type() == QEvent.Type.ContextMenu:
            self._show_result_context_menu(event.pos())
            return True
        if (
            watched in (self.table, self.table.viewport())
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self._drag_pending
        ):
            self._drag_pending = False
            self.drag_cancelled.emit()
            self._finish_waiting_drag()
        return False

    def _show_result_context_menu(self, position: QPoint) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        selection = self.table.selectionModel()
        selected_rows = {
            selected.row() for selected in selection.selectedRows()
        }
        selection.setCurrentIndex(
            index,
            QItemSelectionModel.SelectionFlag.NoUpdate
            if index.row() in selected_rows
            else QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        hit = self.model.hit_at(index.row())
        if hit is None:
            return

        menu = QMenu(self)
        open_action = menu.addAction(self.tr("Open\tDouble-click"))
        menu.addAction(self.copy_action)
        menu.addSeparator()
        location_action = menu.addAction(self.tr("Open Location\tSingle-click"))
        open_action.triggered.connect(
            lambda _checked=False, selected_hit=hit: self.result_open_requested.emit(
                selected_hit
            )
        )
        location_action.triggered.connect(
            lambda _checked=False, selected_hit=hit: self.result_selected.emit(
                selected_hit
            )
        )
        self.copy_context_changed.emit(self)
        try:
            menu.exec(self.table.viewport().mapToGlobal(position))
        finally:
            self.copy_context_changed.emit(None)

    def selected_hits(self) -> tuple[SearchHit, ...]:
        rows = sorted(
            {index.row() for index in self.table.selectionModel().selectedRows()}
        )
        return tuple(
            hit
            for row in rows
            if (hit := self.model.hit_at(row)) is not None
        )
