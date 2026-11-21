from __future__ import annotations

import os
import stat
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Event
from typing import Callable, Sequence

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QEvent,
    QModelIndex,
    QObject,
    QSettings,
    QPoint,
    QRect,
    QRectF,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtSvg import QSvgRenderer

from mix_browser.app.api import MixBrowserApplication
from mix_browser.features.archive.domain import (
    LOCAL_MIX_DATABASE_NAME,
    is_readable_mix_name,
)
from mix_browser.features.archive.type_detection import MIX_CONTAINER_SUFFIXES
from mix_browser.features.archive.writer import mix_file_ids_for_new_archive
from mix_browser.features.browser.directory_operations import is_valid_leaf_name
from mix_browser.features.system_integration.settings import (
    SHOW_BASIC_OPERATION_DIALOG_ONLY_ON_ISSUES_KEY,
)
from mix_browser.shared.mix_name_controls import add_mix_name_template_controls
from mix_browser.shared.semantic_colors import (
    base_status_color,
    set_semantic_status_style,
)
from mix_browser.shared.table_row_delegate import ApplicationTableRowDelegate
from mix_browser.shared.task_progress_dialog import (
    ProgressMode,
    TaskProgressController,
    TaskProgressDialog,
)


_ITEM_NAME_EDIT_ICON_SIZE = 16
_ITEM_NAME_EDIT_BUTTON_PADDING = 3
_ITEM_NAME_EDIT_BUTTON_WIDTH = (
    _ITEM_NAME_EDIT_ICON_SIZE + 2 * _ITEM_NAME_EDIT_BUTTON_PADDING
)
_LUCIDE_SQUARE_PEN_SVG = (
    Path(__file__).resolve().parents[2] / "data" / "icons" / "square-pen.svg"
).read_bytes()


@lru_cache(maxsize=64)
def _tinted_square_pen_renderer(color_name: str) -> QSvgRenderer:
    svg_data = _LUCIDE_SQUARE_PEN_SVG.replace(
        b"currentColor",
        color_name.encode("ascii"),
    )
    return QSvgRenderer(QByteArray(svg_data))


@dataclass
class _OperationRow:
    path: Path
    item_name: str
    destination: str
    status: str
    valid: bool


# @arch mix-browser.shell-operation-result-label component | en: Scrolls long operation results within the dialog footer | zh: 在操作弹窗底栏中滚动显示较长的结果信息
class _ScrollingResultLabel(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.setMinimumWidth(0)
        self._scroll_offset = 0
        self._scroll_pause_timer = QTimer(self)
        self._scroll_pause_timer.setSingleShot(True)
        self._scroll_pause_timer.setInterval(2000)
        self._scroll_pause_timer.timeout.connect(self._start_scrolling)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(40)
        self._scroll_timer.timeout.connect(self._advance_scroll)

    def set_message(self, message: str) -> None:
        message = " ".join(message.splitlines())
        if self.text() != message:
            self.setText(message)
            self._scroll_offset = 0
            self._scroll_pause_timer.stop()
            self._scroll_timer.stop()
        self._update_scrolling()
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_scrolling()

    def hideEvent(self, event) -> None:
        self._scroll_pause_timer.stop()
        self._scroll_timer.stop()
        self._scroll_offset = 0
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scrolling()

    def paintEvent(self, event) -> None:
        message = self.text()
        if not message:
            return
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        contents_rect = self.contentsRect()
        painter.setClipRect(contents_rect)
        metrics = self.fontMetrics()
        baseline = contents_rect.top() + (contents_rect.height() - metrics.height()) // 2
        baseline += metrics.ascent()
        text_width = metrics.horizontalAdvance(message)
        if self._scroll_timer.isActive() and text_width > contents_rect.width():
            gap = 32
            x = contents_rect.left() - self._scroll_offset
            painter.drawText(QPoint(x, baseline), message)
            painter.drawText(QPoint(x + text_width + gap, baseline), message)
            return
        painter.drawText(QPoint(contents_rect.left(), baseline), message)

    def _update_scrolling(self) -> None:
        overflows = (
            bool(self.text())
            and self.isVisible()
            and self.fontMetrics().horizontalAdvance(self.text())
            > self.contentsRect().width()
        )
        if overflows:
            if (
                not self._scroll_timer.isActive()
                and not self._scroll_pause_timer.isActive()
            ):
                self._scroll_pause_timer.start()
            return
        self._scroll_pause_timer.stop()
        self._scroll_timer.stop()
        self._scroll_offset = 0

    def _start_scrolling(self) -> None:
        if (
            self.isVisible()
            and self.fontMetrics().horizontalAdvance(self.text())
            > self.contentsRect().width()
        ):
            self._scroll_timer.start()
            self.update()

    def _advance_scroll(self) -> None:
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        self._scroll_offset = (self._scroll_offset + 2) % (text_width + 32)
        self.update()


# @arch mix-browser.shell-operation-file-delegate component | en: Paints and handles the per-row edit action in shell operation tables | zh: 在系统集成操作表格中绘制并处理每行的编辑图标操作
class _OperationFileDelegate(ApplicationTableRowDelegate):
    def __init__(self, view: QTableView, edit_tooltip: str) -> None:
        super().__init__(view)
        self._operation_view = view
        self._edit_tooltip = edit_tooltip
        self._hovered_cell: tuple[int, int] | None = None
        self._pressed_cell: tuple[int, int] | None = None
        self._editing_cells: set[tuple[int, int]] = set()

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        cell = self._cell_key(index)
        if (
            not self._is_editable_name_cell(index)
            or cell in self._editing_cells
        ):
            return
        widget = option.widget
        if widget is None:
            return
        button = QStyleOptionButton()
        button.rect = self._button_rect(option.rect)
        button.palette = option.palette
        button.features = QStyleOptionButton.ButtonFeature.Flat
        button.state = QStyle.StateFlag.State_Raised
        if option.state & QStyle.StateFlag.State_Enabled:
            button.state |= QStyle.StateFlag.State_Enabled
        if self._cell_key(index) == self._hovered_cell:
            button.state |= QStyle.StateFlag.State_MouseOver
        if self._cell_key(index) == self._pressed_cell:
            button.state |= QStyle.StateFlag.State_Sunken
        painter.save()
        widget.style().drawControl(
            QStyle.ControlElement.CE_PushButton,
            button,
            painter,
            widget,
        )
        color_group = (
            QPalette.ColorGroup.Active
            if option.state & QStyle.StateFlag.State_Enabled
            else QPalette.ColorGroup.Disabled
        )
        icon_color = button.palette.color(
            color_group,
            QPalette.ColorRole.ButtonText,
        )
        icon_size = min(
            _ITEM_NAME_EDIT_ICON_SIZE,
            button.rect.width() - 2 * _ITEM_NAME_EDIT_BUTTON_PADDING,
            button.rect.height() - 2 * _ITEM_NAME_EDIT_BUTTON_PADDING,
        )
        icon_rect = QRect(
            button.rect.center().x() - icon_size // 2,
            button.rect.center().y() - icon_size // 2,
            icon_size,
            icon_size,
        )
        _tinted_square_pen_renderer(icon_color.name()).render(
            painter,
            QRectF(icon_rect),
        )
        painter.restore()

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if editor is not None and self._is_editable_name_cell(index):
            self._editing_cells.add(self._cell_key(index))
            self._operation_view.viewport().update(
                self._operation_view.visualRect(index)
            )
        return editor

    def destroyEditor(self, editor, index) -> None:
        cell = self._cell_key(index)
        self._editing_cells.discard(cell)
        super().destroyEditor(editor, index)
        try:
            self._operation_view.viewport().update(
                self._operation_view.visualRect(index)
            )
        except RuntimeError:
            pass

    def tooltip_at_position(self, index, position) -> str | None:
        if (
            self._is_editable_name_cell(index)
            and self._cell_key(index) not in self._editing_cells
            and self._button_rect(
                self._operation_view.visualRect(index)
            ).contains(position)
        ):
            return self._edit_tooltip
        return None

    def editorEvent(self, event, model, option, index) -> bool:
        if not self._is_editable_name_cell(index):
            return super().editorEvent(event, model, option, index)
        if not isinstance(event, QMouseEvent):
            return super().editorEvent(event, model, option, index)
        cell = self._cell_key(index)
        over_button = self._button_rect(option.rect).contains(
            event.position().toPoint()
        )
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
            and over_button
        ):
            self._pressed_cell = cell
            self._operation_view.viewport().update(option.rect)
            return True
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            was_pressed = self._pressed_cell == cell
            self._pressed_cell = None
            self._operation_view.viewport().update(option.rect)
            if was_pressed and over_button:
                self._operation_view.setCurrentIndex(index)
                self._operation_view.edit(index)
                return True
        return super().editorEvent(event, model, option, index)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._operation_view.viewport():
            hovered_cell = None
            if event.type() == QEvent.Type.MouseMove and isinstance(
                event, QMouseEvent
            ):
                point = event.position().toPoint()
                index = self._operation_view.indexAt(point)
                if (
                    self._is_editable_name_cell(index)
                    and self._button_rect(
                        self._operation_view.visualRect(index)
                    ).contains(point)
                ):
                    hovered_cell = self._cell_key(index)
            elif event.type() == QEvent.Type.Leave:
                hovered_cell = None
            if hovered_cell != self._hovered_cell:
                self._hovered_cell = hovered_cell
                self._operation_view.viewport().update()
        return super().eventFilter(watched, event)

    def _is_editable_name_cell(self, index) -> bool:
        model = self._operation_view.model()
        return (
            index.isValid()
            and index.column() == 0
            and isinstance(model, _OperationFileModel)
            and model._pack_mode
        )

    @staticmethod
    def _cell_key(index) -> tuple[int, int]:
        return index.row(), index.column()

    @staticmethod
    def _button_rect(cell_rect: QRect) -> QRect:
        button_size = _ITEM_NAME_EDIT_BUTTON_WIDTH
        width = min(button_size, max(0, cell_rect.width() - 8))
        height = min(button_size, max(0, cell_rect.height() - 4))
        return QRect(
            cell_rect.right() - width - 3,
            cell_rect.center().y() - height // 2,
            width,
            height,
        )


# @arch mix-browser.shell-operation-file-model model | en: Presents selected shell files and their operation validation status | zh: 展示外壳传入的文件及操作校验状态
class _OperationFileModel(QAbstractTableModel):
    item_name_changed = Signal()

    def __init__(
        self,
        rows: Sequence[_OperationRow],
        headers: tuple[str, ...],
        *,
        pack_mode: bool,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows = rows
        self._headers = headers
        self._pack_mode = pack_mode

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            if self._pack_mode and index.column() == 0:
                view = self.parent()
                if isinstance(view, QTableView):
                    available_width = max(
                        0,
                        view.columnWidth(0) - _ITEM_NAME_EDIT_BUTTON_WIDTH - 20,
                    )
                    return QFontMetrics(view.font()).elidedText(
                        row.item_name,
                        Qt.TextElideMode.ElideRight,
                        available_width,
                    )
                return row.item_name
            values = (
                row.item_name if self._pack_mode else row.path.name,
                row.destination,
                row.status,
            )
            return values[index.column()]
        if (
            role == Qt.ItemDataRole.EditRole
            and self._pack_mode
            and index.column() == 0
        ):
            return row.item_name
        if role == Qt.ItemDataRole.ToolTipRole:
            if self._pack_mode and index.column() == 0:
                return f"{row.item_name}\n{row.path}"
            return str(row.path)
        if role == Qt.ItemDataRole.ForegroundRole:
            return base_status_color("success" if row.valid else "error")
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if self._pack_mode and index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(
        self,
        index: QModelIndex,
        value,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if (
            role != Qt.ItemDataRole.EditRole
            or not index.isValid()
            or index.column() != 0
            or not (0 <= index.row() < len(self._rows))
        ):
            return False
        row = self._rows[index.row()]
        if not self._pack_mode:
            return False
        item_name = str(value)
        if item_name == row.item_name:
            return True
        row.item_name = item_name
        self.dataChanged.emit(
            index,
            index,
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.EditRole,
                Qt.ItemDataRole.ForegroundRole,
                Qt.ItemDataRole.ToolTipRole,
            ],
        )
        self.item_name_changed.emit()
        return True

    def refresh_rows(self) -> None:
        if not self._rows:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._rows) - 1, len(self._headers) - 1),
            [
                Qt.ItemDataRole.DisplayRole,
                Qt.ItemDataRole.ForegroundRole,
                Qt.ItemDataRole.ToolTipRole,
            ],
        )

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and 0 <= section < len(self._headers)
        ):
            return self._headers[section]
        if (
            role == Qt.ItemDataRole.ToolTipRole
            and orientation == Qt.Orientation.Horizontal
            and section == 0
            and self._pack_mode
        ):
            return self.tr(
                "Click the pencil icon or double-click a MIX item name to edit it."
            )
        return None


class _OperationSignals(QObject):
    completed = Signal(object)
    cancellation_requested = Signal()


# @arch mix-browser.shell-basic-operation-dialog component | en: Runs shell-launched packing or extraction without constructing the main browser window | zh: 不构建主浏览器窗口，执行由外壳启动的打包或解包操作
class ShellBasicOperationDialog(QDialog):
    automatic_operation_finished = Signal()
    _SHOW_ONLY_ON_ISSUES_KEY = SHOW_BASIC_OPERATION_DIALOG_ONLY_ON_ISSUES_KEY

    def __init__(
        self,
        operation: str,
        paths: tuple[Path, ...],
        application_api: MixBrowserApplication,
        progress_controller: TaskProgressController,
        executor: ThreadPoolExecutor,
        settings: QSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._operation = operation
        self._paths = tuple(path.expanduser().absolute() for path in paths)
        self._application_api = application_api
        self._progress_controller = progress_controller
        self._executor = executor
        self._settings = settings
        self._signals = _OperationSignals(self)
        self._signals.completed.connect(self._finish_operation)
        self._signals.cancellation_requested.connect(self._show_cancellation_status)
        self._cancellation = Event()
        self._future: Future | None = None
        self._pending_work: Callable[[], object] | None = None
        self._progress: TaskProgressDialog | None = None
        self._completed = False
        self._automatic_operation = False
        self._automatic_success_waiting = False
        self._progress_unavailable = False
        self._result_code = 0
        self._overwrite = False
        self._destination_directory = _common_parent(self._paths)
        self._rows = self._build_rows()

        self.setWindowTitle(self.tr("MIX File Operation"))
        self.setMinimumSize(620, 420)
        available = self.screen().availableGeometry()
        self.resize(
            min(760, available.width() - 32),
            min(600, available.height() - 64),
        )

        layout = QVBoxLayout(self)
        if self._operation in {"pack-copy", "pack-move"}:
            self._build_pack_form(layout)
        else:
            self._build_extract_form(layout)
        self._status = _ScrollingResultLabel(self)
        self._status.setFixedHeight(30)
        self._status.setProperty("visualRole", "description")

        self._table = QTableView(self)
        self._file_model = _OperationFileModel(
            self._rows,
            (
                self.tr("MIX item name")
                if self._operation in {"pack-copy", "pack-move"}
                else self.tr("Selected file"),
                self.tr("Output"),
                self.tr("Validation"),
            ),
            pack_mode=self._operation in {"pack-copy", "pack-move"},
            parent=self._table,
        )
        self._file_delegate = _OperationFileDelegate(
            self._table,
            self.tr("Edit MIX item name"),
        )
        self._file_model.item_name_changed.connect(self._refresh_validation)
        self._table.setModel(self._file_model)
        self._table.setItemDelegate(self._file_delegate)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableView.EditTrigger.DoubleClicked)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 170)
        header.resizeSection(2, 220)
        layout.addWidget(self._table, 1)

        buttons = QDialogButtonBox(self)
        self._action_button = buttons.addButton(
            self.tr("Create MIX")
            if self._operation in {"pack-copy", "pack-move"}
            else self.tr("Extract"),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._action_button.clicked.connect(self._on_action)
        self._cancel_button.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(self._status, 1)
        self._issues_only_checkbox: QCheckBox | None = None
        if self._operation in {"pack-copy", "pack-move", "extract-containers"}:
            self._issues_only_checkbox = QCheckBox(
                self.tr("Only show this window when there are conflicts or errors"),
                self,
            )
            self._issues_only_checkbox.setChecked(
                self._settings.value(
                    self._SHOW_ONLY_ON_ISSUES_KEY,
                    False,
                    type=bool,
                )
            )
            self._issues_only_checkbox.toggled.connect(
                self._save_issues_only_preference
            )
            footer.addWidget(self._issues_only_checkbox)
        footer.addWidget(buttons)
        layout.addLayout(footer)
        self._refresh_validation()

    @property
    def result_code(self) -> int:
        return self._result_code

    @property
    def can_run_without_dialog(self) -> bool:
        if (
            self._issues_only_checkbox is None
            or not self._issues_only_checkbox.isChecked()
        ):
            return False
        if not self._rows or not all(row.valid for row in self._rows):
            return False
        if self._operation in {"pack-copy", "pack-move"}:
            output_path = self._output_path.text()
            return bool(output_path) and not os.path.lexists(output_path)
        return self._operation == "extract-containers"

    def _save_issues_only_preference(self, checked: bool) -> None:
        self._settings.setValue(self._SHOW_ONLY_ON_ISSUES_KEY, checked)
        self._settings.sync()

    def start_without_dialog(self) -> None:
        self._refresh_validation()
        if not self.can_run_without_dialog:
            self.show()
            return
        self._automatic_operation = True
        if self._operation in {"pack-copy", "pack-move"}:
            self._start_pack()
        else:
            self._start_extract()

    def _build_pack_form(self, layout: QVBoxLayout) -> None:
        description = QLabel(
            self.tr(
                "Selected files will become items inside a new MIX archive. MIX uses hashed item names; this application supports printable ASCII names up to 260 characters."
            ),
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self._name_edit = QLineEdit("New Archive.mix", self)
        self._name_edit.textChanged.connect(self._refresh_validation)
        priority_hint = add_mix_name_template_controls(
            layout,
            self._name_edit,
            include_mix_suffix=True,
            quick_fill_label=self.tr("Quick fill:"),
            ra2_button_label=self.tr("RA2: expand30"),
            yr_button_label=self.tr("YR: expandmd30"),
            priority_hint=self.tr(
                "RA2 uses expand##.mix; Yuri's Revenge uses expandmd##.mix. "
                "The engine loads numbered expansion MIX archives from 99 down "
                "to 00. Higher numbers mount earlier and take priority when "
                "member names collide."
            ),
        )
        form = QFormLayout()
        self._output_path = QLabel(self)
        self._output_path.setWordWrap(True)
        form.addRow(self.tr("New MIX name:"), self._name_edit)
        form.addRow(self.tr("Location:"), self._output_path)
        layout.addLayout(form)
        layout.addWidget(priority_hint)

    def _build_extract_form(self, layout: QVBoxLayout) -> None:
        description = QLabel(
            self.tr(
                "Selected containers will be extracted into same-name folders beside the source files. Existing folders are never replaced."
            ),
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(description)

    def _build_rows(self) -> tuple[_OperationRow, ...]:
        if self._operation in {"pack-copy", "pack-move"}:
            return self._build_pack_rows()
        return self._build_extract_rows()

    def _build_pack_rows(self) -> tuple[_OperationRow, ...]:
        common_parent = self._destination_directory
        rows = []
        for path in self._paths:
            status = self._pack_file_status(path)
            rows.append(
                _OperationRow(
                    path=path,
                    item_name=path.name,
                    destination=str(common_parent) if common_parent else "",
                    status=status,
                    valid=status == self.tr("Ready"),
                )
            )
        return tuple(rows)

    def _pack_file_status(self, path: Path, item_name: str | None = None) -> str:
        item_name = path.name if item_name is None else item_name
        try:
            metadata = path.stat()
        except OSError:
            return self.tr("File is unavailable.")
        if not stat.S_ISREG(metadata.st_mode):
            return self.tr("Only regular files can be added to a MIX archive.")
        if not is_readable_mix_name(item_name):
            return self.tr(
                "Name must use printable ASCII characters, be at most 260 characters, and contain no unsupported symbols or surrounding spaces."
            )
        if item_name.casefold() == LOCAL_MIX_DATABASE_NAME.casefold():
            return self.tr("Name is reserved for the embedded MIX name database.")
        return self.tr("Ready")

    def _build_extract_rows(self) -> tuple[_OperationRow, ...]:
        statuses = [self._extract_file_status(path) for path in self._paths]
        targets: dict[str, list[int]] = {}
        for index, path in enumerate(self._paths):
            targets.setdefault(path.stem.casefold(), []).append(index)
        for indices in targets.values():
            if len(indices) > 1:
                for index in indices:
                    statuses[index] = self.tr("Selected containers produce the same folder name.")
        common_parent = self._destination_directory
        if common_parent is None:
            statuses = [
                self.tr("Selected containers must be in the same folder.")
                for _path in self._paths
            ]
        return tuple(
            _OperationRow(
                path=path,
                item_name=path.name,
                destination=(
                    str(common_parent / path.stem)
                    if common_parent
                    else path.stem
                ),
                status=status,
                valid=status == self.tr("Ready"),
            )
            for path, status in zip(self._paths, statuses, strict=True)
        )

    def _extract_file_status(self, path: Path) -> str:
        if path.suffix.casefold() not in MIX_CONTAINER_SUFFIXES:
            return self.tr("File is not a supported MIX-family container.")
        try:
            metadata = path.stat()
        except OSError:
            return self.tr("Container file is unavailable.")
        if not stat.S_ISREG(metadata.st_mode):
            return self.tr("Only container files can be extracted.")
        if not is_valid_leaf_name(path.stem):
            return self.tr("Container name cannot be used for an output folder.")
        output = path.parent.resolve() / path.stem
        if os.path.lexists(output):
            return self.tr("Output folder already exists.")
        return self.tr("Ready")

    def _refresh_validation(self, *_arguments) -> None:
        if not hasattr(self, "_action_button"):
            return
        if self._operation in {"pack-copy", "pack-move"}:
            self._refresh_pack_rows()
        output_valid = True
        if self._operation in {"pack-copy", "pack-move"}:
            self._refresh_pack_output()
        rows_valid = bool(self._rows) and all(row.valid for row in self._rows)
        if rows_valid and self._operation in {"pack-copy", "pack-move"}:
            output_valid = self._output_is_valid()
        self._action_button.setEnabled(rows_valid and output_valid)
        if not self._rows:
            self._set_status(self.tr("No files were selected."), valid=False)
        elif not rows_valid:
            self._set_status(
                self.tr("Review the highlighted items before continuing."),
                valid=False,
            )
        elif not output_valid:
            return
        elif (
            self._operation in {"pack-copy", "pack-move"}
            and self._output_path.text()
            and os.path.isfile(self._output_path.text())
        ):
            self._set_status(
                self.tr("The output file exists; confirmation will be required to replace it."),
                valid=True,
            )
        else:
            self._set_status(self.tr("All selected items are ready."), valid=True)

    def _refresh_pack_rows(self) -> None:
        ready = self.tr("Ready")
        statuses = [
            self._pack_file_status(row.path, row.item_name)
            for row in self._rows
        ]
        duplicate_name = self.tr("Selected files have duplicate names.")
        duplicate_id = self.tr("Selected names resolve to the same MIX item ID.")
        reserved_id = self.tr("Name conflicts with the reserved MIX name database ID.")

        name_indices: dict[str, list[int]] = {}
        for index, row in enumerate(self._rows):
            if statuses[index] == ready:
                name_indices.setdefault(row.item_name.casefold(), []).append(index)
        for indices in name_indices.values():
            if len(indices) > 1:
                for index in indices:
                    statuses[index] = duplicate_name

        try:
            database_id = mix_file_ids_for_new_archive((LOCAL_MIX_DATABASE_NAME,))[0]
        except (UnicodeError, ValueError):
            database_id = -1
        id_indices: dict[int, list[int]] = {}
        for index, row in enumerate(self._rows):
            if statuses[index] != ready:
                continue
            try:
                file_id = mix_file_ids_for_new_archive((row.item_name,))[0]
            except (UnicodeError, ValueError):
                continue
            id_indices.setdefault(file_id, []).append(index)
            if file_id == database_id:
                statuses[index] = reserved_id
        for indices in id_indices.values():
            if len(indices) > 1:
                for index in indices:
                    statuses[index] = duplicate_id

        common_parent = self._destination_directory is not None
        if not common_parent:
            statuses = [
                self.tr("Selected files must be in the same folder.")
                for _row in self._rows
            ]
        for row, status in zip(self._rows, statuses, strict=True):
            row.status = status
            row.valid = status == ready
        self._file_model.refresh_rows()

    def _refresh_pack_output(self) -> None:
        name = self._name_edit.text().strip()
        if name and not Path(name).suffix:
            name += ".mix"
        output = self._destination_directory / name if self._destination_directory and name else None
        self._output_path.setText(str(output) if output else "")

    def _output_is_valid(self) -> bool:
        if self._operation not in {"pack-copy", "pack-move"}:
            return True
        name = self._name_edit.text().strip()
        if not name:
            self._set_status(self.tr("Enter a MIX archive name."), valid=False)
            return False
        if not Path(name).suffix:
            name += ".mix"
        if Path(name).suffix.casefold() != ".mix" or not is_valid_leaf_name(name):
            self._set_status(self.tr("Enter a valid .mix file name."), valid=False)
            return False
        if self._destination_directory is None:
            return False
        target = self._destination_directory / name
        try:
            target_key = os.path.normcase(str(target.resolve(strict=False)))
            source_keys = {
                os.path.normcase(str(path.resolve(strict=False)))
                for path in self._paths
            }
        except (OSError, RuntimeError):
            self._set_status(self.tr("The output path cannot be resolved."), valid=False)
            return False
        if target_key in source_keys:
            self._set_status(self.tr("The output archive cannot replace a selected source file."), valid=False)
            return False
        if os.path.lexists(target):
            if target.is_symlink() or not target.is_file():
                self._set_status(self.tr("The output path is not a regular file."), valid=False)
                return False
            self._set_status(self.tr("The output file exists; confirmation will be required to replace it."), valid=True)
        return True

    def _set_status(self, message: str, *, valid: bool) -> None:
        self._status.set_message(message)
        set_semantic_status_style(
            self._status,
            "success" if valid else "error",
            background_role=QPalette.ColorRole.Window,
        )

    def _on_action(self) -> None:
        if self._completed:
            self.accept()
            return
        if self._future is not None:
            return
        if self._operation in {"pack-copy", "pack-move"}:
            self._start_pack()
        else:
            self._start_extract()

    def _start_pack(self) -> None:
        if not self._output_is_valid() or self._destination_directory is None:
            return
        name = self._name_edit.text().strip()
        if not Path(name).suffix:
            name += ".mix"
        target = self._destination_directory / name
        if os.path.lexists(target):
            if self._automatic_operation:
                self._automatic_operation = False
                self.show()
                self._refresh_validation()
                return
            answer = QMessageBox.question(
                self,
                self.tr("Replace Existing MIX Archive?"),
                self.tr('A file named "{0}" already exists. Replace it?').format(name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._overwrite = True
        self._begin_operation(
            self.tr("Creating MIX Archive"),
            self.tr("Creating {0} from {1} selected file(s)...").format(
                name,
                len(self._paths),
            ),
            lambda: self._application_api.create_mix_from_files(
                target,
                self._paths,
                item_names=tuple(row.item_name for row in self._rows),
                move_sources=self._operation == "pack-move",
                overwrite=self._overwrite,
                cancellation_requested=self._cancellation.is_set,
            ),
        )

    def _start_extract(self) -> None:
        self._begin_operation(
            self.tr("Extracting Containers"),
            self.tr("Extracting {0} selected container(s)...").format(len(self._paths)),
            lambda: self._application_api.extract_mix_archives_to_folders(
                self._paths,
                self._destination_directory,
                cancellation_requested=self._cancellation.is_set,
            ),
        )

    def _begin_operation(self, title: str, message: str, work) -> None:
        self._cancellation.clear()
        self._progress_unavailable = False
        self._pending_work = work
        self._action_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self._table.setEnabled(False)
        if hasattr(self, "_name_edit"):
            self._name_edit.setEnabled(False)
        self._set_status(self.tr("Working... Cancel from the progress window to stop safely."), valid=True)
        self._progress = TaskProgressDialog(
            self._progress_controller,
            title,
            message,
            mode=ProgressMode.INDETERMINATE,
            cancel_callback=self._request_cancellation,
            cancelable=True,
            parent=self,
        )
        self._progress.shown.connect(self._start_pending_operation)
        self._progress.hidden.connect(self._on_progress_hidden)
        self._progress.helper_unavailable.connect(self._handle_progress_unavailable)
        self._progress.show()

    # @arch mix-browser.shell-operation-progress-ready handler | en: Starts an operation after its progress window is visible | zh: 在进度窗可见后启动操作
    def _start_pending_operation(self) -> None:
        work = self._pending_work
        if work is None or self._progress_unavailable or self._future is not None:
            return
        self._pending_work = None
        self._future = self._executor.submit(work)
        self._future.add_done_callback(self._signals.completed.emit)

    def _request_cancellation(self) -> None:
        self._cancellation.set()
        self._signals.cancellation_requested.emit()

    def _show_cancellation_status(self) -> None:
        if self._future is not None and not self._future.done():
            self._set_status(self.tr("Cancellation requested; waiting for a safe stop..."), valid=False)

    def _handle_progress_unavailable(self) -> None:
        self._progress_unavailable = True
        if not self._completed:
            self._set_status(
                self.tr(
                    "The shared progress window is unavailable; the operation could not be started."
                ),
                valid=False,
            )
        progress = self._progress
        self._progress = None
        if progress is not None:
            progress.deleteLater()
        if self._pending_work is not None:
            self._pending_work = None
            self._action_button.setEnabled(True)
            self._cancel_button.setEnabled(True)
            self._table.setEnabled(True)
            if hasattr(self, "_name_edit"):
                self._name_edit.setEnabled(True)
            if self._automatic_operation:
                self._automatic_operation = False
                self.show()
        if self._automatic_success_waiting:
            self._automatic_success_waiting = False
            self._automatic_operation = False
            self.show()

    def _on_progress_hidden(self) -> None:
        self._progress = None
        if self._automatic_success_waiting:
            self._automatic_success_waiting = False
            self.automatic_operation_finished.emit()

    def _finish_operation(self, future: Future) -> None:
        self._future = None
        try:
            result = future.result()
        except InterruptedError:
            self._set_status(self.tr("Operation cancelled."), valid=False)
            self._result_code = 1
        except Exception as exc:
            self._set_status(self.tr("Operation failed: {0}").format(exc), valid=False)
            self._result_code = 1
        else:
            self._show_result(result)
        self._completed = True
        self._action_button.setText(self.tr("Close"))
        self._action_button.setEnabled(True)
        self._cancel_button.hide()
        if hasattr(self, "_name_edit"):
            self._name_edit.setEnabled(False)
        automatic_success = (
            self._automatic_operation
            and self._result_code == 0
            and not self._progress_unavailable
        )
        progress = self._progress
        self._automatic_success_waiting = automatic_success and progress is not None
        if progress is not None:
            if automatic_success:
                progress.finish(
                    self.tr("Completed."),
                    dismiss_delay_ms=500,
                )
            else:
                progress.finish()
        if self._automatic_operation:
            if self._result_code == 0 and not self._progress_unavailable:
                if not self._automatic_success_waiting:
                    self.automatic_operation_finished.emit()
                return
            self._automatic_operation = False
            self.show()

    def _show_result(self, result: dict[str, object]) -> None:
        if self._operation == "extract-containers":
            self._set_status(
                self.tr("Extracted {0} file(s) into {1} folder(s).").format(
                    result.get("extracted_file_count", 0),
                    len(result.get("created_paths", ())),
                ),
                valid=True,
            )
            return
        archive_name = Path(str(result.get("archive_path", ""))).name
        if result.get("source_move_complete"):
            self._set_status(
                self.tr("Created {0} and moved {1} file(s).").format(
                    archive_name,
                    result.get("entry_count", 0),
                ),
                valid=True,
            )
        elif result.get("source_move_failures"):
            details = "; ".join(str(item) for item in result["source_move_failures"])
            self._set_status(
                self.tr("Created {0}, but some source files could not be moved: {1}").format(
                    archive_name,
                    details,
                ),
                valid=False,
            )
            self._result_code = 1
        elif result.get("source_move_cancelled"):
            removed_count = len(result.get("removed_source_paths", ()))
            remaining_count = len(result.get("remaining_source_paths", ()))
            self._set_status(
                self.tr(
                    "Created {0}; source removal was cancelled after removing "
                    "{1} file(s), and {2} remain."
                ).format(archive_name, removed_count, remaining_count),
                valid=False,
            )
            self._result_code = 1
        else:
            self._set_status(
                self.tr("Created {0} with {1} file(s); source files were kept.").format(
                    archive_name,
                    result.get("entry_count", 0),
                ),
                valid=True,
            )

    def closeEvent(self, event) -> None:
        if self._future is not None:
            self._request_cancellation()
            event.ignore()
            return
        self._discard_pending_operation()
        super().closeEvent(event)

    def reject(self) -> None:
        if self._future is not None:
            self._request_cancellation()
            return
        self._discard_pending_operation()
        super().reject()

    def _discard_pending_operation(self) -> None:
        if self._pending_work is None:
            return
        self._pending_work = None
        if self._progress is not None:
            self._progress.finish()


def _common_parent(paths: tuple[Path, ...]) -> Path | None:
    if not paths:
        return None
    try:
        parents = {path.parent.resolve() for path in paths}
    except (OSError, RuntimeError):
        return None
    return next(iter(parents)) if len(parents) == 1 else None
