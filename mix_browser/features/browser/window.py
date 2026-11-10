from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import CancelledError, Executor, Future
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING
from uuid import uuid4

from PySide6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QMimeData,
    QPoint,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCloseEvent,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mix_browser.features.archive.domain import (
    MixArchiveIndex,
    MixArchiveParent,
    MixEntry,
    MixFormatError,
    LOCAL_MIX_DATABASE_NAME,
    is_readable_mix_name,
)
from mix_browser.features.archive.api import MixArchiveApplication
from mix_browser.features.archive.loader import MixArchiveLoader
from mix_browser.features.archive.name_catalog import (
    DEFAULT_MIX_NAME_GAME,
    MIX_NAME_GAME_GROUPS,
    XCC_NAME_GAME_KEYS,
    community_name_database_path,
)
from mix_browser.features.archive.type_detection import (
    MIX_CONTAINER_SUFFIXES,
    detect_content_type,
)
from mix_browser.features.browser.directory_model import (
    DirectoryEntry,
    DirectoryEntryTableModel,
    load_directory_entries,
)
from mix_browser.features.browser.directory_operations import (
    is_valid_leaf_name,
)
from mix_browser.features.archive.writer import (
    ExternalFileChangedError,
    NoExternalChangesError,
    mix_file_ids_for_archive,
    write_back_mix_entry,
)
from mix_browser.features.browser.about_dialog import AboutDialog
from mix_browser.features.browser.api import MixBrowserFeatureApplication
from mix_browser.features.browser.asset_preview import (
    EntryPreviewResult,
    PaletteLibraryRule,
    game_palette_catalog_directory_key,
    game_palette_catalog_is_ready_or_loading,
    load_entry_palette_update,
    load_entry_preview,
    load_game_palette_catalog_snapshot,
    load_path_palette_update,
    load_path_preview,
    mark_game_palette_catalog_scheduled,
    refresh_game_palette_catalog,
)
from mix_browser.features.browser.formatting import format_byte_size
from mix_browser.features.browser.palette_naming_guide import (
    PaletteNamingGuideDialog,
)
from mix_browser.features.browser.preview_support import PreviewSupportDialog
from mix_browser.features.browser.entry_table import EntryTable
from mix_browser.features.browser.file_type_support import (
    CONFIGURABLE_BROWSER_TYPE_FILTERS,
    DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS,
    OTHER_FILE_TYPE_FILTER,
)
from mix_browser.features.browser.recursive_search import (
    ArchivePageLocation,
    DirectoryPageLocation,
    SearchHit,
    SearchOutcome,
    SearchRoot,
    search_from_root,
)
from mix_browser.features.browser.search_dialog import SearchResultsDialog
from mix_browser.features.browser.temporary_files import (
    TemporaryFileCleanupResult,
    clean_temporary_files,
    count_temporary_files,
)
from mix_browser.features.browser.temporary_files_preferences import (
    TemporaryFilesSettingsPage,
)
from mix_browser.features.system_integration.api import SystemIntegrationApplication
from mix_browser.features.system_integration.open_with_dialog import (
    cleanup_container_association_probe_result,
    consume_container_association_probe_result,
    create_container_association_probe,
)
from mix_browser.features.system_integration.preferences import (
    ContainerDefaultHandlerDialog,
    SystemIntegrationSettingsPage,
)
from mix_browser.features.browser.external_open import (
    ExtractedEntry,
    extract_entries_for_drag,
    extract_entry_to_temporary_file,
    hash_file,
    load_archive_chain,
    prepare_search_hit_targets,
    reload_archive_indexes,
)
from mix_browser.features.browser.rounded_row_delegate import RoundedRowDelegate
from mix_browser.features.browser.system_icons import system_icon_for_object
from mix_browser.features.browser.table_model import MixEntryTableModel
from mix_browser.shared.task_progress_dialog import (
    ProgressMode,
    TaskProgressController,
    TaskCancellationToken,
    TaskProgressDialog,
)
from mix_browser.shared.application_identity import APPLICATION_DISPLAY_NAME
from mix_browser.shared.application_errors import ApplicationApiError
from mix_browser.shared.application_settings import (
    application_directory,
    create_application_settings,
)
from mix_browser.shared.file_operations import replace_path_with_staged_sibling
from mix_browser.shared.interaction_help import InteractionHelpCatalog

if TYPE_CHECKING:
    from mix_browser.features.browser.entry_preview import EntryPreviewPane


# @arch mix-browser.entry-preview-factory utility | en: Creates the preview widget on the UI thread | zh: 在 UI 线程创建预览控件
def _create_entry_preview(parent: QWidget) -> EntryPreviewPane:
    from mix_browser.features.browser.entry_preview import EntryPreviewPane

    return EntryPreviewPane(parent)


def _remove_stale_clipboard_exports(
    roots: tuple[Path, ...],
    cancellation: Event,
) -> None:
    for root in roots:
        if cancellation.is_set():
            return
        shutil.rmtree(root, ignore_errors=True)


class MixArchivePage(QWidget):
    navigate_requested = Signal(str)
    preview_requested = Signal(object)
    preview_state_changed = Signal()
    filter_state_changed = Signal()
    context_menu_requested = Signal(object)
    drag_requested = Signal()
    drag_cancelled = Signal()

    def __init__(
        self,
        archive: MixArchiveIndex,
        page_key: str,
        display_title: str,
        ancestors: tuple[tuple[str, str], ...] = (),
        location_text: str | None = None,
        parent: QWidget | None = None,
        preview: EntryPreviewPane | None = None,
    ) -> None:
        super().__init__(parent)
        self.archive = archive
        self.path_key = page_key
        self.display_title = display_title
        self.ancestors = ancestors
        self.location_text = location_text or str(archive.path)
        self._ancestor_buttons: dict[str, QToolButton] = {}

        self.entry_table = EntryTable(MixEntryTableModel(archive.entries), self)
        self.entry_table.filter_changed.connect(self.filter_state_changed.emit)
        self.table = self.entry_table.table
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.entry_table.context_menu_requested.connect(self.context_menu_requested.emit)
        self.entry_table.drag_requested.connect(self.drag_requested.emit)
        self.entry_table.drag_cancelled.connect(self.drag_cancelled.emit)
        self._row_delegate = RoundedRowDelegate(self.table)
        self.table.setItemDelegate(self._row_delegate)
        self.table.selectionModel().currentChanged.connect(self._on_current_entry_changed)
        self._preview_request_id: int | None = None
        self._preview_entry: MixEntry | None = None
        self._preview_result: EntryPreviewResult | None = None
        self._preview_encoding = "ansi"
        self._preview_line_endings = "Unknown"
        self._preview_pending = False

        self.preview = preview if preview is not None else _create_entry_preview(self)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.entry_table)
        self.content_splitter.addWidget(self.preview)
        self.preview.show()
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([640, 384])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.breadcrumb_bar = QWidget(self)
        breadcrumb_layout = QHBoxLayout(self.breadcrumb_bar)
        self._breadcrumb_layout = breadcrumb_layout
        breadcrumb_layout.setContentsMargins(8, 4, 8, 4)
        breadcrumb_layout.setSpacing(4)
        self._rebuild_breadcrumbs()
        layout.addWidget(self.breadcrumb_bar)
        layout.addWidget(self.content_splitter, 1)

    def set_navigation_context(
        self,
        ancestors: tuple[tuple[str, str], ...],
        location_text: str | None = None,
    ) -> None:
        if self.ancestors == ancestors and (
            location_text is None or self.location_text == location_text
        ):
            return
        self.ancestors = ancestors
        if location_text is not None:
            self.location_text = location_text
        self._rebuild_breadcrumbs()

    def _rebuild_breadcrumbs(self) -> None:
        while self._breadcrumb_layout.count():
            item = self._breadcrumb_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._ancestor_buttons.clear()
        for ancestor_key, ancestor_title in self.ancestors:
            button = QToolButton(self.breadcrumb_bar)
            button.setObjectName("BreadcrumbButton")
            button.setText(ancestor_title)
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(
                lambda _checked=False, key=ancestor_key: self.navigate_requested.emit(key)
            )
            self._ancestor_buttons[ancestor_key] = button
            self._breadcrumb_layout.addWidget(button)
            separator = QLabel(self.tr(">"), self.breadcrumb_bar)
            separator.setObjectName("BreadcrumbSeparator")
            self._breadcrumb_layout.addWidget(separator)
        current = QLabel(self.display_title, self.breadcrumb_bar)
        current.setObjectName("CurrentBreadcrumb")
        self._breadcrumb_layout.addWidget(current)
        self._breadcrumb_layout.addStretch(1)
        self.breadcrumb_bar.setVisible(bool(self.ancestors))

    def _on_current_entry_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        model = self.entry_table.source_model
        source_index = current
        entry = (
            model.entry_at(source_index.row())
            if source_index.isValid() and isinstance(model, MixEntryTableModel)
            else None
        )
        self.preview_requested.emit(entry)

    @property
    def preview_entry(self) -> MixEntry | None:
        return self._preview_entry

    def current_entry(self) -> MixEntry | None:
        current = self.table.currentIndex()
        model = self.entry_table.source_model
        if not current.isValid() or not isinstance(model, MixEntryTableModel):
            return None
        return model.entry_at(current.row())

    def show_preview_loading(self, request_id: int, entry: MixEntry) -> None:
        self._preview_request_id = request_id
        self._preview_entry = entry
        self._preview_result = None
        self._preview_encoding = "ansi"
        self._preview_line_endings = "Unknown"
        self._preview_pending = True
        self.preview.show_loading()
        self.preview_state_changed.emit()

    def show_preview_result(self, request_id: int, result: EntryPreviewResult) -> None:
        if request_id != self._preview_request_id:
            return
        self._preview_result = result
        document = result.document
        self._preview_encoding = document.detected_encoding if document is not None else "ansi"
        self._preview_pending = False
        decoded = self.preview.show_result(result, self._preview_encoding)
        self._preview_line_endings = decoded.line_endings if decoded is not None else "Unknown"
        self.preview_state_changed.emit()

    def update_preview_palette_result(
        self,
        request_id: int,
        result: EntryPreviewResult,
    ) -> None:
        if request_id != self._preview_request_id:
            return
        self._preview_result = result
        self.preview.update_palette_sources(result)
        self.preview_state_changed.emit()

    def clear_preview(self) -> None:
        self._preview_request_id = None
        self._preview_entry = None
        self._preview_result = None
        self._preview_encoding = "ansi"
        self._preview_line_endings = "Unknown"
        self._preview_pending = False
        self.preview.show_empty()
        self.preview_state_changed.emit()

    def replace_archive(self, archive: MixArchiveIndex) -> None:
        self.preview_requested.emit(None)
        self.archive = archive
        model = self.entry_table.source_model
        if isinstance(model, MixEntryTableModel):
            selection = self.table.selectionModel()
            was_blocked = selection.blockSignals(True)
            model.replace_entries(archive.entries)
            selection.blockSignals(was_blocked)
        self.clear_preview()

    @property
    def preview_encoding(self) -> str:
        return self._preview_encoding

    @property
    def preview_encoding_enabled(self) -> bool:
        return (
            self._preview_result is not None
            and self._preview_result.document is not None
            and bool(self._preview_result.document.data)
        )

    @property
    def preview_status_text(self) -> str:
        entry = self._preview_entry
        if entry is None:
            return self.tr("Select an entry")
        name = entry.name or f"Unknown (0x{entry.file_id:08X})"
        parts = [name, self.tr(entry.file_type or "Unknown"), format_byte_size(entry.size)]
        if self._preview_pending:
            parts.append(self.tr("Loading preview..."))
        elif self._preview_result is not None:
            if self._preview_line_endings != "Unknown":
                parts.append(self.tr("EOL: {0}").format(self._preview_line_endings))
            elif self._preview_result.kind == "message":
                parts.append(self.tr("Preview unavailable"))
            if self._preview_result.document is not None and self._preview_result.document.truncated:
                parts.append(self.tr("Partial preview"))
            parts.extend(self.tr(detail) for detail in self._preview_result.details)
        return " | ".join(parts)

    def set_preview_encoding(self, encoding: str) -> None:
        result = self._preview_result
        document = result.document if result is not None else None
        if document is None or not document.data or encoding == self._preview_encoding:
            return
        self._preview_encoding = encoding
        decoded = self.preview.show_document(document, encoding)
        self._preview_line_endings = decoded.line_endings
        self.preview_state_changed.emit()

    def set_available_ancestor_keys(self, available_keys: set[str]) -> None:
        for key, button in self._ancestor_buttons.items():
            button.setEnabled(key in available_keys)

class DirectoryBrowserPage(QWidget):
    navigate_requested = Signal(str)
    preview_requested = Signal(object)
    preview_state_changed = Signal()
    filter_state_changed = Signal()
    context_menu_requested = Signal(object)
    drag_requested = Signal()
    drag_cancelled = Signal()

    def __init__(
        self,
        directory: Path,
        page_key: str,
        display_title: str,
        ancestors: tuple[tuple[str, str], ...] = (),
        parent: QWidget | None = None,
        preview: EntryPreviewPane | None = None,
    ) -> None:
        super().__init__(parent)
        self.directory = directory
        self.path_key = page_key
        self.display_title = display_title
        self.ancestors = ancestors
        self.location_text = str(directory)
        self._ancestor_buttons: dict[str, QToolButton] = {}
        self._directory_loading = True
        self._directory_error: str | None = None
        self._preview_request_id: int | None = None
        self._preview_entry: DirectoryEntry | None = None
        self._preview_result: EntryPreviewResult | None = None
        self._preview_encoding = "ansi"
        self._preview_line_endings = "Unknown"
        self._preview_pending = False

        self.entry_table = EntryTable(DirectoryEntryTableModel(parent=self), self)
        self.entry_table.filter_changed.connect(self.filter_state_changed.emit)
        self.table = self.entry_table.table
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.entry_table.context_menu_requested.connect(self.context_menu_requested.emit)
        self.entry_table.drag_requested.connect(self.drag_requested.emit)
        self.entry_table.drag_cancelled.connect(self.drag_cancelled.emit)
        self._row_delegate = RoundedRowDelegate(self.table)
        self.table.setItemDelegate(self._row_delegate)
        self.table.selectionModel().currentChanged.connect(self._on_current_entry_changed)

        self.preview = preview if preview is not None else _create_entry_preview(self)
        self.content_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.entry_table)
        self.content_splitter.addWidget(self.preview)
        self.preview.show()
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes([640, 384])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.breadcrumb_bar = QWidget(self)
        breadcrumb_layout = QHBoxLayout(self.breadcrumb_bar)
        self._breadcrumb_layout = breadcrumb_layout
        breadcrumb_layout.setContentsMargins(8, 4, 8, 4)
        breadcrumb_layout.setSpacing(4)
        self._rebuild_breadcrumbs()
        layout.addWidget(self.breadcrumb_bar)
        layout.addWidget(self.content_splitter, 1)

    def set_navigation_context(
        self,
        ancestors: tuple[tuple[str, str], ...],
    ) -> None:
        if self.ancestors == ancestors:
            return
        self.ancestors = ancestors
        self._rebuild_breadcrumbs()

    def _rebuild_breadcrumbs(self) -> None:
        while self._breadcrumb_layout.count():
            item = self._breadcrumb_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._ancestor_buttons.clear()
        for ancestor_key, ancestor_title in self.ancestors:
            button = QToolButton(self.breadcrumb_bar)
            button.setObjectName("BreadcrumbButton")
            button.setText(ancestor_title)
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.clicked.connect(
                lambda _checked=False, key=ancestor_key: self.navigate_requested.emit(key)
            )
            self._ancestor_buttons[ancestor_key] = button
            self._breadcrumb_layout.addWidget(button)
            self._breadcrumb_layout.addWidget(QLabel(self.tr(">"), self.breadcrumb_bar))
        current = QLabel(self.display_title, self.breadcrumb_bar)
        current.setObjectName("CurrentBreadcrumb")
        self._breadcrumb_layout.addWidget(current)
        self._breadcrumb_layout.addStretch(1)
        self.breadcrumb_bar.setVisible(bool(self.ancestors))

    def show_directory_result(self, entries: tuple[DirectoryEntry, ...], error: str = "") -> None:
        self._directory_loading = False
        self._directory_error = error or None
        model = self.entry_table.source_model
        if isinstance(model, DirectoryEntryTableModel):
            model.replace_entries(entries)
        self.preview_state_changed.emit()

    def _on_current_entry_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        source_index = current
        model = self.entry_table.source_model
        entry = (
            model.entry_at(source_index.row())
            if source_index.isValid() and isinstance(model, DirectoryEntryTableModel)
            else None
        )
        self.preview_requested.emit(entry)

    @property
    def preview_entry(self) -> DirectoryEntry | None:
        return self._preview_entry

    def current_entry(self) -> DirectoryEntry | None:
        current = self.table.currentIndex()
        model = self.entry_table.source_model
        if not current.isValid() or not isinstance(model, DirectoryEntryTableModel):
            return None
        return model.entry_at(current.row())

    def show_preview_loading(self, request_id: int, entry: DirectoryEntry) -> None:
        self._preview_request_id = request_id
        self._preview_entry = entry
        self._preview_result = None
        self._preview_encoding = "ansi"
        self._preview_line_endings = "Unknown"
        self._preview_pending = True
        self.preview.show_loading()
        self.preview_state_changed.emit()

    def show_preview_result(self, request_id: int, result: EntryPreviewResult) -> None:
        if request_id != self._preview_request_id:
            return
        self._preview_result = result
        document = result.document
        self._preview_encoding = document.detected_encoding if document is not None else "ansi"
        self._preview_pending = False
        decoded = self.preview.show_result(result, self._preview_encoding)
        self._preview_line_endings = decoded.line_endings if decoded is not None else "Unknown"
        self.preview_state_changed.emit()

    def update_preview_palette_result(
        self,
        request_id: int,
        result: EntryPreviewResult,
    ) -> None:
        if request_id != self._preview_request_id:
            return
        self._preview_result = result
        self.preview.update_palette_sources(result)
        self.preview_state_changed.emit()

    def clear_preview(self) -> None:
        self._preview_request_id = None
        self._preview_entry = None
        self._preview_result = None
        self._preview_encoding = "ansi"
        self._preview_line_endings = "Unknown"
        self._preview_pending = False
        self.preview.show_empty()
        self.preview_state_changed.emit()

    @property
    def preview_encoding(self) -> str:
        return self._preview_encoding

    @property
    def preview_encoding_enabled(self) -> bool:
        return (
            self._preview_result is not None
            and self._preview_result.document is not None
            and bool(self._preview_result.document.data)
        )

    @property
    def preview_status_text(self) -> str:
        if self._directory_loading:
            return self.tr("Loading folder...")
        if self._directory_error:
            return self.tr("Unable to read folder: {0}").format(self._directory_error)
        entry = self._preview_entry
        if entry is None:
            return self.tr("Select an entry")
        parts = [entry.path.name, self.tr(entry.file_type), format_byte_size(entry.size)]
        if self._preview_pending:
            parts.append(self.tr("Loading preview..."))
        elif self._preview_result is not None:
            if self._preview_line_endings != "Unknown":
                parts.append(self.tr("EOL: {0}").format(self._preview_line_endings))
            elif self._preview_result.kind == "message":
                parts.append(self.tr("Preview unavailable"))
            if self._preview_result.document is not None and self._preview_result.document.truncated:
                parts.append(self.tr("Partial preview"))
            parts.extend(self.tr(detail) for detail in self._preview_result.details)
        return " | ".join(parts)

    def set_preview_encoding(self, encoding: str) -> None:
        result = self._preview_result
        document = result.document if result is not None else None
        if document is None or not document.data or encoding == self._preview_encoding:
            return
        self._preview_encoding = encoding
        decoded = self.preview.show_document(document, encoding)
        self._preview_line_endings = decoded.line_endings
        self.preview_state_changed.emit()

    def set_available_ancestor_keys(self, available_keys: set[str]) -> None:
        for key, button in self._ancestor_buttons.items():
            button.setEnabled(key in available_keys)

class _ArchiveOpenSignals(QObject):
    completed = Signal(str, object, str)


class _EntryPreviewSignals(QObject):
    completed = Signal(int, object, str)
    palette_completed = Signal(int, object, str)


class _DirectorySignals(QObject):
    completed = Signal(str, object, object, str)


class _SearchSignals(QObject):
    completed = Signal(object, object, object, str)


class _SearchDragSignals(QObject):
    completed = Signal(object, object, object, str)


class _PaletteCatalogSignals(QObject):
    scan_started = Signal(object)
    snapshot_completed = Signal(object, object, str)
    completed = Signal(object, object, object, object, str)


class _CommunityNameDatabaseSignals(QObject):
    progress = Signal(object, int, int)
    completed = Signal(object, object, object, str)
    download_confirmation_size_completed = Signal(object, object, str)


class _ExternalOpenSignals(QObject):
    progress = Signal(int, int, int)
    completed = Signal(int, object, str)
    file_hash_completed = Signal(str, object, str)


class _TemporaryFilesSignals(QObject):
    count_completed = Signal(object, object, str)
    cleanup_completed = Signal(object, object, str)


class _DragExportSignals(QObject):
    completed = Signal(str, object, object, str)


class _ClipboardExportSignals(QObject):
    completed = Signal(str, object, object, str)


@dataclass(frozen=True)
class _PendingDragExport:
    temporary_root: Path
    cancellation: Event


@dataclass
class _ExternalProgressTask:
    kind: str
    display_name: str
    dialog: TaskProgressDialog
    cancellation: TaskCancellationToken
    future: Future | None = None
    modified_path: str | None = None
    page_key: str | None = None
    archive: MixArchiveIndex | None = None
    entry: MixEntry | None = None
    cleanup_root: Path | None = None
    target_parent_entry_ids: tuple[int, ...] = ()
    affected_entry_ids: tuple[int, ...] = ()
    close_page_prefixes: tuple[str, ...] = ()
    directory_keys: tuple[str, ...] = ()
    directory_operation: str | None = None
    save_root_key: str | None = None
    save_source_path: Path | None = None
    save_destination_path: Path | None = None
    save_remove_source: bool = False


@dataclass(frozen=True)
class _MixClipboard:
    archive_path: Path
    parent_entry_ids: tuple[int, ...]
    entry_ids: tuple[int, ...]
    exported_paths: tuple[Path, ...]


@dataclass(frozen=True)
class _AddedFilesResult:
    destination: str
    added_names: tuple[str, ...]
    replaced_names: tuple[str, ...]
    archive_signature: tuple[int, int] | None = None
    refreshed_archives: dict[str, MixArchiveIndex] | None = None
    refresh_error: str | None = None


@dataclass(frozen=True)
class _EditedEntriesResult:
    destination: str
    archive_signature: tuple[int, int]
    removed_names: tuple[str, ...]
    renamed_names: tuple[str, ...]
    copied_names: tuple[str, ...]
    refreshed_archives: dict[str, MixArchiveIndex]
    refresh_error: str | None = None


@dataclass
class _TrackedExternalFile:
    archive: MixArchiveIndex
    entry: MixEntry
    page_key: str
    display_name: str
    path: Path
    original_hash: str
    current_hash: str
    archive_signature: tuple[int, int]
    file_signature: tuple[int, int]
    dismissed_hash: str | None = None


@dataclass(frozen=True)
class _WriteBackResult:
    archive_signature: tuple[int, int]
    refreshed_archives: dict[str, MixArchiveIndex]
    refresh_error: str | None = None


# @arch mix-browser.save-mix-archive-copy utility | en: Copies an open MIX archive to a selected path with cancellation and atomic replacement | zh: 支持取消并原子替换地将打开的 MIX 归档复制到用户选择的位置
def _save_mix_archive_copy(
    source_path: Path,
    destination_path: Path,
    expected_signature: tuple[int, int],
    overwrite: bool,
    progress: Callable[[int, int], None],
    cancellation_requested: Callable[[], bool],
) -> tuple[int, int]:
    source_path = source_path.resolve()
    destination_path = destination_path.expanduser().resolve()
    if source_path == destination_path:
        raise ValueError("The save destination must differ from the runtime archive path.")
    before = source_path.stat()
    before_signature = (before.st_size, before.st_mtime_ns)
    if before_signature != expected_signature:
        raise ExternalFileChangedError("The runtime MIX archive changed before it could be saved.")
    total = before.st_size
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".mix-browser-save-",
            suffix=".tmp",
            dir=destination_path.parent,
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            with source_path.open("rb") as source:
                completed = 0
                progress(completed, total)
                while chunk := source.read(1024 * 1024):
                    if cancellation_requested():
                        raise InterruptedError("MIX archive save cancelled.")
                    output.write(chunk)
                    completed += len(chunk)
                    progress(completed, total)
            output.flush()
            os.fsync(output.fileno())

        after = source_path.stat()
        if (after.st_size, after.st_mtime_ns) != expected_signature:
            raise ExternalFileChangedError("The runtime MIX archive changed while it was being saved.")
        if cancellation_requested():
            raise InterruptedError("MIX archive save cancelled.")
        assert temporary_path is not None
        replace_path_with_staged_sibling(
            temporary_path,
            destination_path,
            overwrite=overwrite,
        )
        temporary_path = None
        saved = destination_path.stat()
        return saved.st_size, saved.st_mtime_ns
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


# @arch mix-browser.add-files-refresh service | en: Adds files to a MIX and refreshes every open view of the root archive | zh: 向 MIX 添加文件并刷新根归档的所有打开视图
def _add_files_to_mix_and_refresh(
    application: MixArchiveApplication,
    loader: MixArchiveLoader,
    root_path: Path,
    archive_entry_ids: tuple[int, ...],
    source_paths: tuple[Path, ...],
    overwrite: bool,
    expected_archive_signature: tuple[int, int],
    reload_targets: tuple[tuple[str, tuple[int, ...]], ...],
    progress: Callable[[int, int], None],
    cancellation_requested: Callable[[], bool],
) -> _AddedFilesResult:
    result = application.add_files(
        root_path,
        source_paths,
        parent_entry_ids=archive_entry_ids,
        overwrite=overwrite,
        expected_archive_signature=expected_archive_signature,
        progress=progress,
        cancellation_requested=cancellation_requested,
    )
    metadata = root_path.stat()
    signature = (metadata.st_size, metadata.st_mtime_ns)
    try:
        refreshed = reload_archive_indexes(loader, root_path, reload_targets)
    except Exception as exc:
        refreshed = {}
        refresh_error = str(exc)
    else:
        refresh_error = None
    return _AddedFilesResult(
        str(result["archive_path"]),
        tuple(str(name) for name in result["added_names"]),
        tuple(str(name) for name in result["replaced_names"]),
        signature,
        refreshed,
        refresh_error,
    )


# @arch mix-browser.edit-entries-refresh service | en: Edits MIX entries and reloads all open views of the root archive | zh: 编辑 MIX 条目并刷新根归档的所有打开视图
def _edit_mix_entries_and_refresh(
    application: MixArchiveApplication,
    loader: MixArchiveLoader,
    root_path: Path,
    target_parent_entry_ids: tuple[int, ...],
    remove_entry_ids: tuple[int, ...],
    rename_entries: dict[int, str] | None,
    source_archive_path: Path | None,
    source_parent_entry_ids: tuple[int, ...],
    copy_entry_ids: tuple[int, ...],
    expected_archive_signature: tuple[int, int] | None,
    reload_targets: tuple[tuple[str, tuple[int, ...]], ...],
    progress: Callable[[int, int], None],
    cancellation_requested: Callable[[], bool],
) -> _EditedEntriesResult:
    result = application.edit_entries(
        root_path,
        parent_entry_ids=target_parent_entry_ids,
        remove_entry_ids=remove_entry_ids,
        rename_entries=rename_entries,
        source_archive_path=source_archive_path,
        source_parent_entry_ids=source_parent_entry_ids,
        copy_entry_ids=copy_entry_ids,
        expected_archive_signature=expected_archive_signature,
        progress=progress,
        cancellation_requested=cancellation_requested,
    )
    metadata = root_path.stat()
    signature = (metadata.st_size, metadata.st_mtime_ns)
    try:
        refreshed = reload_archive_indexes(loader, root_path, reload_targets)
    except Exception as exc:
        refreshed = {}
        refresh_error = str(exc)
    else:
        refresh_error = None
    return _EditedEntriesResult(
        str(result["archive_path"]),
        signature,
        tuple(str(name) for name in result["removed_names"]),
        tuple(str(name) for name in result["renamed_names"]),
        tuple(str(name) for name in result["copied_names"]),
        refreshed,
        refresh_error,
    )


# @arch mix-browser.add-directory-files service | en: Adds local files to a directory through the browser application API | zh: 通过浏览器应用 API 将本地文件加入目录
def _add_files_to_directory(
    application: MixBrowserFeatureApplication,
    directory: Path,
    source_paths: tuple[Path, ...],
    overwrite: bool,
    approved_overwrites: frozenset[str],
    progress: Callable[[int, int], None],
    cancellation_requested: Callable[[], bool],
) -> _AddedFilesResult:
    result = application.add_files_to_directory(
        directory,
        source_paths,
        overwrite=overwrite,
        approved_overwrites=approved_overwrites,
        progress=progress,
        cancellation_requested=cancellation_requested,
    )
    return _AddedFilesResult(
        str(result["directory"]),
        tuple(str(name) for name in result["added_names"]),
        tuple(str(name) for name in result["overwritten_names"]),
    )


# @arch mix-browser.drop-action-dialog component | en: Presents open and add actions for dropped files with destination and overwrite details | zh: 显示拖入文件的打开与添加操作、目标位置和覆盖信息
class DropActionDialog(QDialog):
    def __init__(
        self,
        paths: tuple[Path, ...],
        *,
        destination: str,
        overwrite_names: tuple[str, ...],
        open_enabled: bool,
        add_enabled: bool,
        add_label: str,
        add_disabled_reason: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Dropped Items"))
        self.setMinimumWidth(520)
        self.action: str | None = None

        shown_paths = [str(path) for path in paths[:8]]
        if len(paths) > len(shown_paths):
            shown_paths.append(self.tr("and {0} more").format(len(paths) - len(shown_paths)))
        details = QLabel(
            self.tr("Dropped items:\n{0}").format("\n".join(shown_paths)),
            self,
        )
        details.setWordWrap(True)
        destination_label = QLabel(
            self.tr('Add destination:\n{0}').format(
                destination or self.tr("No active destination")
            ),
            self,
        )
        destination_label.setWordWrap(True)
        if overwrite_names:
            overwrite_text = self.tr("Existing items to replace:\n{0}").format(
                "\n".join(overwrite_names)
            )
        else:
            overwrite_text = self.tr(
                "No existing items with matching names or MIX IDs were found."
            )
        overwrite_label = QLabel(overwrite_text, self)
        overwrite_label.setWordWrap(True)
        open_help = QLabel(
            self.tr("Open folders and MIX archives in tabs; open other files with their default application."),
            self,
        )
        open_help.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(details)
        layout.addWidget(destination_label)
        layout.addWidget(overwrite_label)
        layout.addWidget(open_help)
        if not add_enabled and add_disabled_reason:
            reason = QLabel(self.tr(add_disabled_reason), self)
            reason.setWordWrap(True)
            layout.addWidget(reason)

        buttons = QDialogButtonBox(self)
        self.open_button = buttons.addButton(
            self.tr("Open"),
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.add_button = buttons.addButton(
            self.tr(add_label),
            QDialogButtonBox.ButtonRole.ActionRole,
        )
        self.cancel_button = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.open_button.setEnabled(open_enabled)
        self.add_button.setEnabled(add_enabled)
        self.open_button.clicked.connect(self._choose_open)
        self.add_button.clicked.connect(self._choose_add)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_open(self) -> None:
        self.action = "open"
        self.accept()

    def _choose_add(self) -> None:
        self.action = "add"
        self.accept()


# @arch mix-browser.name-validation-indicator component | en: Shows whether a proposed name is valid, available, or conflicting | zh: 显示名称有效性、可用性或冲突状态
class NameValidationIndicator(QLabel):
    _STATE_PRESENTATION = {
        "empty": ("Enter a name", "#8c959f"),
        "invalid": ("Invalid name", "#cf222e"),
        "invalid_path": ("Invalid save path", "#cf222e"),
        "same": ("Choose a different save path", "#cf222e"),
        "conflict": ("Name conflicts with an existing item", "#b45309"),
        "valid": ("Valid name", "#1a7f37"),
        "available": ("Name available", "#1a7f37"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_state("empty")

    def set_state(self, state: str) -> None:
        source, color = self._STATE_PRESENTATION.get(
            state,
            self._STATE_PRESENTATION["invalid"],
        )
        self.setText(self.tr(source))
        self.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.setProperty("validationState", state)

    @classmethod
    def color_for_state(cls, state: str) -> str:
        return cls._STATE_PRESENTATION.get(
            state,
            cls._STATE_PRESENTATION["invalid"],
        )[1]


def _set_name_conflict_button_style(button: QPushButton, emphasized: bool) -> None:
    if not emphasized:
        button.setStyleSheet("")
        return
    conflict_color = QColor(NameValidationIndicator.color_for_state("conflict"))
    hover_color = conflict_color.lighter(118).name()
    pressed_color = conflict_color.darker(118).name()
    button.setStyleSheet(
        "QPushButton {"
        f"background-color: {conflict_color.name()}; color: #ffffff; "
        f"border: 1px solid {conflict_color.name()}; font-weight: 600;"
        "}"
        "QPushButton:hover, QPushButton:focus {"
        f"background-color: {hover_color}; border-color: {hover_color};"
        "}"
        "QPushButton:pressed {"
        f"background-color: {pressed_color}; border-color: {pressed_color};"
        "}"
    )


def _add_mix_name_template_controls(
    layout: QVBoxLayout,
    name_edit: QLineEdit,
    *,
    include_mix_suffix: bool,
    quick_fill_label: str,
    ra2_button_label: str,
    yr_button_label: str,
    priority_hint: str,
) -> QLabel:
    template_row = QHBoxLayout()
    template_row.addWidget(QLabel(quick_fill_label))
    for label, prefix in (
        (ra2_button_label, "expand"),
        (yr_button_label, "expandmd"),
    ):
        button = QPushButton(label)
        button.setAutoDefault(False)

        def apply_template(_checked: bool = False, *, value: str = prefix) -> None:
            suffix = ".mix" if include_mix_suffix else ""
            name_edit.setText(f"{value}30{suffix}")
            name_edit.setCursorPosition(len(value) + 2)
            name_edit.setFocus()

        button.clicked.connect(apply_template)
        template_row.addWidget(button)
    template_row.addStretch(1)
    layout.addLayout(template_row)

    hint_label = QLabel(priority_hint)
    hint_label.setWordWrap(True)
    return hint_label


# @arch mix-browser.name-entry-dialog component | en: Collects a name and confirms replacement when it conflicts | zh: 收集名称并在冲突时确认是否替换
class NameEntryDialog(QDialog):
    def __init__(
        self,
        title: str,
        prompt: str,
        initial_name: str,
        name_state: Callable[..., str],
        parent: QWidget | None = None,
        *,
        save_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(680 if save_path is not None else 520)
        self._name_state = name_state
        self._save_directory = save_path.parent if save_path is not None else None
        self._save_path_edit: QLineEdit | None = None
        self._save_path_valid = True
        self._updating_name_from_save_path = False
        self.overwrite_confirmed = False
        self._current_name_state = "empty"

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(prompt, self))
        self.name_edit = QLineEdit(initial_name, self)
        self.name_edit.selectAll()
        priority_hint = _add_mix_name_template_controls(
            layout,
            self.name_edit,
            include_mix_suffix=Path(initial_name).suffix.casefold() in {".mix", ".mmx", ".yro"},
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
        layout.addWidget(self.name_edit)
        layout.addWidget(priority_hint)
        if self._save_directory is not None:
            save_path_row = QHBoxLayout()
            save_path_row.addWidget(QLabel(self.tr("Save location:"), self))
            self._save_path_edit = QLineEdit(self)
            self._save_path_edit.textEdited.connect(self._on_save_path_edited)
            self._save_path_edit.editingFinished.connect(self._normalize_save_path_edit)
            save_path_row.addWidget(self._save_path_edit, 1)
            choose_path_button = QPushButton(self.tr("Choose path..."), self)
            choose_path_button.setAutoDefault(False)
            choose_path_button.clicked.connect(self._choose_save_path)
            save_path_row.addWidget(choose_path_button)
            layout.addLayout(save_path_row)
        self.validation_indicator = NameValidationIndicator(self)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.accept_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addWidget(self.validation_indicator, 1)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)
        self.name_edit.textChanged.connect(self._refresh_name_state)
        self._refresh_name_state(self.name_edit.text())

    @property
    def destination_path(self) -> Path:
        if self._save_directory is None:
            raise RuntimeError("This name dialog has no save destination.")
        name = self.name_edit.text()
        if name and not Path(name).suffix:
            name += ".mix"
        return self._save_directory / name

    def _choose_save_path(self) -> None:
        if self._save_directory is None:
            return
        selected_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            self.tr("Choose MIX save path"),
            str(self.destination_path),
            self.tr("MIX archives (*.mix *.mmx *.yro);;All files (*)"),
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not selected_path:
            return
        chosen = Path(selected_path).expanduser()
        if not chosen.suffix:
            chosen = chosen.with_suffix(".mix")
        self._save_directory = chosen.parent
        self._save_path_valid = True
        self.name_edit.setText(chosen.name)
        self._refresh_name_state(self.name_edit.text())
        self.name_edit.setCursorPosition(len(self.name_edit.text()))
        self.name_edit.setFocus()

    def _on_save_path_edited(self, text: str) -> None:
        if self._save_path_edit is not None:
            self._save_path_edit.setToolTip(text)
        raw_path = text.strip()
        if len(raw_path) >= 2 and raw_path[0] == raw_path[-1] == '"':
            raw_path = raw_path[1:-1].strip()
        if not raw_path or raw_path.endswith(("/", "\\")):
            self._set_invalid_save_path()
            return

        candidate = Path(raw_path).expanduser()
        name = candidate.name
        if not is_valid_leaf_name(name):
            self._set_invalid_save_path()
            return
        if candidate.parent != Path("."):
            self._save_directory = candidate.parent
        self._save_path_valid = True
        self._updating_name_from_save_path = True
        try:
            self.name_edit.setText(name)
            self._refresh_name_state(self.name_edit.text())
        finally:
            self._updating_name_from_save_path = False

    def _normalize_save_path_edit(self) -> None:
        if (
            self._save_path_edit is None
            or self._current_name_state not in {"available", "valid", "conflict"}
        ):
            return
        destination = self.destination_path
        self._save_path_edit.setText(str(destination))
        self._save_path_edit.setToolTip(str(destination))

    def _set_invalid_save_path(self) -> None:
        self._save_path_valid = False
        self._current_name_state = "invalid_path"
        self.validation_indicator.set_state("invalid_path")
        self.accept_button.setEnabled(False)
        self._set_conflict_emphasis(False)

    def _refresh_name_state(self, name: str) -> None:
        self._save_path_valid = True
        if self._save_directory is None:
            state = self._name_state(name)
        elif not self._save_directory.is_dir():
            state = "invalid_path"
        else:
            state = self._name_state(name, self._save_directory)
        self._current_name_state = state
        self.validation_indicator.set_state(state)
        self.accept_button.setEnabled(state in {"available", "valid", "conflict"})
        self._set_conflict_emphasis(state == "conflict")
        if (
            self._save_path_edit is not None
            and self._save_path_valid
            and not self._updating_name_from_save_path
        ):
            destination = self.destination_path
            self._save_path_edit.setText(str(destination))
            self._save_path_edit.setToolTip(str(destination))

    def _set_conflict_emphasis(self, emphasized: bool) -> None:
        _set_name_conflict_button_style(self.accept_button, emphasized)

    def accept(self) -> None:
        if self._current_name_state not in {"available", "valid", "conflict"}:
            return
        if self._current_name_state == "conflict":
            item = str(self.destination_path) if self._save_directory is not None else self.name_edit.text()
            choice = QMessageBox.question(
                self,
                self.tr("Replace Existing Item?"),
                self.tr('An item named "{0}" already exists. Replace it? Existing contents may be lost.').format(item),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
            self.overwrite_confirmed = True
        super().accept()


# @arch mix-browser.new-file-dialog component | en: Collects a new name, MIX choice, and overwrite confirmation | zh: 收集新名称、MIX 选项及覆盖确认
class NewFileDialog(QDialog):
    def __init__(
        self,
        name_state: Callable[[str, bool], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("New File Here"))
        self.setMinimumWidth(520)
        self._name_state = name_state
        self.overwrite_confirmed = False
        self._current_name_state = "empty"

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("File name:"), self))
        self.name_edit = QLineEdit(self)
        self.name_edit.textChanged.connect(self._on_name_changed)
        priority_hint = _add_mix_name_template_controls(
            layout,
            self.name_edit,
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
        layout.addWidget(self.name_edit)
        layout.addWidget(priority_hint)
        self.create_mix_checkbox = QCheckBox(self.tr("Create as a MIX archive (.mix)"), self)
        self.create_mix_checkbox.toggled.connect(self._refresh_name_state)
        layout.addWidget(self.create_mix_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.accept_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.validation_indicator = NameValidationIndicator(self)
        button_row = QHBoxLayout()
        button_row.addWidget(self.validation_indicator, 1)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)
        self._refresh_name_state()

    def _on_name_changed(self, name: str) -> None:
        self._infer_mix_archive_type(name)
        self._refresh_name_state()

    def _refresh_name_state(self, *_args) -> None:
        state = self._name_state(
            self.name_edit.text(),
            self.create_mix_checkbox.isChecked(),
        )
        self._current_name_state = state
        self.validation_indicator.set_state(state)
        self.accept_button.setEnabled(state in {"available", "conflict"})
        _set_name_conflict_button_style(
            self.accept_button,
            state == "conflict",
        )

    def accept(self) -> None:
        if self._current_name_state not in {"available", "conflict"}:
            return
        if self._current_name_state == "conflict":
            name = self.name_edit.text().strip()
            if self.create_mix_checkbox.isChecked() and Path(name).suffix.casefold() != ".mix":
                name += ".mix"
            choice = QMessageBox.question(
                self,
                self.tr("Replace Existing Item?"),
                self.tr('An item named "{0}" already exists. Replace it? Existing contents may be lost.').format(name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
            self.overwrite_confirmed = True
        super().accept()

    def _infer_mix_archive_type(self, name: str) -> None:
        self.create_mix_checkbox.setChecked(
            Path(name.strip()).suffix.casefold() == ".mix"
        )


def _write_back_and_refresh_archives(
    loader: MixArchiveLoader,
    root_path: Path,
    archive_entry_ids: tuple[int, ...],
    entry_id: int,
    modified_path: Path,
    temporary_root: Path,
    original_content_hash: str,
    expected_content_hash: str,
    expected_archive_signature: tuple[int, int],
    reload_targets: tuple[tuple[str, tuple[int, ...]], ...],
    progress: Callable[[int, int], None],
    cancellation_requested: Callable[[], bool],
) -> _WriteBackResult:
    archive = load_archive_chain(loader, root_path, archive_entry_ids)
    entry = next((item for item in archive.entries if item.file_id == entry_id), None)
    if entry is None:
        raise OSError(f"MIX entry 0x{entry_id:08X} is no longer present.")
    signature = write_back_mix_entry(
        archive,
        entry_id,
        modified_path,
        temporary_root,
        original_content_hash=original_content_hash,
        expected_content_hash=expected_content_hash,
        expected_archive_signature=expected_archive_signature,
        progress=progress,
        cancellation_requested=cancellation_requested,
    )
    try:
        refreshed = reload_archive_indexes(loader, root_path, reload_targets)
    except Exception as exc:
        return _WriteBackResult(signature, {}, str(exc))
    return _WriteBackResult(signature, refreshed)


# @arch mix-browser.game-selection-dialog component | en: Selects the MIX name database game and shows name and palette support | zh: 选择 MIX 名称数据库所属游戏并展示名称与色盘支持情况
class GameSelectionDialog(QDialog):
    def __init__(
        self,
        selected_game: str,
        *,
        xcc_names_enabled: bool,
        community_names_enabled: bool,
        community_database_downloaded: bool,
        palette_directory_configured: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Select Game"))
        self.setMinimumWidth(780)
        self.resize(920, 440)

        layout = QVBoxLayout(self)
        reason = QLabel(
            self.tr(
                "Choose the game's MIX name list to resolve hashed entry IDs. A list for another game may leave IDs unresolved or suggest incorrect names. This affects name lookup only; nearby filenames and embedded local name databases remain available for every game."
            ),
            self,
        )
        reason.setWordWrap(True)
        reason.setProperty("visualRole", "description")
        layout.addWidget(reason)

        palette_note = QLabel(
            self.tr(
                "Palette automation uses separate rules. General local and user-defined rules are available for every game; game-directory Art and theater rules currently support RA2/YR. Choosing a game here does not change the configured directory or palette rules."
            ),
            self,
        )
        palette_note.setWordWrap(True)
        palette_note.setProperty("visualRole", "description")
        layout.addWidget(palette_note)

        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 3)
        for column, heading in enumerate(
            (
                self.tr("Game"),
                self.tr("MIX name availability"),
                self.tr("Palette automation availability"),
            )
        ):
            label = QLabel(heading, self)
            label.setProperty("visualRole", "heading")
            grid.addWidget(label, 0, column)

        self._game_group = QButtonGroup(self)
        self._game_buttons: dict[str, QRadioButton] = {}
        for row, (game_key, game_label, _database_group) in enumerate(
            MIX_NAME_GAME_GROUPS,
            start=1,
        ):
            radio = QRadioButton(self.tr(game_label), self)
            self._game_group.addButton(radio, row)
            radio.setChecked(game_key == selected_game)
            grid.addWidget(radio, row, 0)
            grid.addWidget(
                self._status_label(
                    self._name_availability(
                        game_key,
                        xcc_names_enabled=xcc_names_enabled,
                        community_names_enabled=community_names_enabled,
                        community_database_downloaded=community_database_downloaded,
                    )
                ),
                row,
                1,
            )
            grid.addWidget(
                self._status_label(
                    self._palette_availability(
                        game_key,
                        palette_directory_configured=palette_directory_configured,
                    )
                ),
                row,
                2,
            )
            self._game_buttons[game_key] = radio
        layout.addLayout(grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            self.tr("OK / 确定")
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            self.tr("Cancel / 取消")
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_game(self) -> str:
        return next(
            game_key
            for game_key, radio in self._game_buttons.items()
            if radio.isChecked()
        )

    def _status_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setWordWrap(True)
        label.setProperty("visualRole", "description")
        return label

    def _name_availability(
        self,
        game: str,
        *,
        xcc_names_enabled: bool,
        community_names_enabled: bool,
        community_database_downloaded: bool,
    ) -> str:
        if game in XCC_NAME_GAME_KEYS:
            xcc_status = self.tr(
                "XCC list: enabled" if xcc_names_enabled else "XCC list: disabled"
            )
        else:
            xcc_status = self.tr("XCC list: unavailable")
        if community_database_downloaded:
            community_status = self.tr(
                "CnCNet database: enabled"
                if community_names_enabled
                else "CnCNet database: downloaded, disabled"
            )
        else:
            community_status = self.tr("CnCNet database: not downloaded")
        return self.tr("{0} | {1}").format(xcc_status, community_status)

    def _palette_availability(
        self,
        game: str,
        *,
        palette_directory_configured: bool,
    ) -> str:
        if game != DEFAULT_MIX_NAME_GAME:
            return self.tr(
                "General and user rules available; no dedicated game rules"
            )
        if palette_directory_configured:
            return self.tr(
                "General and user rules available; RA2/YR game-directory path is set"
            )
        return self.tr(
            "General and user rules available; no RA2/YR game-directory path is set"
        )


# @arch mix-browser.mix-name-source-page component | en: Configures the XCC and optional downloaded MIX filename sources | zh: 配置 XCC 与可选下载的 MIX 文件名来源
class MixNameSourcesPage(QWidget):
    download_community_requested = Signal()

    def __init__(
        self,
        xcc_enabled: bool,
        community_enabled: bool,
        community_downloaded: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.xcc_checkbox = QCheckBox(
            self.tr("Use bundled XCC name list for selected game (GPL-3.0)"),
            self,
        )
        self.xcc_checkbox.setChecked(xcc_enabled)
        self.community_checkbox = QCheckBox(
            self.tr("Use CnCNet community database (optional)"), self
        )
        self.community_checkbox.setChecked(community_enabled and community_downloaded)
        self.community_checkbox.setEnabled(community_downloaded)
        self.community_status_label = QLabel(self)
        self.community_status_label.setProperty("visualRole", "description")
        self.community_download_button = QPushButton(self)
        self.community_download_button.clicked.connect(
            self.download_community_requested
        )
        self.set_community_database_downloaded(community_downloaded)

        source_group = QGroupBox(self.tr("Name database sources"), self)
        source_layout = QVBoxLayout(source_group)
        xcc_row = QHBoxLayout()
        xcc_row.addWidget(self.xcc_checkbox)
        xcc_row.addStretch(1)
        xcc_link = QLabel(
            self.tr('<a href="https://github.com/OlafvdSpek/xcc/tree/master/data">XCC Utilities MIX name lists</a>'),
            self,
        )
        xcc_link.setOpenExternalLinks(True)
        xcc_row.addWidget(xcc_link)
        source_layout.addLayout(xcc_row)

        xcc_note = QLabel(
            self.tr(
                "XCC includes name lists for TD, TS, and RA2/YR. The Red Alert list is available from the optional community database."
            ),
            self,
        )
        xcc_note.setWordWrap(True)
        xcc_note.setProperty("visualRole", "description")
        source_layout.addWidget(xcc_note)

        community_row = QHBoxLayout()
        community_row.addWidget(self.community_checkbox)
        community_row.addStretch(1)
        community_row.addWidget(self.community_status_label)
        community_row.addWidget(self.community_download_button)
        source_layout.addLayout(community_row)

        community_details_row = QHBoxLayout()
        community_details_row.addStretch(1)
        community_link = QLabel(
            self.tr('<a href="https://forums.cncnet.org/topic/2286-updated-global-mix-database/">CnCNet Forums · Blade · 2015-04-13</a>'),
            self,
        )
        community_link.setOpenExternalLinks(True)
        community_details_row.addWidget(community_link)
        source_layout.addLayout(community_details_row)

        local_group = QGroupBox(self.tr("Local sources"), self)
        local_layout = QVBoxLayout(local_group)
        local_sources = QLabel(
            self.tr("The opened MIX's embedded local database is always included."),
            self,
        )
        local_sources.setWordWrap(True)
        local_sources.setProperty("visualRole", "description")
        local_layout.addWidget(local_sources)

        community_note = QLabel(
            self.tr(
                "The community database is downloaded directly from CnCNet and is not included in releases."
            ),
            self,
        )
        community_note.setWordWrap(True)
        community_note.setProperty("visualRole", "description")
        source_layout.addWidget(community_note)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(source_group)
        layout.addWidget(local_group)
        layout.addStretch(1)

    def set_community_database_downloaded(
        self,
        downloaded: bool,
        *,
        enable_source: bool | None = None,
    ) -> None:
        self.community_database_downloaded = downloaded
        self.community_checkbox.setEnabled(downloaded)
        if not downloaded:
            self.community_checkbox.setChecked(False)
        elif enable_source is not None:
            self.community_checkbox.setChecked(enable_source)
        self.community_status_label.setText(
            self.tr("Downloaded") if downloaded else self.tr("Not downloaded")
        )
        self.community_download_button.setText(
            self.tr("Download again") if downloaded else self.tr("Download")
        )


# @arch mix-browser.palette-library-settings adapter | en: Reads legacy user palette paths and filename patterns from settings | zh: 从旧版设置中读取用户色盘路径和资源名正则
def _read_palette_library_setting(value: str) -> tuple[PaletteLibraryRule, ...]:
    try:
        records = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return ()
    if not isinstance(records, list):
        return ()
    rules = []
    for record in records:
        if not isinstance(record, dict):
            continue
        path = record.get("path")
        pattern = record.get("pattern", "")
        if isinstance(path, str) and path.strip() and isinstance(pattern, str):
            rules.append(PaletteLibraryRule(Path(path), pattern))
    return tuple(rules)


# @arch mix-browser.palette-library-manifest adapter | en: Reads and writes portable user palette rules beside their palette files | zh: 在用户色盘文件旁读写可迁移的色盘规则
def _palette_library_manifest_path() -> Path:
    return application_directory() / "user-palettes" / "palette-library.json"


def _read_palette_library_manifest() -> tuple[PaletteLibraryRule, ...] | None:
    manifest_path = _palette_library_manifest_path()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or not isinstance(payload.get("rules"), list)
    ):
        return None

    rules = []
    for record in payload["rules"]:
        if not isinstance(record, dict):
            continue
        raw_path = record.get("path")
        pattern = record.get("pattern", "")
        if (
            not isinstance(raw_path, str)
            or not raw_path.strip()
            or not isinstance(pattern, str)
        ):
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = manifest_path.parent / path
        rules.append(PaletteLibraryRule(path, pattern))
    return tuple(rules)


def _serialize_palette_library_manifest(
    rules: tuple[PaletteLibraryRule, ...],
) -> str:
    palette_directory = _user_palette_library_directory().resolve()
    records = []
    for rule in rules:
        path = _resolve_palette_library_path(rule.path)
        try:
            stored_path = path.resolve().relative_to(palette_directory).as_posix()
        except (OSError, RuntimeError, ValueError):
            stored_path = str(path)
        records.append({"path": stored_path, "pattern": rule.asset_pattern})
    return json.dumps(
        {"version": 1, "rules": records},
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def _write_palette_library_manifest(rules: tuple[PaletteLibraryRule, ...]) -> None:
    _user_palette_library_directory()
    manifest_path = _palette_library_manifest_path()
    temporary_path = manifest_path.with_name(f".{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            _serialize_palette_library_manifest(rules),
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary_path, manifest_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _resolve_palette_library_path(path: Path) -> Path:
    path = path.expanduser()
    if path.is_absolute():
        return path
    return (application_directory() / path).resolve()


def _stored_palette_library_path(path: Path) -> Path:
    resolved = _resolve_palette_library_path(path)
    try:
        return resolved.relative_to(application_directory())
    except ValueError:
        return path


def _user_palette_library_directory() -> Path:
    directory = application_directory() / "user-palettes"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _is_managed_user_palette_path(path: Path) -> bool:
    try:
        path = _resolve_palette_library_path(path).resolve()
        path.relative_to((application_directory() / "user-palettes").resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


# @arch mix-browser.import-user-palette service | en: Copies a selected PAL file into the program-relative palette library | zh: 将选中的 PAL 文件复制到程序相对目录下的色盘库
def _import_user_palette(
    source: Path,
    *,
    created_paths: set[Path] | None = None,
) -> Path:
    source = source.expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.casefold() != ".pal":
        raise OSError("The selected file is not an available PAL file.")

    library_directory = _user_palette_library_directory().resolve()
    if source.parent == library_directory:
        return source

    source_data = source.read_bytes()
    destination = library_directory / source.name
    if destination.exists():
        if destination.is_file() and destination.read_bytes() == source_data:
            return destination
        digest = hashlib.sha256(source_data).hexdigest()[:12]
        destination = library_directory / f"{source.stem}-{digest}{source.suffix}"
        suffix = 2
        while destination.exists():
            if destination.is_file() and destination.read_bytes() == source_data:
                return destination
            destination = library_directory / f"{source.stem}-{digest}-{suffix}{source.suffix}"
            suffix += 1

    temporary = library_directory / f".{uuid4().hex}.tmp"
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
        if created_paths is not None:
            created_paths.add(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _migrate_user_palette_rules(
    rules: tuple[PaletteLibraryRule, ...],
) -> tuple[PaletteLibraryRule, ...]:
    migrated = []
    for rule in rules:
        try:
            path = _import_user_palette(_resolve_palette_library_path(rule.path))
        except (OSError, RuntimeError):
            path = rule.path
        migrated.append(replace(rule, path=path))
    return tuple(migrated)


def _serialize_palette_library_setting(
    rules: tuple[PaletteLibraryRule, ...],
) -> str:
    return json.dumps(
        [
            {
                "path": _stored_palette_library_path(rule.path).as_posix(),
                "pattern": rule.asset_pattern,
            }
            for rule in rules
        ],
        ensure_ascii=False,
    )


# @arch mix-browser.palette-library-drop-table component | en: Accepts local PAL files dropped onto the user palette library | zh: 接收拖入用户色盘库的本地 PAL 文件
class _PaletteLibraryDropTable(QTableWidget):
    files_dropped = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 2, parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDropIndicatorShown(False)

    @staticmethod
    def _palette_paths(event) -> tuple[Path, ...]:
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return ()
        return tuple(
            path
            for url in mime_data.urls()
            if url.isLocalFile()
            and (path := Path(url.toLocalFile())).suffix.casefold() == ".pal"
        )

    def dragEnterEvent(self, event) -> None:
        if self._palette_paths(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._palette_paths(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        paths = self._palette_paths(event)
        if not paths:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        self.files_dropped.emit(paths)
        event.accept()


# @arch mix-browser.palette-source-page component | en: Configures palette sources, the user palette library, and preview theater | zh: 配置色盘来源、用户色盘库和预览战区
class PaletteSourcesPage(QWidget):
    refresh_palette_requested = Signal()

    def __init__(
        self,
        directory: str,
        theater: str = "auto",
        palette_library: tuple[PaletteLibraryRule, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.directory_edit = QLineEdit(directory, self)
        self.directory_edit.setClearButtonEnabled(True)
        self.directory_edit.setPlaceholderText(self.tr("Select an RA2/YR game directory"))
        browse_button = QPushButton(self.tr("Browse..."), self)
        browse_button.clicked.connect(self._browse)

        row = QHBoxLayout()
        row.addWidget(self.directory_edit, 1)
        row.addWidget(browse_button)

        self.refresh_palette_button = QPushButton(self.tr("Refresh Palette Search"), self)
        self.refresh_palette_button.setEnabled(bool(directory.strip()))
        self.refresh_palette_button.clicked.connect(
            self.refresh_palette_requested.emit
        )
        self.directory_edit.textChanged.connect(
            lambda value: self.refresh_palette_button.setEnabled(bool(value.strip()))
        )

        self.theater_combo = QComboBox(self)
        for label, value in (
            (self.tr("Automatic (Temperate when unknown)"), "auto"),
            (self.tr("Temperate"), "tem"),
            (self.tr("Snow"), "sno"),
            (self.tr("Urban"), "urb"),
            (self.tr("Desert"), "des"),
            (self.tr("Lunar"), "lun"),
            (self.tr("New Urban"), "ubn"),
        ):
            self.theater_combo.addItem(label, value)
        theater_index = self.theater_combo.findData(theater)
        self.theater_combo.setCurrentIndex(max(0, theater_index))

        self.palette_library_table = _PaletteLibraryDropTable(self)
        self.palette_library_table.files_dropped.connect(self._add_palette_paths)
        self.palette_library_table.setHorizontalHeaderLabels(
            (self.tr("Palette file"), self.tr("Asset filename regex"))
        )
        self.palette_library_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.palette_library_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.palette_library_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        self.palette_library_table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        self.palette_library_table.setMinimumHeight(120)
        self._pending_user_palette_deletions: set[Path] = set()
        self._newly_copied_palette_files: set[Path] = set()
        for rule in palette_library:
            self._append_palette_rule(rule.path, rule.asset_pattern)

        add_palette_button = QPushButton(self.tr("Add PAL..."), self)
        add_palette_button.clicked.connect(self._add_palette_files)
        remove_palette_button = QPushButton(self.tr("Remove"), self)
        remove_palette_button.clicked.connect(self._remove_palette_rules)
        move_up_button = QPushButton(self.tr("Move Up"), self)
        move_up_button.clicked.connect(lambda: self._move_palette_rule(-1))
        move_down_button = QPushButton(self.tr("Move Down"), self)
        move_down_button.clicked.connect(lambda: self._move_palette_rule(1))
        open_palette_folder_button = QPushButton(
            self.tr("Open Palette Storage Folder"),
            self,
        )
        open_palette_folder_button.clicked.connect(self._open_palette_storage_folder)
        palette_buttons = QHBoxLayout()
        palette_buttons.addWidget(add_palette_button)
        palette_buttons.addWidget(remove_palette_button)
        palette_buttons.addWidget(move_up_button)
        palette_buttons.addWidget(move_down_button)
        palette_buttons.addWidget(open_palette_folder_button)
        palette_buttons.addStretch(1)

        directory_group = QGroupBox(self.tr("RA2/YR game directory"), self)
        directory_layout = QVBoxLayout(directory_group)
        directory_layout.addLayout(row)
        refresh_row = QHBoxLayout()
        refresh_row.addStretch(1)
        refresh_row.addWidget(self.refresh_palette_button)
        directory_layout.addLayout(refresh_row)

        theater_group = QGroupBox(self.tr("Map theater for previews"), self)
        theater_layout = QVBoxLayout(theater_group)
        theater_layout.addWidget(self.theater_combo)
        theater_description = QLabel(
            self.tr("Palettes and art rules are read from this folder and its nested MIX archives. "
            "NewTheater A variants use the Snow palette; G variants use the selected theater."),
            theater_group,
        )
        theater_description.setWordWrap(True)
        theater_description.setProperty("visualRole", "description")
        theater_layout.addWidget(theater_description)

        library_group = QGroupBox(self.tr("User palette library"), self)
        library_layout = QVBoxLayout(library_group)
        library_description = QLabel(
            self.tr("Regex searches the asset filename including its extension, case-insensitively. "
            "For example: ^E1ICON\\.SHP$. Leave it blank for manual selection only. "
            "Matching rows run top to bottom. Added .pal files are copied into the program's user-palettes folder only when you confirm preferences. "
            "Same-name identical palettes reuse a copy; different contents get a hash suffix, and existing files are never overwritten. "
            "Remove can also delete imported copies after saving preferences if no rule still references them. "
            "The palette files and their filename rules are stored together in user-palettes. Back up and restore that folder to keep the library on another installation. "
            "Drop files into the table or use Add PAL to import them."),
            library_group,
        )
        library_description.setWordWrap(True)
        library_description.setProperty("visualRole", "description")
        library_layout.addWidget(library_description)
        library_layout.addWidget(self.palette_library_table, 1)
        library_layout.addLayout(palette_buttons)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(directory_group)
        layout.addWidget(theater_group)
        layout.addWidget(library_group, 1)

    def palette_library_rules(self) -> tuple[PaletteLibraryRule, ...]:
        rules = []
        for row in range(self.palette_library_table.rowCount()):
            path_item = self.palette_library_table.item(row, 0)
            pattern_item = self.palette_library_table.item(row, 1)
            if path_item is None:
                continue
            rules.append(
                PaletteLibraryRule(
                    _resolve_palette_library_path(Path(path_item.text())),
                    pattern_item.text().strip() if pattern_item is not None else "",
                )
            )
        return tuple(rules)

    def _append_palette_rule(
        self,
        path: Path,
        pattern: str = "",
        *,
        pending_import: bool = False,
    ) -> None:
        row = self.palette_library_table.rowCount()
        self.palette_library_table.insertRow(row)
        stored_path = path if pending_import else _stored_palette_library_path(path)
        path_item = QTableWidgetItem(stored_path.as_posix())
        path_item.setFlags(path_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        path_item.setToolTip(stored_path.as_posix())
        path_item.setData(Qt.ItemDataRole.UserRole, pending_import)
        path_item.setData(
            Qt.ItemDataRole.UserRole + 1,
            str(path.expanduser().resolve()) if pending_import else None,
        )
        pattern_item = QTableWidgetItem(pattern)
        pattern_item.setToolTip(
            self.tr("Case-insensitive regular expression tested against the asset filename.")
        )
        self.palette_library_table.setItem(row, 0, path_item)
        self.palette_library_table.setItem(row, 1, pattern_item)

    def _add_palette_files(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            self.tr("Add palette files"),
            "",
            self.tr("Palette files (*.pal);;All files (*)"),
        )
        self._add_palette_paths(tuple(Path(raw_path) for raw_path in paths))

    def _open_palette_storage_folder(self) -> None:
        directory = None
        try:
            directory = _user_palette_library_directory().resolve()
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
        except OSError as exc:
            opened = False
            error = str(exc)
        else:
            error = ""
        if not opened:
            QMessageBox.warning(
                self,
                self.tr("Could Not Open Palette Folder"),
                self.tr("The user palette storage folder could not be opened:\n{0}").format(
                    error or str(directory or application_directory() / "user-palettes")
                ),
            )

    def _add_palette_paths(self, paths: tuple[Path, ...]) -> None:
        existing = set()
        for row in range(self.palette_library_table.rowCount()):
            item = self.palette_library_table.item(row, 0)
            if item is not None:
                existing.add(self._palette_path_key(Path(item.text())))
        for source in paths:
            if source.suffix.casefold() != ".pal" or not source.is_file():
                continue
            try:
                path = source.expanduser().resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            key = self._palette_path_key(path)
            if key not in existing:
                self._append_palette_rule(
                    path,
                    pending_import=not _is_managed_user_palette_path(path),
                )
                existing.add(key)

    def commit_pending_palette_imports(self) -> tuple[str, ...]:
        imports: dict[int, tuple[Path, str]] = {}
        created_paths: set[Path] = set()
        failures = []
        for row in range(self.palette_library_table.rowCount()):
            path_item = self.palette_library_table.item(row, 0)
            if path_item is None or not path_item.data(Qt.ItemDataRole.UserRole):
                continue
            source = Path(path_item.text())
            try:
                destination = _import_user_palette(
                    source,
                    created_paths=created_paths,
                )
            except (OSError, RuntimeError) as exc:
                failures.append(f"{source}: {exc}")
                continue
            pattern_item = self.palette_library_table.item(row, 1)
            pattern = pattern_item.text().strip() if pattern_item is not None else ""
            imports[row] = (destination, pattern)

        if failures:
            for path in created_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            return tuple(failures)

        seen: dict[str, set[str]] = {}
        rows_to_remove = []
        for row in range(self.palette_library_table.rowCount()):
            path_item = self.palette_library_table.item(row, 0)
            pattern_item = self.palette_library_table.item(row, 1)
            if path_item is None:
                continue
            imported = imports.get(row)
            path = (
                imported[0]
                if imported is not None
                else _resolve_palette_library_path(Path(path_item.text()))
            )
            if imported is not None:
                pattern = imported[1]
            else:
                pattern = pattern_item.text().strip() if pattern_item is not None else ""
            key = self._palette_path_key(path)
            patterns = seen.setdefault(key, set())
            if imported is not None and pattern in patterns:
                rows_to_remove.append(row)
                continue
            patterns.add(pattern)
            if imported is not None:
                stored_path = _stored_palette_library_path(path).as_posix()
                path_item.setText(stored_path)
                path_item.setToolTip(stored_path)
                path_item.setData(Qt.ItemDataRole.UserRole, False)

        for row in reversed(rows_to_remove):
            self.palette_library_table.removeRow(row)
        self._newly_copied_palette_files.update(created_paths)
        return ()

    def rollback_pending_palette_imports(self) -> tuple[str, ...]:
        failures = []
        for row in range(self.palette_library_table.rowCount()):
            path_item = self.palette_library_table.item(row, 0)
            if path_item is None:
                continue
            original_path = path_item.data(Qt.ItemDataRole.UserRole + 1)
            if not original_path:
                continue
            path_item.setText(str(original_path))
            path_item.setToolTip(str(original_path))
            path_item.setData(Qt.ItemDataRole.UserRole, True)

        for path in self._newly_copied_palette_files:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                failures.append(f"{path}: {exc}")
        self._newly_copied_palette_files.clear()
        return tuple(failures)

    def finalize_pending_palette_imports(self) -> None:
        for row in range(self.palette_library_table.rowCount()):
            path_item = self.palette_library_table.item(row, 0)
            if path_item is not None:
                path_item.setData(Qt.ItemDataRole.UserRole + 1, None)
        self._newly_copied_palette_files.clear()

    @staticmethod
    def _palette_path_key(path: Path) -> str:
        try:
            return str(_resolve_palette_library_path(path).resolve()).casefold()
        except OSError:
            return str(_resolve_palette_library_path(path).absolute()).casefold()

    def _remove_palette_rules(self) -> None:
        rows = sorted(
            {index.row() for index in self.palette_library_table.selectionModel().selectedRows()},
            reverse=True,
        )
        if not rows:
            return
        managed_paths = {
            _resolve_palette_library_path(Path(item.text())).resolve()
            for row in rows
            if (item := self.palette_library_table.item(row, 0)) is not None
            and _is_managed_user_palette_path(Path(item.text()))
        }
        if managed_paths:
            prompt = QMessageBox(self)
            prompt.setIcon(QMessageBox.Icon.Warning)
            prompt.setWindowTitle(self.tr("Remove Palette Rules"))
            prompt.setText(
                self.tr(
                    "Choose whether to delete imported copies with these rules. Deletion happens only after you save preferences, and files still used by another rule are kept. Original files outside the program folder are never deleted."
                )
            )
            delete_button = prompt.addButton(
                self.tr("Remove Rules and Stored Files"),
                QMessageBox.ButtonRole.DestructiveRole,
            )
            remove_only_button = prompt.addButton(
                self.tr("Remove Rules Only"),
                QMessageBox.ButtonRole.AcceptRole,
            )
            prompt.addButton(
                self.tr("Cancel"),
                QMessageBox.ButtonRole.RejectRole,
            )
            prompt.setDefaultButton(remove_only_button)
            prompt.exec()
            if prompt.clickedButton() is delete_button:
                self._pending_user_palette_deletions.update(managed_paths)
            elif prompt.clickedButton() is not remove_only_button:
                return
        for row in rows:
            self.palette_library_table.removeRow(row)

    def delete_unreferenced_palette_copies(
        self,
        rules: tuple[PaletteLibraryRule, ...],
    ) -> tuple[str, ...]:
        referenced = {self._palette_path_key(rule.path) for rule in rules}
        failures = []
        for path in self._pending_user_palette_deletions:
            if self._palette_path_key(path) in referenced:
                continue
            try:
                if _is_managed_user_palette_path(path):
                    path.unlink(missing_ok=True)
            except OSError as exc:
                failures.append(f"{path}: {exc}")
        self._pending_user_palette_deletions.clear()
        return tuple(failures)

    @property
    def has_pending_user_palette_deletions(self) -> bool:
        return bool(self._pending_user_palette_deletions)

    def _move_palette_rule(self, offset: int) -> None:
        selected_rows = self.palette_library_table.selectionModel().selectedRows()
        if len(selected_rows) != 1:
            return
        row = selected_rows[0].row()
        target = row + offset
        if not 0 <= target < self.palette_library_table.rowCount():
            return
        items = [
            self.palette_library_table.takeItem(row, column)
            for column in range(self.palette_library_table.columnCount())
        ]
        self.palette_library_table.removeRow(row)
        self.palette_library_table.insertRow(target)
        for column, item in enumerate(items):
            if item is not None:
                self.palette_library_table.setItem(target, column, item)
        self.palette_library_table.selectRow(target)

    def validate(self) -> bool:
        for row in range(self.palette_library_table.rowCount()):
            item = self.palette_library_table.item(row, 1)
            pattern = item.text().strip() if item is not None else ""
            if not pattern:
                continue
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                QMessageBox.warning(
                    self,
                    self.tr("Invalid Palette Regex"),
                    self.tr('The regular expression in row {0} is invalid: {1}').format(row + 1, exc),
                )
                self.palette_library_table.setCurrentCell(row, 1)
                return False
        return True

    def _browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select RA2/YR game directory"),
            self.directory_edit.text(),
        )
        if directory:
            self.directory_edit.setText(directory)


# @arch mix-browser.preferences-dialog component | en: Groups playback, source, integration, and temporary-file preferences in one dialog | zh: 在同一弹窗中集中管理播放、来源、系统集成和临时文件首选项
class PreferencesDialog(QDialog):
    def __init__(
        self,
        auto_play_preferences: dict[str, bool],
        xcc_names_enabled: bool,
        community_names_enabled: bool,
        community_database_downloaded: bool,
        palette_directory: str,
        palette_theater: str,
        palette_library_rules: tuple[PaletteLibraryRule, ...],
        system_integration_state: dict[str, object],
        ui_language: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Preferences / 首选项"))
        self.setMinimumSize(760, 520)
        self.resize(900, 640)

        self.tabs = QTabWidget(self)
        general_page = QWidget(self.tabs)
        general_layout = QVBoxLayout(general_page)
        language_group = QGroupBox(
            self.tr("Interface language / 界面语言"), general_page
        )
        language_layout = QVBoxLayout(language_group)
        language_row = QHBoxLayout()
        language_row.addWidget(
            QLabel(self.tr("Language / 语言"), language_group)
        )
        self.language_combo = QComboBox(language_group)
        for label, value in (
            (self.tr("System default / 系统默认"), "system"),
            (self.tr("English / 英语"), "en"),
            (self.tr("Chinese (Simplified) / 简体中文"), "zh_CN"),
        ):
            self.language_combo.addItem(label, value)
        language_index = self.language_combo.findData(ui_language)
        self.language_combo.setCurrentIndex(max(0, language_index))
        language_row.addWidget(self.language_combo, 1)
        language_layout.addLayout(language_row)
        language_note = QLabel(
            self.tr(
                "Restart the application to apply the selected language. / "
                "重启应用后，所选语言才会生效。"
            ),
            language_group,
        )
        language_note.setWordWrap(True)
        language_note.setProperty("visualRole", "description")
        language_layout.addWidget(language_note)
        general_layout.addWidget(language_group)
        general_layout.addStretch(1)
        self.tabs.addTab(general_page, self.tr("General / 常规"))

        playback_page = QWidget(self.tabs)
        playback_layout = QVBoxLayout(playback_page)
        playback_group = QGroupBox(self.tr("Automatic playback"), playback_page)
        playback_group_layout = QVBoxLayout(playback_group)
        self.auto_play_checkboxes: dict[str, QCheckBox] = {}
        for key, label in (
            ("animations", self.tr("Auto-play SHP animations")),
            ("audio", self.tr("Auto-play audio")),
            ("video", self.tr("Auto-play video")),
        ):
            checkbox = QCheckBox(label, playback_page)
            checkbox.setChecked(auto_play_preferences[key])
            self.auto_play_checkboxes[key] = checkbox
            playback_group_layout.addWidget(checkbox)
        playback_layout.addWidget(playback_group)
        playback_layout.addStretch(1)
        self.tabs.addTab(playback_page, self.tr("Playback"))

        self.mix_name_sources = MixNameSourcesPage(
            xcc_names_enabled,
            community_names_enabled,
            community_database_downloaded,
            self,
        )
        self.tabs.addTab(self.mix_name_sources, self.tr("MIX Name Sources"))

        self.palette_sources = PaletteSourcesPage(
            palette_directory,
            palette_theater,
            palette_library_rules,
            self,
        )
        self.tabs.addTab(self.palette_sources, self.tr("Palette Sources"))

        self.system_integration = SystemIntegrationSettingsPage(
            system_integration_state,
            self,
        )
        self.tabs.addTab(self.system_integration, self.tr("System Integration"))

        self.temporary_files = TemporaryFilesSettingsPage(self)
        self.tabs.addTab(self.temporary_files, self.tr("Temporary Files"))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            self.tr("OK / 确定")
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            self.tr("Cancel / 取消")
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)
        self._position_on_available_screen()

    def _position_on_available_screen(self) -> None:
        self.ensurePolished()
        self.winId()

        parent = self.parentWidget()
        parent_center = parent.frameGeometry().center() if parent is not None else None
        screen = (
            QGuiApplication.screenAt(parent_center)
            if parent_center is not None
            else None
        )
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry().adjusted(8, 8, -8, -8)
        window_handle = self.windowHandle()
        margins = window_handle.frameMargins() if window_handle is not None else None
        frame_width = margins.left() + margins.right() if margins is not None else 0
        frame_height = margins.top() + margins.bottom() if margins is not None else 0
        max_width = max(1, available.width() - frame_width)
        max_height = max(1, available.height() - frame_height)
        self.setMinimumSize(min(760, max_width), min(520, max_height))
        self.setMaximumSize(max_width, max_height)
        self.resize(min(self.width(), max_width), min(self.height(), max_height))

        target = (
            parent_center
            if parent_center is not None and available.contains(parent_center)
            else available.center()
        )
        frame = self.frameGeometry()
        x = min(
            max(target.x() - frame.width() // 2, available.left()),
            available.right() - frame.width() + 1,
        )
        y = min(
            max(target.y() - frame.height() // 2, available.top()),
            available.bottom() - frame.height() + 1,
        )
        self.move(x, y)

    def accept(self) -> None:
        raw_directory = self.palette_sources.directory_edit.text().strip()
        if raw_directory and not Path(raw_directory).expanduser().is_dir():
            self.tabs.setCurrentWidget(self.palette_sources)
            QMessageBox.warning(
                self,
                self.tr("Invalid Game Directory"),
                self.tr("The selected folder does not exist."),
            )
            return
        if not self.palette_sources.validate():
            self.tabs.setCurrentWidget(self.palette_sources)
            return
        super().accept()

# @arch mix-browser.fixed-width-tab-bar component | en: Gives browser tabs one fixed width | zh: 为浏览器标签设置固定宽度
class _FixedWidthTabBar(QTabBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fixed_tab_width = 180

    def set_fixed_tab_width(self, width: int) -> None:
        width = max(120, width)
        if width == self._fixed_tab_width:
            return
        self._fixed_tab_width = width
        self.tabLayoutChange()
        self.updateGeometry()
        self.update()

    def tabSizeHint(self, index: int) -> QSize:
        size = super().tabSizeHint(index)
        size.setWidth(self._fixed_tab_width)
        return size


# @arch mix-browser.fixed-width-tabs component | en: Hosts the browser tab bar with fixed-width sizing | zh: 为浏览器承载固定宽度标签栏
class _FixedWidthTabWidget(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabBar(_FixedWidthTabBar(self))


# @arch mix-browser.window component | en: Coordinates the MIX browser workspace | zh: 协调 MIX 浏览器工作区
class MixBrowserWindow(QMainWindow):
    restart_requested = Signal()

    def __init__(
        self,
        task_executor: Executor,
        temporary_root: Path,
        *,
        startup_executor: Executor,
        interaction_help: InteractionHelpCatalog,
        progress_controller: TaskProgressController,
    ) -> None:
        super().__init__()
        self.setWindowTitle(APPLICATION_DISPLAY_NAME)
        self.setAcceptDrops(True)
        self._interaction_help = interaction_help
        interaction_help.register_gesture(
            "mix-browser.drop-actions",
            self.tr("Drop local files or folders"),
            self.tr("Open dropped MIX archives or folders, or add dropped files to the active tab."),
        )
        interaction_help.register_gesture(
            "mix-browser.drag-copy-items",
            self.tr("Drag selected rows"),
            self.tr("Copy selected files or MIX entries to another tab or an external application."),
        )
        interaction_help.register_gesture(
            "mix-browser.entry-context-menu",
            self.tr("Right-click a list item or empty list area"),
            self.tr("Open actions for selected filesystem items, MIX entries, or the list background."),
        )
        interaction_help.register_gesture(
            "mix-browser.add-user-palette-by-drop",
            self.tr("Drag .pal files into the user palette library"),
            self.tr("Drop local .pal files to copy them into the library with a blank regex rule."),
        )
        self._task_executor = task_executor
        self._startup_executor = startup_executor
        self._temporary_root = temporary_root
        self._progress_controller = progress_controller
        self._developer_tools_enabled = (
            not getattr(sys, "frozen", False)
            and os.environ.get("RA2AYRMB_DEVELOPER_TOOLS") == "1"
        )
        self._pages_by_path: dict[str, MixArchivePage | DirectoryBrowserPage] = {}
        self._unsaved_mix_roots: set[str] = set()
        self._saving_mix_roots: set[str] = set()
        self._untitled_mix_count = 0
        self._pending_paths: dict[str, Path] = {}
        self._reload_archives_when_idle = False
        self._pending_replacements: set[str] = set()
        self._directory_futures: dict[str, Future] = {}
        self._pending_drag_exports: dict[str, _PendingDragExport] = {}
        self._active_drag_status_root: Path | None = None
        self._pending_clipboard_export_token: str | None = None
        self._pending_clipboard_export_cancellation: Event | None = None
        self._startup_clipboard_cleanup_cancellation: Event | None = None
        self._deferred_startup_work_started = False
        self._clipboard_export_base = self._temporary_root.parent / "mix-browser-clipboard"
        self._clipboard_export_root = self._root_for_clipboard_paths(
            self._system_clipboard_paths()
        )
        self._open_progress_dialog: TaskProgressDialog | None = None
        self._open_progress_tasks: dict[str, tuple[Future | None, str]] = {}
        self._next_open_task_id = 0
        self._pending_search_selections: dict[str, Path] = {}
        self._pending_search_opens: dict[str, Path] = {}
        self._pending_search_drag_exports: dict[
            SearchResultsDialog,
            _PendingDragExport,
        ] = {}
        self._pending_titles: dict[str, str] = {}
        self._pending_ancestors: dict[str, tuple[tuple[str, str], ...]] = {}
        self._pending_locations: dict[str, str] = {}
        self._next_preview_request_id = 0
        self._preview_requests: dict[int, str] = {}
        self._preview_futures: dict[str, tuple[int, Future]] = {}
        self._preview_cancellations: dict[int, Event] = {}
        self._palette_catalog_preloads: dict[str, Future] = {}
        self._palette_catalog_cancellations: dict[str, Event] = {}
        self._palette_catalog_progress: dict[str, TaskProgressDialog] = {}
        self._progress_tasks: dict[int, _ExternalProgressTask] = {}
        self._next_progress_task_id = 0
        self._mix_clipboard: _MixClipboard | None = None
        self._pending_mix_clipboard: _MixClipboard | None = None
        self._tracked_external_files: dict[str, _TrackedExternalFile] = {}
        self._modified_external_files: list[str] = []
        self._pending_external_hashes: set[str] = set()
        self._hashing_external_files: set[str] = set()
        self._settings = create_application_settings()
        self._ui_language = self._settings.value("ui/language", "system", type=str)
        self._system_integration = SystemIntegrationApplication()
        self._pending_container_probe_results: dict[
            Path,
            tuple[Callable[[str, str | None], None], int],
        ] = {}
        self._next_container_probe_request_id = 0
        self._container_probe_result_timer = QTimer(self)
        self._container_probe_result_timer.setInterval(200)
        self._container_probe_result_timer.timeout.connect(
            self._poll_container_probe_results
        )
        self._visible_browser_type_filters = self._load_browser_type_filters()
        self._xcc_names_enabled = self._settings.value("mixNameSources/xcc", True, type=bool)
        self._community_names_enabled = self._settings.value(
            "mixNameSources/community", False, type=bool
        ) and community_name_database_path().is_file()
        self._community_database_size_bytes: int | None = None
        self._community_database_size_request_pending = False
        self._community_database_confirmation_page: MixNameSourcesPage | None = None
        self._community_database_confirmation_box: QMessageBox | None = None
        configured_name_game = self._settings.value(
            "mixNameSources/game",
            DEFAULT_MIX_NAME_GAME,
            type=str,
        )
        supported_name_games = {key for key, _label, _group in MIX_NAME_GAME_GROUPS}
        self._selected_name_game = (
            configured_name_game
            if configured_name_game in supported_name_games
            else DEFAULT_MIX_NAME_GAME
        )
        if self._selected_name_game != configured_name_game:
            self._settings.setValue(
                "mixNameSources/game",
                self._selected_name_game,
            )
        self._settings.setValue(
            "mixNameSources/community", self._community_names_enabled
        )
        palette_directory = self._settings.value(
            "preview/paletteGameDirectory",
            "",
            type=str,
        )
        self._palette_directory = Path(palette_directory) if palette_directory else None
        palette_library_setting = self._settings.value(
            "preview/paletteLibrary",
            "[]",
            type=str,
        )
        palette_manifest_path = _palette_library_manifest_path()
        palette_manifest_existed = palette_manifest_path.exists()
        palette_manifest_rules = _read_palette_library_manifest()
        configured_palette_rules = (
            palette_manifest_rules
            if palette_manifest_rules is not None
            else _read_palette_library_setting(palette_library_setting)
        )
        migrated_palette_rules = _migrate_user_palette_rules(
            configured_palette_rules
        )
        self._palette_library_rules = migrated_palette_rules
        serialized_palette_rules = _serialize_palette_library_setting(
            migrated_palette_rules
        )
        if serialized_palette_rules != palette_library_setting:
            self._settings.setValue(
                "preview/paletteLibrary",
                serialized_palette_rules,
            )
        if not palette_manifest_existed or (
            palette_manifest_rules is not None
            and migrated_palette_rules != palette_manifest_rules
        ):
            try:
                _write_palette_library_manifest(migrated_palette_rules)
            except OSError:
                pass
        palette_theater = self._settings.value(
            "preview/paletteTheater",
            "auto",
            type=str,
        )
        self._palette_theater = (
            palette_theater
            if palette_theater in {"auto", "tem", "sno", "urb", "des", "lun", "ubn"}
            else "auto"
        )
        self._auto_play_preferences = {
            "animations": self._settings.value(
                "preview/autoPlay/animations",
                False,
                type=bool,
            ),
            "audio": self._settings.value("preview/autoPlay/audio", False, type=bool),
            "video": self._settings.value("preview/autoPlay/video", False, type=bool),
        }
        self._archive_loader = MixArchiveLoader(
            xcc_names_enabled=self._xcc_names_enabled,
            community_names_enabled=self._community_names_enabled,
        )
        self._archive_loader.set_active_name_game(self._selected_name_game)
        self._archive_load_session = self._archive_loader.create_session()
        self._archive_application = MixArchiveApplication(self._archive_loader)
        self._browser_application = MixBrowserFeatureApplication(self._archive_loader)
        self._restore_active_path_key: str | None = None
        self._open_signals = _ArchiveOpenSignals(self)
        self._open_signals.completed.connect(self._on_archive_opened)
        self._preview_signals = _EntryPreviewSignals(self)
        self._preview_signals.completed.connect(self._on_entry_preview_completed)
        self._preview_signals.palette_completed.connect(
            self._on_entry_palette_update_completed
        )
        self._palette_catalog_signals = _PaletteCatalogSignals(self)
        self._palette_catalog_signals.scan_started.connect(
            self._on_palette_catalog_scan_started
        )
        self._palette_catalog_signals.snapshot_completed.connect(
            self._on_palette_catalog_snapshot_completed
        )
        self._palette_catalog_signals.completed.connect(
            self._on_palette_catalog_refresh_completed
        )
        self._community_name_database_signals = _CommunityNameDatabaseSignals(self)
        self._community_name_database_signals.progress.connect(
            self._on_community_name_database_progress
        )
        self._community_name_database_signals.completed.connect(
            self._on_community_name_database_download_completed
        )
        self._community_name_database_signals.download_confirmation_size_completed.connect(
            self._on_community_name_database_download_confirmation_size_completed
        )
        self._directory_signals = _DirectorySignals(self)
        self._directory_signals.completed.connect(self._on_directory_loaded)
        self._search_dialogs: set[SearchResultsDialog] = set()
        self._search_copy_context: SearchResultsDialog | None = None
        self._search_signals = _SearchSignals(self)
        self._search_signals.completed.connect(self._on_recursive_search_completed)
        self._search_drag_signals = _SearchDragSignals(self)
        self._search_drag_signals.completed.connect(
            self._on_search_drag_export_completed
        )
        self._external_open_signals = _ExternalOpenSignals(self)
        self._external_open_signals.progress.connect(self._on_progress_task_progress)
        self._external_open_signals.completed.connect(self._on_external_entry_extracted)
        self._external_open_signals.file_hash_completed.connect(self._on_external_file_hash_completed)
        self._temporary_files_signals = _TemporaryFilesSignals(self)
        self._temporary_files_signals.count_completed.connect(
            self._on_temporary_file_count_completed
        )
        self._temporary_files_signals.cleanup_completed.connect(
            self._on_temporary_file_cleanup_completed
        )
        QGuiApplication.clipboard().dataChanged.connect(self._on_system_clipboard_changed)
        self._clipboard_export_signals = _ClipboardExportSignals(self)
        self._clipboard_export_signals.completed.connect(self._on_clipboard_export_completed)
        self._drag_export_signals = _DragExportSignals(self)
        self._drag_export_signals.completed.connect(self._on_drag_export_completed)
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.fileChanged.connect(self._queue_external_file_hash)
        self._file_watcher.directoryChanged.connect(self._queue_external_directory_hash)
        self._external_hash_timer = QTimer(self)
        self._external_hash_timer.setSingleShot(True)
        self._external_hash_timer.setInterval(350)
        self._external_hash_timer.timeout.connect(self._check_pending_external_hashes)
        self._external_poll_timer = QTimer(self)
        self._external_poll_timer.setInterval(1500)
        self._external_poll_timer.timeout.connect(self._poll_external_file_signatures)
        self._external_poll_timer.start()

        self._create_main_menus()

        self.tabs = _FixedWidthTabWidget(self)
        self.tabs.setObjectName("MixArchiveTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tabs.tabBar().customContextMenuRequested.connect(
            self._show_tab_context_menu
        )
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self._search_action.setEnabled(False)
        self._sync_workspace_actions()

        self.empty_state = QLabel(self.tr("No MIX archive open"))
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.container = QWidget(self)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self._create_modified_file_banner()
        self.container_layout.addWidget(self._modified_file_banner)
        self.container_layout.addWidget(self.empty_state)
        self.container_layout.addWidget(self.tabs)
        self.setCentralWidget(self.container)
        self._create_split_status_bar()
        self._sync_empty_state()
        self._register_drop_targets(self)

    def start_deferred_startup_work(self) -> None:
        if self._deferred_startup_work_started:
            return
        self._deferred_startup_work_started = True
        self._startup_executor.submit(self._archive_loader.prewarm_name_sources)
        self._cleanup_stale_clipboard_exports()

    def preload_entry_preview(self) -> None:
        preview = _create_entry_preview(self)
        preview.hide()
        preview.prepare_media_runtime()
        preview.shutdown()
        preview.deleteLater()

    def _create_main_menus(self) -> None:
        file_menu = self.menuBar().addMenu(self.tr("File"))
        edit_menu = self.menuBar().addMenu(self.tr("Edit / 编辑"))
        self._game_selection_action = QAction(self.tr("Game..."), self)
        self._game_selection_action.triggered.connect(self._open_game_selection)
        self.menuBar().addAction(self._game_selection_action)
        help_menu = self.menuBar().addMenu(self.tr("Help"))

        self._create_mix_action = QAction(self.tr("Create MIX Archive"), self)
        self._create_mix_action.triggered.connect(self._create_mix)
        self._save_mix_action = self._interaction_help.create_action(
            self,
            entry_id="mix-browser.save-runtime-mix",
            text=self.tr("Save MIX..."),
            shortcut=QKeySequence.StandardKey.Save,
            description=self.tr("Choose a file path for a newly created MIX archive."),
        )
        self._save_mix_action.triggered.connect(self._save_mix)
        self.addAction(self._save_mix_action)
        self._save_mix_as_action = self._interaction_help.create_action(
            self,
            entry_id="mix-browser.save-mix-as",
            text=self.tr("Save MIX As..."),
            shortcut=QKeySequence.StandardKey.SaveAs,
            description=self.tr("Save the open MIX archive to another file path."),
        )
        self._save_mix_as_action.triggered.connect(self._save_mix_as)
        self.addAction(self._save_mix_as_action)
        self._new_file_action = QAction(self.tr("New File Here (including MIX)..."), self)
        self._new_file_action.setToolTip(self.tr("Create an empty file or MIX archive in the active location"))
        self._new_file_action.triggered.connect(self._create_file_entry)
        self._new_folder_action = QAction(self.tr("New Folder Here..."), self)
        self._new_folder_action.triggered.connect(self._create_directory_entry)
        self._add_files_action = QAction(self.tr("Add Files Here..."), self)
        self._add_files_action.triggered.connect(self._choose_files_to_add)
        self._open_archives_action = QAction(self.tr("Open MIX File..."), self)
        self._open_archives_action.triggered.connect(self._choose_archives)
        self._open_directory_action = QAction(self.tr("Open Folder..."), self)
        self._open_directory_action.triggered.connect(self._choose_directory)
        self._open_game_directory_action = QAction(self.tr("Open Game Folder"), self)
        self._open_game_directory_action.triggered.connect(self._open_game_directory)

        self._copy_action = self._interaction_help.create_action(
            self,
            entry_id="mix-browser.copy-browser-items",
            text=self.tr("Copy"),
            shortcut=QKeySequence.StandardKey.Copy,
            description=self.tr("Copy selected browser items or search results to the system clipboard."),
        )
        self._copy_action.triggered.connect(self._copy_selected_entries)
        self._paste_action = self._interaction_help.create_action(
            self,
            entry_id="mix-browser.paste-browser-items",
            text=self.tr("Paste"),
            shortcut=QKeySequence.StandardKey.Paste,
            description=self.tr("Paste files from the system clipboard or copied MIX entries into the active location."),
        )
        self._paste_action.triggered.connect(self._paste_selected_entries)
        self._rename_action = self._interaction_help.create_action(
            self,
            entry_id="mix-browser.rename-browser-item",
            text=self.tr("Rename"),
            shortcut="F2",
            description=self.tr("Rename the selected filesystem item or MIX entry."),
        )
        self._rename_action.triggered.connect(self._rename_selected_entry)
        self._delete_action = self._interaction_help.create_action(
            self,
            entry_id="mix-browser.delete-browser-items",
            text=self.tr("Delete"),
            shortcut=QKeySequence.StandardKey.Delete,
            description=self.tr("Delete the selected filesystem items or MIX entries."),
        )
        self._delete_action.triggered.connect(self._delete_selected_entries)
        for action in (
            self._copy_action,
            self._paste_action,
            self._rename_action,
            self._delete_action,
        ):
            self.addAction(action)
            edit_menu.addAction(action)

        self._search_action = self._interaction_help.create_action(
            self,
            entry_id="mix-browser.recursive-search",
            text=self.tr("Search from Root..."),
            shortcut=QKeySequence.StandardKey.Find,
            description=self.tr("Search recursively from the current root."),
        )
        self._search_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.addAction(self._search_action)
        self._search_action.triggered.connect(self._open_recursive_search)
        self._preferences_action = QAction(
            self.tr("Preferences... / 首选项..."), self
        )
        self._preferences_action.triggered.connect(self._open_preferences)
        self._about_action = QAction(
            self.tr("About {0}...").format(APPLICATION_DISPLAY_NAME),
            self,
        )
        self._about_action.triggered.connect(self._open_about)
        self._palette_naming_guide_action = QAction(
            self.tr("Asset Filename Guide for INI Palette References..."),
            self,
        )
        self._palette_naming_guide_action.triggered.connect(
            self._open_palette_naming_guide
        )
        self._preview_support_action = QAction(
            self.tr("Preview Support..."),
            self,
        )
        self._preview_support_action.triggered.connect(self._open_preview_support)

        for action in (
            self._create_mix_action,
            self._save_mix_action,
            self._save_mix_as_action,
        ):
            file_menu.addAction(action)
        file_menu.addSeparator()
        for action in (
            self._new_file_action,
            self._new_folder_action,
            self._add_files_action,
        ):
            file_menu.addAction(action)
        file_menu.addSeparator()
        for action in (
            self._open_archives_action,
            self._open_directory_action,
            self._open_game_directory_action,
        ):
            file_menu.addAction(action)
        edit_menu.addSeparator()
        edit_menu.addAction(self._search_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self._preferences_action)
        help_menu.addAction(self._preview_support_action)
        help_menu.addAction(self._palette_naming_guide_action)
        help_menu.addSeparator()
        help_menu.addAction(self._about_action)
        self._sync_workspace_actions()

    def _open_about(self) -> None:
        AboutDialog(self).exec()

    def _open_preview_support(self) -> None:
        PreviewSupportDialog(self).exec()

    def _open_game_selection(self) -> None:
        dialog = GameSelectionDialog(
            self._selected_name_game,
            xcc_names_enabled=self._xcc_names_enabled,
            community_names_enabled=self._community_names_enabled,
            community_database_downloaded=community_name_database_path().is_file(),
            palette_directory_configured=self._palette_directory is not None,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._set_mix_name_game(dialog.selected_game)

    def _set_mix_name_game(self, game: str) -> None:
        if game == self._selected_name_game:
            return
        game_labels = {
            key: label
            for key, label, _database_group in MIX_NAME_GAME_GROUPS
        }
        game_label = self.tr(game_labels[game])
        self._selected_name_game = game
        self._settings.setValue("mixNameSources/game", game)
        self._archive_loader.set_active_name_game(game)
        self._archive_load_session = self._archive_loader.create_session()
        self._reload_open_archives()
        if game == "ra" and (
            not self._community_names_enabled
            or not community_name_database_path().is_file()
        ):
            self.statusBar().showMessage(
                self.tr(
                    "{0} name lookup needs the optional CnCNet database. Download and enable it in Preferences > MIX Name Sources."
                ).format(game_label),
                10000,
            )

    def _open_palette_naming_guide(self) -> None:
        PaletteNamingGuideDialog(self).exec()

    # @arch mix-browser.game-directory-setup-prompt handler | en: Offers game-directory setup when no directory is configured | zh: 未设置游戏目录时提供目录设置入口
    def prompt_missing_game_directory(self) -> None:
        if self._palette_directory is not None or self._settings.value(
            "startup/dismissGameDirectoryPrompt",
            False,
            type=bool,
        ):
            return

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle(self.tr("Game Directory Not Set"))
        message.setText(self.tr("No RA2/YR game directory is configured."))
        message.setInformativeText(
            self.tr(
                "Game files are not bundled with this application. Set your RA2/YR "
                "game directory under Preferences > Palette Sources to use its "
                "palettes and art rules in previews."
            )
        )
        set_directory_button = message.addButton(
            self.tr("Set Game Directory..."),
            QMessageBox.ButtonRole.AcceptRole,
        )
        message.addButton(
            self.tr("Later"),
            QMessageBox.ButtonRole.RejectRole,
        )
        message.setDefaultButton(set_directory_button)
        dont_show_checkbox = QCheckBox(self.tr("Don't show this again"))
        dont_show_checkbox.setChecked(False)
        message.setCheckBox(dont_show_checkbox)
        message.exec()

        if dont_show_checkbox.isChecked():
            self._settings.setValue("startup/dismissGameDirectoryPrompt", True)
            self._settings.sync()
        if message.clickedButton() is set_directory_button:
            self._open_preferences("palette")

    def _open_preferences(self, initial_tab: str = "playback") -> None:
        try:
            system_state = self._system_integration.get_state()
        except ApplicationApiError as exc:
            QMessageBox.warning(
                self,
                self.tr("System Integration"),
                self.tr("The Windows registration state could not be read: {0}").format(
                    exc.message
                ),
            )
            return
        dialog = PreferencesDialog(
            self._auto_play_preferences,
            self._xcc_names_enabled,
            self._community_names_enabled,
            community_name_database_path().is_file(),
            str(self._palette_directory or ""),
            self._palette_theater,
            self._palette_library_rules,
            system_state,
            self._ui_language,
            self,
        )
        dialog.system_integration.open_container_default_requested.connect(
            lambda extension, page=dialog.system_integration: self._open_container_default_from_preferences(
                extension,
                page,
            )
        )
        dialog.palette_sources.refresh_palette_requested.connect(
            lambda page=dialog.palette_sources: self._start_palette_catalog_refresh(page)
        )
        dialog.mix_name_sources.download_community_requested.connect(
            lambda page=dialog.mix_name_sources: self._request_community_name_database_download(page)
        )
        dialog.temporary_files.refresh_requested.connect(
            lambda page=dialog.temporary_files: self._count_temporary_files(page)
        )
        dialog.temporary_files.clean_requested.connect(
            lambda page=dialog.temporary_files: self._request_temporary_file_cleanup(page)
        )
        dialog.temporary_files.open_folder_requested.connect(
            self._open_temporary_file_folder
        )
        if initial_tab == "palette":
            dialog.tabs.setCurrentWidget(dialog.palette_sources)
        self._count_temporary_files(dialog.temporary_files)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            previous_language = self._ui_language
            state_before_apply = self._system_integration.get_state()
            if not self._apply_preferences(dialog):
                return
            current_state = self._system_integration.get_state()
            previous_handlers = state_before_apply.get(
                "container_file_associations", {}
            )
            current_handlers = current_state.get("container_file_associations", {})
            current_defaults = current_state.get("container_file_is_default", {})
            default_sample_extensions: list[str] = []
            for extension in sorted(MIX_CONTAINER_SUFFIXES):
                if (
                    not bool(previous_handlers.get(extension))
                    and bool(current_handlers.get(extension))
                ):
                    default_sample_extensions.append(extension)
                elif (
                    self._developer_tools_enabled
                    and bool(state_before_apply.get("container_file_is_default", {}).get(extension))
                    and not bool(current_handlers.get(extension))
                    and bool(current_defaults.get(extension))
                ):
                    default_sample_extensions.append(extension)
            if default_sample_extensions:
                setup_dialog = ContainerDefaultHandlerDialog(
                    tuple(default_sample_extensions),
                    self,
                )
                setup_dialog.open_sample_requested.connect(
                    lambda extension, target=setup_dialog: self._open_container_default_sample(
                        extension,
                        lambda result, error, suffix=extension, dialog=target: dialog.set_probe_result(
                            suffix,
                            result,
                            error,
                        ),
                    )
                )
                setup_dialog.exec()
            if self._ui_language != previous_language:
                restart_dialog = QMessageBox(self)
                restart_dialog.setIcon(QMessageBox.Icon.Question)
                restart_dialog.setWindowTitle(
                    self.tr("Restart Application / 重启应用")
                )
                restart_dialog.setText(
                    self.tr(
                        "The language selection has been saved. Restart now to apply it? / "
                        "语言设置已保存。现在重启以应用更改吗？"
                    )
                )
                restart_button = restart_dialog.addButton(
                    self.tr("Yes / 是"),
                    QMessageBox.ButtonRole.YesRole,
                )
                later_button = restart_dialog.addButton(
                    self.tr("No / 否"),
                    QMessageBox.ButtonRole.NoRole,
                )
                restart_dialog.setDefaultButton(later_button)
                restart_dialog.exec()
                if restart_dialog.clickedButton() is restart_button:
                    self.restart_requested.emit()

    def _count_temporary_files(self, page: TemporaryFilesSettingsPage) -> None:
        page.show_counting()
        future = self._task_executor.submit(
            count_temporary_files,
            self._temporary_root,
        )
        future.add_done_callback(
            lambda completed, target=page: self._forward_temporary_file_count(
                target,
                completed,
            )
        )

    def _forward_temporary_file_count(
        self,
        page: TemporaryFilesSettingsPage,
        future: Future,
    ) -> None:
        try:
            count = future.result()
        except Exception as exc:
            count = None
            error = str(exc)
        else:
            error = ""
        try:
            self._temporary_files_signals.count_completed.emit(page, count, error)
        except RuntimeError:
            return

    @Slot(object, object, str)
    def _on_temporary_file_count_completed(
        self,
        page: object,
        count: object,
        error: str,
    ) -> None:
        if not isinstance(page, TemporaryFilesSettingsPage):
            return
        try:
            if error or not isinstance(count, int):
                page.show_count_error(error or self.tr("The file count is unavailable."))
            else:
                page.show_count_result(count)
        except RuntimeError:
            return

    def _request_temporary_file_cleanup(
        self,
        page: TemporaryFilesSettingsPage,
    ) -> None:
        count = page.file_count
        if count is None:
            return
        if count <= 0:
            page.show_count_result(0)
            return

        if self._unsaved_mix_roots:
            QMessageBox.information(
                self,
                self.tr("Temporary Files"),
                self.tr("Save or close unsaved MIX archives before cleaning temporary files."),
            )
            return
        if (
            self._progress_tasks
            or self._open_progress_tasks
            or self._pending_paths
            or self._pending_drag_exports
            or self._pending_search_drag_exports
        ):
            QMessageBox.information(
                self,
                self.tr("Temporary Files"),
                self.tr("Wait for active operations to finish before cleaning temporary files."),
            )
            return

        answer = QMessageBox.question(
            self,
            self.tr("Clean Temporary Files"),
            self.tr(
                "Delete {0} temporary files? This includes files opened from MIX "
                "archives; unsaved changes in external applications will be lost."
            ).format(count),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        page.show_cleaning()
        self._remove_external_file_watches()
        future = self._task_executor.submit(
            clean_temporary_files,
            self._temporary_root,
        )
        future.add_done_callback(
            lambda completed, target=page: self._forward_temporary_file_cleanup(
                target,
                completed,
            )
        )

    def _forward_temporary_file_cleanup(
        self,
        page: TemporaryFilesSettingsPage,
        future: Future,
    ) -> None:
        try:
            result = future.result()
        except Exception as exc:
            result = None
            error = str(exc)
        else:
            error = ""
        try:
            self._temporary_files_signals.cleanup_completed.emit(page, result, error)
        except RuntimeError:
            return

    @Slot(object, object, str)
    def _on_temporary_file_cleanup_completed(
        self,
        page: object,
        result: object,
        error: str,
    ) -> None:
        if not isinstance(page, TemporaryFilesSettingsPage):
            return
        if error or not isinstance(result, TemporaryFileCleanupResult):
            self._restore_external_file_watches()
            try:
                page.show_cleanup_error(error or self.tr("Cleanup could not be completed."))
            except RuntimeError:
                pass
            return

        for path_key, tracked in tuple(self._tracked_external_files.items()):
            if tracked.path.exists():
                continue
            self._tracked_external_files.pop(path_key, None)
            self._pending_external_hashes.discard(path_key)
            self._hashing_external_files.discard(path_key)
            self._remove_modified_external_file(path_key)
        self._restore_external_file_watches()
        self._sync_modified_file_banner()
        try:
            page.show_cleanup_result(result)
        except RuntimeError:
            return

    def _remove_external_file_watches(self) -> None:
        watched_paths = tuple(
            dict.fromkeys(
                (*self._file_watcher.files(), *self._file_watcher.directories())
            )
        )
        if watched_paths:
            self._file_watcher.removePaths(list(watched_paths))

    def _restore_external_file_watches(self) -> None:
        watched_files = set(self._file_watcher.files())
        watched_directories = set(self._file_watcher.directories())
        for tracked in self._tracked_external_files.values():
            if not tracked.path.is_file():
                continue
            file_path = str(tracked.path)
            if file_path not in watched_files and self._file_watcher.addPath(file_path):
                watched_files.add(file_path)
            directory_path = str(tracked.path.parent)
            if (
                directory_path not in watched_directories
                and tracked.path.parent.is_dir()
                and self._file_watcher.addPath(directory_path)
            ):
                watched_directories.add(directory_path)

    def _open_temporary_file_folder(self) -> None:
        try:
            opened = QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self._temporary_root))
            )
        except Exception:
            opened = False
        if not opened:
            QMessageBox.warning(
                self,
                self.tr("Temporary Files"),
                self.tr("Could not open the temporary folder:\n{0}").format(
                    self._temporary_root
                ),
            )

    def _apply_preferences(self, dialog: PreferencesDialog) -> bool:
        palette_page = dialog.palette_sources
        import_failures = palette_page.commit_pending_palette_imports()
        if import_failures:
            QMessageBox.warning(
                self,
                self.tr("Palette Import Failed"),
                self.tr(
                    "Could not import one or more palette files into the program's palette library:\n{0}"
                ).format("\n".join(import_failures)),
            )
            return False

        palette_library = palette_page.palette_library_rules()
        try:
            _write_palette_library_manifest(palette_library)
        except OSError as exc:
            rollback_failures = palette_page.rollback_pending_palette_imports()
            details = str(exc)
            if rollback_failures:
                details += "\n" + "\n".join(rollback_failures)
            QMessageBox.warning(
                self,
                self.tr("Palette Settings Could Not Be Saved"),
                self.tr(
                    "The palette library configuration could not be saved beside its files:\n{0}"
                ).format(details),
            )
            return False
        palette_page.finalize_pending_palette_imports()

        for preference, checkbox in dialog.auto_play_checkboxes.items():
            enabled = checkbox.isChecked()
            if enabled != self._auto_play_preferences[preference]:
                self._set_auto_play_preference(preference, enabled)

        xcc_enabled = dialog.mix_name_sources.xcc_checkbox.isChecked()
        community_enabled = dialog.mix_name_sources.community_checkbox.isChecked()
        if (xcc_enabled, community_enabled) != (
            self._xcc_names_enabled,
            self._community_names_enabled,
        ):
            self._xcc_names_enabled = xcc_enabled
            self._community_names_enabled = community_enabled
            self._settings.setValue("mixNameSources/xcc", xcc_enabled)
            self._settings.setValue("mixNameSources/community", community_enabled)
            self._archive_loader.set_name_sources(
                xcc=xcc_enabled,
                community=community_enabled,
            )
            self._archive_load_session = self._archive_loader.create_session()
            self._reload_open_archives()

        raw_directory = palette_page.directory_edit.text().strip()
        directory = Path(raw_directory).expanduser() if raw_directory else None
        if directory is not None:
            try:
                directory = directory.resolve()
            except OSError:
                pass
        theater = palette_page.theater_combo.currentData()
        if (
            directory != self._palette_directory
            or theater != self._palette_theater
            or palette_library != self._palette_library_rules
        ):
            self._palette_directory = directory
            self._palette_theater = theater
            self._palette_library_rules = palette_library
            if directory is not None:
                self._ensure_game_palette_catalog_snapshot(directory)
            self._settings.setValue(
                "preview/paletteGameDirectory",
                str(directory) if directory is not None else "",
            )
            self._settings.setValue("preview/paletteTheater", theater)
            self._settings.setValue(
                "preview/paletteLibrary",
                _serialize_palette_library_setting(palette_library),
            )
            self._refresh_current_preview()

        ui_language = dialog.language_combo.currentData()
        if ui_language != self._ui_language:
            self._ui_language = ui_language
            self._settings.setValue("ui/language", ui_language)

        if palette_page.has_pending_user_palette_deletions:
            self._settings.sync()
            if self._settings.status() != QSettings.Status.NoError:
                QMessageBox.warning(
                    self,
                    self.tr("Settings Save Warning"),
                    self.tr(
                        "The portable palette configuration was saved, but some application preferences could not be saved."
                    ),
                )
            palette_file_removal_failures = (
                palette_page.delete_unreferenced_palette_copies(palette_library)
            )
            if palette_file_removal_failures:
                QMessageBox.warning(
                    self,
                    self.tr("Palette File Removal Failed"),
                    self.tr("Some palette copies could not be removed:\n{0}").format(
                        "\n".join(palette_file_removal_failures)
                    ),
                )

        if bool(dialog.system_integration.initial_state.get("supported")):
            registrations = dialog.system_integration.registrations()
            try:
                self._system_integration.configure(**registrations)
            except ApplicationApiError as exc:
                QMessageBox.warning(
                    self,
                    self.tr("System Integration"),
                    self.tr(
                        "Other preferences were saved, but Windows shell registration "
                        "could not be updated:\n{0}"
                    ).format(exc.message),
                )

        return True

    def _open_container_default_sample(
        self,
        extension: str,
        result_callback: Callable[[str, str | None], None],
    ) -> None:
        probe_path: Path | None = None
        request_id: int | None = None
        try:
            probe_path = create_container_association_probe(extension)
            cleanup_container_association_probe_result(probe_path)
            self._next_container_probe_request_id += 1
            request_id = self._next_container_probe_request_id
            self._pending_container_probe_results[probe_path] = (
                result_callback,
                request_id,
            )
            if not self._container_probe_result_timer.isActive():
                self._container_probe_result_timer.start()
            self._system_integration.open_container_file_with_windows_default(
                probe_path
            )
        except (OSError, ApplicationApiError) as exc:
            if probe_path is not None:
                self._pending_container_probe_results.pop(probe_path, None)
                cleanup_container_association_probe_result(probe_path)
            if not self._pending_container_probe_results:
                self._container_probe_result_timer.stop()
            result_callback("error", getattr(exc, "message", str(exc)))
            return

        QTimer.singleShot(
            60_000,
            lambda sample=probe_path, identifier=request_id: self._expire_container_probe_result(
                sample,
                identifier,
            ),
        )

    def _poll_container_probe_results(self) -> None:
        for probe_path, (callback, _request_id) in tuple(
            self._pending_container_probe_results.items()
        ):
            result = consume_container_association_probe_result(probe_path)
            if result is None:
                continue
            self._pending_container_probe_results.pop(probe_path, None)
            cleanup_container_association_probe_result(probe_path)
            try:
                callback(result, None)
            except RuntimeError:
                continue
        if not self._pending_container_probe_results:
            self._container_probe_result_timer.stop()

    def _expire_container_probe_result(
        self,
        probe_path: Path,
        request_id: int | None,
    ) -> None:
        pending = self._pending_container_probe_results.get(probe_path)
        if pending is None or pending[1] != request_id:
            return
        self._pending_container_probe_results.pop(probe_path, None)
        cleanup_container_association_probe_result(probe_path)
        callback, _request_id = pending
        try:
            callback("timeout", None)
        except RuntimeError:
            pass
        if not self._pending_container_probe_results:
            self._container_probe_result_timer.stop()

    def _open_container_default_from_preferences(
        self,
        extension: str,
        settings_page: SystemIntegrationSettingsPage,
    ) -> None:
        try:
            state = self._system_integration.configure(
                container_file_associations={extension: True}
            )
        except ApplicationApiError as exc:
            QMessageBox.warning(
                self,
                self.tr("System Integration"),
                self.tr("The {0} handler could not be registered: {1}").format(
                    extension, exc.message
                ),
            )
            return

        settings_page.update_container_file_state(extension, state)
        settings_page.set_probe_pending(extension)
        self._open_container_default_sample(
            extension,
            lambda result, error: settings_page.set_probe_result(
                extension,
                result,
                error,
            ),
        )

    def _load_browser_type_filters(self) -> set[str]:
        raw = self._settings.value("browser/visibleTypeFiltersV2", None)
        legacy_setting = raw is None
        if legacy_setting:
            raw = self._settings.value("browser/visibleTypeFilters", None)
        if raw is None:
            raw = self._settings.value("browser/filterBarTypes", "", type=str)
        if not raw:
            return set(DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS)
        try:
            values = json.loads(raw)
        except (TypeError, ValueError):
            return set(DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS)
        if not isinstance(values, list):
            return set(DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS)
        selected = {
            value
            for value in values
            if isinstance(value, str) and value in CONFIGURABLE_BROWSER_TYPE_FILTERS
        }
        if legacy_setting:
            selected.difference_update({"Folder", "MIX"})
        selected.add(OTHER_FILE_TYPE_FILTER)
        return selected

    def _configure_entry_type_filters(self, entry_table: EntryTable) -> None:
        entry_table.set_visible_type_filters(self._visible_browser_type_filters)
        entry_table.visible_type_filters_changed.connect(
            self._save_browser_type_filters
        )

    def _save_browser_type_filters(self, values: object) -> None:
        if not isinstance(values, (set, frozenset)):
            return
        selected = set(values) & set(CONFIGURABLE_BROWSER_TYPE_FILTERS)
        selected.add(OTHER_FILE_TYPE_FILTER)
        if selected == self._visible_browser_type_filters:
            return

        self._visible_browser_type_filters = selected
        type_order = tuple(
            dict.fromkeys(
                (
                    *DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS,
                    *CONFIGURABLE_BROWSER_TYPE_FILTERS,
                )
            )
        )
        self._settings.setValue(
            "browser/visibleTypeFiltersV2",
            json.dumps([key for key in type_order if key in selected]),
        )
        for page in tuple(self._pages_by_path.values()):
            page.entry_table.set_visible_type_filters(selected)

    def _set_auto_play_preference(self, preference: str, enabled: bool) -> None:
        self._auto_play_preferences[preference] = enabled
        self._settings.setValue(f"preview/autoPlay/{preference}", enabled)
        for page in self._pages_by_path.values():
            self._apply_auto_play_preferences(page)

    def _sync_workspace_actions(self, *_args) -> None:
        if not hasattr(self, "_add_files_action"):
            return
        page = self.tabs.currentWidget() if hasattr(self, "tabs") else None
        is_mix = isinstance(page, MixArchivePage)
        is_directory = isinstance(page, DirectoryBrowserPage)
        selected = self._selected_entries(page)
        shortcut_parent = page.table if is_mix else self
        for action in (
            self._copy_action,
            self._paste_action,
            self._rename_action,
            self._delete_action,
        ):
            if action.parent() is not shortcut_parent:
                action.setParent(shortcut_parent)
        editable = bool(selected) and not any(
            isinstance(entry, MixEntry)
            and (entry.name or "").casefold() == LOCAL_MIX_DATABASE_NAME.casefold()
            for entry in selected
        )
        self._new_file_action.setEnabled(is_mix or is_directory)
        self._new_folder_action.setEnabled(is_directory)
        self._add_files_action.setEnabled(is_mix or is_directory)
        search_dialog = self._search_copy_context
        if search_dialog not in self._search_dialogs:
            search_dialog = None
        self._copy_action.setEnabled(
            bool(search_dialog.selected_hits())
            if search_dialog is not None
            else editable
        )
        self._delete_action.setEnabled(editable)
        self._rename_action.setEnabled(editable and len(selected) == 1)
        unsaved_root_key = self._unsaved_root_key_for_page(page)
        self._save_mix_action.setEnabled(
            unsaved_root_key is not None
            and unsaved_root_key not in self._saving_mix_roots
        )
        mix_root_key = self._mix_root_key_for_page(page)
        self._save_mix_as_action.setEnabled(
            mix_root_key is not None
            and mix_root_key not in self._saving_mix_roots
        )
        clipboard_paths = self._system_clipboard_paths()
        native_mix_copy = self._mix_clipboard_matches(clipboard_paths)
        has_clipboard_paths = bool(clipboard_paths)
        self._paste_action.setEnabled(
            (is_mix or is_directory)
            and (native_mix_copy or has_clipboard_paths)
            and self._pending_clipboard_export_token is None
        )
        self._search_action.setEnabled(is_mix or is_directory)

    @staticmethod
    def _system_clipboard_paths() -> tuple[Path, ...]:
        mime_data = QGuiApplication.clipboard().mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return ()
        return tuple(
            Path(url.toLocalFile())
            for url in mime_data.urls()
            if url.isLocalFile() and url.toLocalFile()
        )

    @staticmethod
    def _normalized_paths(paths: tuple[Path, ...]) -> tuple[str, ...]:
        return tuple(os.path.normcase(os.path.abspath(path)) for path in paths)

    def _mix_clipboard_matches(self, clipboard_paths: tuple[Path, ...]) -> bool:
        return (
            self._mix_clipboard is not None
            and bool(self._mix_clipboard.exported_paths)
            and self._normalized_paths(clipboard_paths)
            == self._normalized_paths(self._mix_clipboard.exported_paths)
        )

    def _root_for_clipboard_paths(self, paths: tuple[Path, ...]) -> Path | None:
        if not paths:
            return None
        base = Path(os.path.abspath(self._clipboard_export_base))
        roots: set[Path] = set()
        for path in paths:
            try:
                relative = Path(os.path.abspath(path)).relative_to(base)
            except ValueError:
                continue
            if relative.parts and relative.parts[0].startswith("copy-"):
                roots.add(base / relative.parts[0])
        if len(roots) != 1:
            return None
        root = next(iter(roots))
        try:
            if (
                root.parent.resolve() != self._clipboard_export_base.resolve()
                or not root.name.startswith("copy-")
            ):
                return None
        except OSError:
            return None
        return root

    def _cleanup_stale_clipboard_exports(self) -> None:
        active_root = self._root_for_clipboard_paths(self._system_clipboard_paths())
        self._clipboard_export_root = active_root
        try:
            stale_roots = tuple(
                candidate
                for candidate in self._clipboard_export_base.iterdir()
                if candidate.name.startswith("copy-")
                and candidate != active_root
                and candidate.is_dir()
            )
        except OSError:
            return
        if not stale_roots:
            return
        cancellation = Event()
        self._startup_clipboard_cleanup_cancellation = cancellation
        self._startup_executor.submit(
            _remove_stale_clipboard_exports,
            stale_roots,
            cancellation,
        )

    def _on_system_clipboard_changed(self) -> None:
        if self._startup_clipboard_cleanup_cancellation is not None:
            self._startup_clipboard_cleanup_cancellation.set()
        paths = self._system_clipboard_paths()
        current_root = self._root_for_clipboard_paths(paths)
        if self._mix_clipboard is not None and not self._mix_clipboard_matches(paths):
            self._mix_clipboard = None
        previous_root = self._clipboard_export_root
        if previous_root is not None and current_root != previous_root:
            self._schedule_clipboard_export_cleanup(previous_root)
        self._clipboard_export_root = current_root
        self._cancel_pending_clipboard_export()
        self._sync_workspace_actions()

    def _schedule_clipboard_export_cleanup(self, export_root: Path) -> None:
        QTimer.singleShot(
            300_000,
            self,
            lambda root=export_root: self._cleanup_clipboard_export(root),
        )

    def _cleanup_clipboard_export(self, export_root: Path) -> None:
        if export_root != self._clipboard_export_root:
            shutil.rmtree(export_root, ignore_errors=True)

    def _cancel_pending_clipboard_export(self) -> None:
        was_pending = self._pending_clipboard_export_token is not None
        if self._pending_clipboard_export_cancellation is not None:
            self._pending_clipboard_export_cancellation.set()
        self._pending_clipboard_export_cancellation = None
        self._pending_clipboard_export_token = None
        self._pending_mix_clipboard = None
        if was_pending and self.statusBar().currentMessage() in {
            "Preparing MIX entries for the system clipboard...",
            "Preparing search results for the system clipboard...",
        }:
            self.statusBar().clearMessage()

    def _selected_entries(self, page) -> tuple[MixEntry | DirectoryEntry, ...]:
        if isinstance(page, MixArchivePage):
            return self._selected_mix_entries(page)
        if isinstance(page, DirectoryBrowserPage):
            return self._selected_directory_entries(page)
        return ()

    @staticmethod
    def _selected_mix_entries(page: MixArchivePage) -> tuple[MixEntry, ...]:
        model = page.entry_table.source_model
        if not isinstance(model, MixEntryTableModel):
            return ()
        selected = page.table.selectionModel().selectedRows()
        if not selected and page.table.currentIndex().isValid():
            selected = [page.table.currentIndex()]
        return tuple(
            entry
            for index in selected
            if (entry := model.entry_at(index.row())) is not None
        )

    @staticmethod
    def _selected_directory_entries(page: DirectoryBrowserPage) -> tuple[DirectoryEntry, ...]:
        model = page.entry_table.source_model
        if not isinstance(model, DirectoryEntryTableModel):
            return ()
        selected = page.table.selectionModel().selectedRows()
        if not selected and page.table.currentIndex().isValid():
            selected = [page.table.currentIndex()]
        return tuple(
            entry
            for index in selected
            if (entry := model.entry_at(index.row())) is not None
        )

    # @arch mix-browser.entry-context-menu handler | en: Shows actions available for a selected browser item | zh: 显示当前浏览对象可执行的上下文操作
    def _show_entry_context_menu(self, page, position) -> None:
        index = page.table.indexAt(position)
        if index.isValid() and not page.table.selectionModel().isSelected(index):
            page.table.selectionModel().setCurrentIndex(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        elif not index.isValid():
            page.table.clearSelection()
            page.table.setCurrentIndex(QModelIndex())
        if self.tabs.currentWidget() is not page:
            self.tabs.setCurrentWidget(page)
        self._sync_workspace_actions()
        menu = QMenu(self)
        menu.setSeparatorsCollapsible(False)
        selected = self._selected_entries(page)
        if selected:
            if len(selected) == 1:
                entry = selected[0]
                if self._entry_is_browsable(entry):
                    browse_action = menu.addAction(self.tr("Browse with this app"))
                    browse_action.triggered.connect(
                        lambda _checked=False, target=page, target_index=page.table.currentIndex(): self._browse_selected_entry(
                            target,
                            target_index,
                        )
                    )
                system_open_action = menu.addAction(self.tr("Open with system default"))
                system_open_action.triggered.connect(
                    lambda _checked=False, target=page, target_index=page.table.currentIndex(): self._open_selected_with_system_default(
                        target,
                        target_index,
                    )
                )
                menu.addSeparator()

            menu.addAction(self._copy_action)
            menu.addAction(self._paste_action)
        if selected:
            menu.addAction(self._rename_action)
            menu.addAction(self._delete_action)
            menu.addSeparator()
            menu.addSeparator()
        else:
            menu.addAction(self._paste_action)
            menu.addSeparator()
        menu.addAction(self._new_file_action)
        if isinstance(page, MixArchivePage):
            menu.addAction(self._add_files_action)
        elif isinstance(page, DirectoryBrowserPage):
            menu.addAction(self._new_folder_action)
            menu.addAction(self._add_files_action)
        menu.addSeparator()
        menu.addAction(self._search_action)
        menu.exec(page.table.viewport().mapToGlobal(position))

    @staticmethod
    def _entry_is_browsable(entry: MixEntry | DirectoryEntry) -> bool:
        if isinstance(entry, DirectoryEntry):
            return entry.is_directory or entry.path.suffix.casefold() == ".mix" or entry.file_type.casefold() == "mix"
        return (
            Path(entry.name or "").suffix.casefold() == ".mix"
            or (entry.file_type or "").casefold() == "mix"
        )

    def _open_selected_entry(self, page, index: QModelIndex) -> None:
        if isinstance(page, MixArchivePage):
            self._open_entry(page, index)
        elif isinstance(page, DirectoryBrowserPage):
            self._open_directory_entry(page, index)

    def _browse_selected_entry(self, page, index: QModelIndex) -> None:
        if isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
            self._open_selected_entry(page, index)

    def _open_selected_with_system_default(self, page, index: QModelIndex) -> None:
        if isinstance(page, MixArchivePage):
            model = page.entry_table.source_model
            entry = model.entry_at(index.row()) if isinstance(model, MixEntryTableModel) else None
            if entry is not None:
                self._open_entry_with_default_application(page.archive, entry, page.path_key)
        elif isinstance(page, DirectoryBrowserPage):
            model = page.entry_table.source_model
            entry = model.entry_at(index.row()) if isinstance(model, DirectoryEntryTableModel) else None
            if entry is not None:
                self._open_with_default_application(entry.path)

    def _choose_files_to_add(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            self.tr("Add Files"),
            str(Path.home()),
            self.tr("All files (*)"),
        )
        if paths:
            self._show_drop_action_dialog(tuple(Path(path) for path in paths))

    # @arch mix-browser.create-file-entry handler | en: Creates an empty file or MIX archive at the active location | zh: 在当前位置创建空文件或 MIX 归档
    def _create_file_entry(self) -> None:
        page = self.tabs.currentWidget()
        if not isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
            return

        dialog = NewFileDialog(
            lambda name, create_mix: self._new_file_name_state(
                page,
                name,
                create_mix,
            ),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        raw_name = dialog.name_edit.text()
        if not raw_name.strip():
            QMessageBox.warning(self, self.tr("Invalid File Name"), self.tr("Enter a file name."))
            return

        if dialog.create_mix_checkbox.isChecked():
            name = raw_name.strip()
            if Path(name).suffix.casefold() != ".mix":
                name += ".mix"
            if name in {".", ".."} or Path(name).name != name:
                QMessageBox.warning(
                    self,
                    self.tr("Invalid MIX File Name"),
                    self.tr("Enter a file name without a folder path."),
                )
                return
            self._create_mix_archive_here(
                page,
                name,
                overwrite_confirmed=dialog.overwrite_confirmed,
            )
            return

        if isinstance(page, MixArchivePage):
            self._create_mix_file_entry(
                page,
                raw_name.strip(),
                overwrite_confirmed=dialog.overwrite_confirmed,
            )
            return
        try:
            result = self._browser_application.create_file(
                page.directory,
                raw_name,
                overwrite=dialog.overwrite_confirmed,
            )
        except ApplicationApiError as exc:
            QMessageBox.warning(self, self.tr("Unable to Create File"), exc.message)
            return
        self._close_pages_for_filesystem_paths((page.directory / raw_name,))
        self._refresh_directory_page(page)
        self.statusBar().showMessage(self.tr('Created {0}').format(result['created_path']), 5000)

    def _new_file_name_state(
        self,
        page: MixArchivePage | DirectoryBrowserPage,
        raw_name: str,
        create_mix_archive: bool,
    ) -> str:
        if not raw_name:
            return "empty"
        if isinstance(page, MixArchivePage) or create_mix_archive:
            name = raw_name.strip()
            if create_mix_archive and Path(name).suffix.casefold() != ".mix":
                name += ".mix"
            if isinstance(page, MixArchivePage):
                return self._mix_entry_name_state(page, name)
            return self._filesystem_name_state(page.directory, name)
        return self._filesystem_name_state(page.directory, raw_name)

    def _filesystem_name_state(
        self,
        directory: Path,
        name: str,
        *,
        current_path: Path | None = None,
    ) -> str:
        if not name:
            return "empty"
        if not is_valid_leaf_name(name):
            return "invalid"
        candidate = directory / name
        if current_path is not None:
            try:
                candidate_key = os.path.normcase(str(candidate.resolve(strict=False)))
                current_key = os.path.normcase(str(current_path.resolve(strict=False)))
            except (OSError, RuntimeError):
                candidate_key = os.path.normcase(os.path.abspath(candidate))
                current_key = os.path.normcase(os.path.abspath(current_path))
            if candidate_key == current_key:
                return "available"
        return "conflict" if os.path.lexists(candidate) else "available"

    def _mix_entry_name_state(
        self,
        page: MixArchivePage,
        name: str,
        *,
        excluded_entry_id: int | None = None,
    ) -> str:
        if not name:
            return "empty"
        if (
            not is_readable_mix_name(name)
            or Path(name).name != name
            or "/" in name
            or "\\" in name
        ):
            return "invalid"
        try:
            candidate_id = mix_file_ids_for_archive(page.archive, (name,))[0]
            reserved_id = mix_file_ids_for_archive(
                page.archive,
                (LOCAL_MIX_DATABASE_NAME,),
            )[0]
        except (MixFormatError, OSError, ValueError):
            return "invalid"
        if candidate_id == reserved_id:
            return "invalid"
        if any(
            entry.file_id == candidate_id and entry.file_id != excluded_entry_id
            for entry in page.archive.entries
        ):
            return "conflict"
        return "available"

    # @arch mix-browser.create-mix-file-entry handler | en: Creates an empty file entry in the active MIX archive | zh: 在当前 MIX 归档中创建空文件条目
    def _create_mix_file_entry(
        self,
        page: MixArchivePage,
        name: str,
        *,
        overwrite_confirmed: bool = False,
    ) -> None:
        name = name.strip()
        if not name:
            QMessageBox.warning(self, self.tr("Invalid MIX File Name"), self.tr("Enter a file name."))
            return
        if not is_readable_mix_name(name) or Path(name).name != name:
            QMessageBox.warning(self, self.tr("Invalid MIX File Name"), self.tr("The name cannot be stored in a MIX archive."))
            return
        overwrite = self._confirm_mix_entry_replacement(
            page,
            name,
            overwrite_confirmed=overwrite_confirmed,
        )
        if overwrite is None:
            return
        operation_root = self._temporary_root / f"new-entry-{uuid4().hex}"
        try:
            operation_root.mkdir(parents=True, exist_ok=False)
            source = operation_root / name
            source.touch(exist_ok=False)
        except OSError as exc:
            shutil.rmtree(operation_root, ignore_errors=True)
            QMessageBox.warning(self, self.tr("Unable to Create MIX File"), str(exc))
            return
        self._begin_add_files(
            page,
            (source,),
            approved_overwrites=frozenset(),
            overwrite=overwrite,
            cleanup_root=operation_root,
        )

    # @arch mix-browser.create-mix-archive-here handler | en: Creates a MIX archive in the active directory or inside the active MIX archive | zh: 在当前目录或当前 MIX 归档中创建 MIX 归档
    def _create_mix_archive_here(
        self,
        page: MixArchivePage | DirectoryBrowserPage,
        name: str,
        *,
        overwrite_confirmed: bool = False,
    ) -> None:
        if isinstance(page, DirectoryBrowserPage):
            try:
                result = self._archive_application.create_empty_mix(
                    page.directory / name,
                    overwrite=overwrite_confirmed,
                )
            except ApplicationApiError as exc:
                QMessageBox.warning(self, self.tr("Unable to Create MIX"), exc.message)
                return
            self._close_pages_for_filesystem_paths((Path(str(result["archive_path"])),))
            self._refresh_directory_page(page)
            self.statusBar().showMessage(self.tr('Created MIX archive {0}').format(result['archive_path']), 5000)
            return

        if not is_readable_mix_name(name):
            QMessageBox.warning(self, self.tr("Invalid MIX File Name"), self.tr("The name cannot be stored in a MIX archive."))
            return
        overwrite = self._confirm_mix_entry_replacement(
            page,
            name,
            overwrite_confirmed=overwrite_confirmed,
        )
        if overwrite is None:
            return
        operation_root = self._temporary_root / f"new-mix-{uuid4().hex}"
        try:
            operation_root.mkdir(parents=True, exist_ok=False)
            source = operation_root / name
            self._archive_application.create_empty_mix(source)
        except (ApplicationApiError, OSError) as exc:
            shutil.rmtree(operation_root, ignore_errors=True)
            QMessageBox.warning(self, self.tr("Unable to Create MIX"), str(exc))
            return
        self._begin_add_files(
            page,
            (source,),
            approved_overwrites=frozenset(),
            overwrite=overwrite,
            cleanup_root=operation_root,
        )

    def _confirm_mix_entry_replacement(
        self,
        page: MixArchivePage,
        name: str,
        *,
        overwrite_confirmed: bool = False,
    ) -> bool | None:
        if name.casefold() == LOCAL_MIX_DATABASE_NAME.casefold():
            QMessageBox.warning(
                self,
                self.tr("Reserved MIX Entry Name"),
                self.tr('{0} is reserved for embedded MIX name data.').format(LOCAL_MIX_DATABASE_NAME),
            )
            return None
        try:
            target_id = mix_file_ids_for_archive(page.archive, (name,))[0]
            reserved_id = mix_file_ids_for_archive(
                page.archive,
                (LOCAL_MIX_DATABASE_NAME,),
            )[0]
        except (MixFormatError, OSError, ValueError) as exc:
            QMessageBox.warning(self, self.tr("Unable to Check MIX Entry"), str(exc))
            return None
        if target_id == reserved_id:
            QMessageBox.warning(
                self,
                self.tr("Reserved MIX Entry Name"),
                self.tr('{0} resolves to the reserved {1} entry.').format(name, LOCAL_MIX_DATABASE_NAME),
            )
            return None
        existing = next((entry for entry in page.archive.entries if entry.file_id == target_id), None)
        if existing is None:
            return False
        existing_name = existing.name or f"Unknown (0x{existing.file_id:08X})"
        if overwrite_confirmed:
            return True
        choice = QMessageBox.question(
            self,
            self.tr("Replace MIX Entry?"),
            self.tr('{0} resolves to the existing entry {1}. Replace its contents?').format(name, existing_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return choice == QMessageBox.StandardButton.Yes

    # @arch mix-browser.create-directory-entry handler | en: Creates a child folder in the active filesystem directory | zh: 在当前文件系统目录中创建子目录
    def _create_directory_entry(self) -> None:
        page = self.tabs.currentWidget()
        if not isinstance(page, DirectoryBrowserPage):
            return
        dialog = NameEntryDialog(
            self.tr("New Folder"),
            self.tr("Folder name:"),
            "",
            lambda name: self._filesystem_name_state(
                page.directory,
                name.strip(),
            ),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name_edit.text()
        try:
            result = self._browser_application.create_directory(
                page.directory,
                name.strip(),
                overwrite=dialog.overwrite_confirmed,
            )
        except ApplicationApiError as exc:
            QMessageBox.warning(self, self.tr("Unable to Create Folder"), exc.message)
            return
        self._close_pages_for_filesystem_paths((Path(str(result["created_path"])),))
        self._refresh_directory_page(page)
        self.statusBar().showMessage(self.tr('Created {0}').format(result['created_path']), 5000)

    # @arch mix-browser.copy-browser-items handler | en: Copies selected browser items or recursive search results to the system clipboard | zh: 将选中的浏览对象或递归搜索结果复制到系统剪贴板
    def _copy_selected_entries(self) -> None:
        search_dialog = self._focused_search_dialog() or self._search_copy_context
        if search_dialog in self._search_dialogs:
            self._copy_search_hits(search_dialog.selected_hits())
            return
        page = self.tabs.currentWidget()
        if isinstance(page, MixArchivePage):
            self._copy_mix_entries(page)
        elif isinstance(page, DirectoryBrowserPage):
            entries = self._selected_directory_entries(page)
            if not entries:
                return
            self._mix_clipboard = None
            self._cancel_pending_clipboard_export()
            paths = tuple(entry.path for entry in entries)
            self._set_system_clipboard_paths(paths)
            self._sync_workspace_actions()
            self.statusBar().showMessage(self.tr('Copied {0} filesystem item(s).').format(len(entries)), 5000)

    # @arch mix-browser.paste-browser-items handler | en: Pastes clipboard contents into the active browser location | zh: 将剪贴板内容粘贴到当前浏览位置
    def _paste_selected_entries(self) -> None:
        page = self.tabs.currentWidget()
        clipboard_paths = self._system_clipboard_paths()
        if isinstance(page, MixArchivePage):
            if self._mix_clipboard_matches(clipboard_paths):
                self._paste_mix_entries(page)
            else:
                self._paste_files_to_mix(page, clipboard_paths)
        elif isinstance(page, DirectoryBrowserPage):
            self._paste_directory_entries(page, clipboard_paths)

    def _set_system_clipboard_paths(
        self,
        paths: tuple[Path, ...],
        *,
        mix_clipboard: _MixClipboard | None = None,
        export_root: Path | None = None,
    ) -> None:
        previous_root = self._clipboard_export_root
        referenced_root = export_root or self._root_for_clipboard_paths(paths)
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        self._mix_clipboard = mix_clipboard
        self._clipboard_export_root = referenced_root
        QGuiApplication.clipboard().setMimeData(mime_data)
        if previous_root is not None and previous_root != referenced_root:
            self._schedule_clipboard_export_cleanup(previous_root)

    def _copy_mix_entries(self, page: MixArchivePage) -> None:
        entries = self._selected_mix_entries(page)
        if not entries:
            return
        self._cancel_pending_clipboard_export()
        token = uuid4().hex
        cancellation = Event()
        export_root = self._clipboard_export_base / f"copy-{token}"
        try:
            self._clipboard_export_base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.statusBar().showMessage(self.tr('Could not prepare the system clipboard: {0}').format(exc), 8000)
            return
        self._pending_clipboard_export_token = token
        self._pending_clipboard_export_cancellation = cancellation
        self._pending_mix_clipboard = _MixClipboard(
            page.archive.path,
            tuple(parent.entry_id for parent in page.archive.parents),
            tuple(entry.file_id for entry in entries),
            (),
        )
        self.statusBar().showMessage(self.tr("Preparing MIX entries for the system clipboard..."))
        future = self._task_executor.submit(
            extract_entries_for_drag,
            page.archive,
            entries,
            export_root,
            cancellation_requested=cancellation.is_set,
        )
        future.add_done_callback(
            lambda completed, pending_token=token, root=export_root: self._forward_clipboard_export(
                pending_token,
                root,
                completed,
            )
        )

    def _forward_clipboard_export(self, token: str, export_root: Path, future: Future) -> None:
        try:
            paths = future.result()
        except Exception as exc:
            paths = ()
            error = str(exc)
        else:
            error = ""
        try:
            self._clipboard_export_signals.completed.emit(token, export_root, paths, error)
        except RuntimeError:
            shutil.rmtree(export_root, ignore_errors=True)

    @Slot(str, object, object, str)
    def _on_clipboard_export_completed(
        self,
        token: str,
        export_root_value: object,
        paths_value: object,
        error: str,
    ) -> None:
        export_root = Path(export_root_value)
        if token != self._pending_clipboard_export_token:
            shutil.rmtree(export_root, ignore_errors=True)
            return
        pending = self._pending_mix_clipboard
        self._pending_clipboard_export_token = None
        self._pending_clipboard_export_cancellation = None
        self._pending_mix_clipboard = None
        paths = paths_value if isinstance(paths_value, tuple) else ()
        if error or not paths:
            shutil.rmtree(export_root, ignore_errors=True)
            message = error or self.tr("No files were exported.")
            source_label = self.tr("MIX entries") if pending is not None else self.tr("search results")
            self.statusBar().showMessage(
                self.tr('Could not copy {0}: {1}').format(source_label, message),
                8000,
            )
            return
        clipboard = (
            _MixClipboard(
                pending.archive_path,
                pending.parent_entry_ids,
                pending.entry_ids,
                paths,
            )
            if pending is not None
            else None
        )
        self._set_system_clipboard_paths(paths, mix_clipboard=clipboard, export_root=export_root)
        if pending is not None:
            self.statusBar().showMessage(
                self.tr("Copied {0} MIX items.").format(len(paths)),
                5000,
            )
        else:
            self.statusBar().showMessage(self.tr('Copied {0} item(s).').format(len(paths)), 5000)
        self._sync_workspace_actions()

    def _paste_directory_entries(
        self,
        page: DirectoryBrowserPage,
        clipboard_paths: tuple[Path, ...],
    ) -> None:
        destination = page.directory.resolve()
        source_paths = tuple(
            path for path in clipboard_paths if path.exists() or path.is_symlink()
        )
        if not source_paths:
            self.statusBar().showMessage(self.tr("The copied items are no longer available."), 6000)
            return
        if len({path.name.casefold() for path in source_paths}) != len(source_paths):
            QMessageBox.warning(
                self,
                self.tr("Unable to Paste Items"),
                self.tr("The clipboard contains items with duplicate names."),
            )
            return
        if all(path.parent.resolve() == destination for path in source_paths):
            self.statusBar().showMessage(self.tr("The selected items are already in this folder."), 5000)
            return

        conflicts = []
        for path in source_paths:
            target = destination / path.name
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(target)):
                continue
            if not target.exists() and not target.is_symlink():
                continue
            if path.is_dir() != target.is_dir():
                QMessageBox.warning(
                    self,
                    self.tr("Unable to Paste Items"),
                    self.tr('An item of a different type already uses the name {0}.').format(path.name),
                )
                return
            conflicts.append(path.name)
        overwrite = False
        if conflicts:
            shown = "\n".join(conflicts[:8])
            if len(conflicts) > 8:
                shown += f"\n... and {len(conflicts) - 8} more"
            choice = QMessageBox.question(
                self,
                self.tr("Replace Existing Items?"),
                self.tr('Replace {0} existing item(s) in {1}?\n\n{2}').format(len(conflicts), destination, shown),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        self._begin_directory_operation(
            page,
            source_paths,
            operation="transfer",
            overwrite=overwrite,
        )

    def _paste_files_to_mix(
        self,
        page: MixArchivePage,
        clipboard_paths: tuple[Path, ...],
    ) -> None:
        if not clipboard_paths:
            self.statusBar().showMessage(self.tr("The system clipboard does not contain local files."), 6000)
            return
        if any(not path.is_file() for path in clipboard_paths):
            QMessageBox.warning(self, self.tr("Unable to Paste Items"), self.tr("Folders cannot be added to a MIX archive."))
            return
        try:
            target_archive_path = page.archive.path.resolve()
            if any(path.resolve() == target_archive_path for path in clipboard_paths):
                QMessageBox.warning(
                    self,
                    self.tr("Unable to Paste Items"),
                    self.tr("The active MIX archive cannot be added to itself."),
                )
                return
        except OSError as exc:
            QMessageBox.warning(self, self.tr("Unable to Paste Items"), str(exc))
            return
        names = tuple(path.name for path in clipboard_paths)
        if len({name.casefold() for name in names}) != len(names):
            QMessageBox.warning(
                self,
                self.tr("Unable to Paste Items"),
                self.tr("The clipboard contains files with duplicate names."),
            )
            return
        invalid_name = next(
            (
                name
                for name in names
                if not is_readable_mix_name(name)
                or name.casefold() == LOCAL_MIX_DATABASE_NAME.casefold()
            ),
            None,
        )
        if invalid_name is not None:
            QMessageBox.warning(
                self,
                self.tr("Unable to Paste Items"),
                self.tr('{0} cannot be stored as a MIX entry name.').format(invalid_name),
            )
            return
        try:
            file_ids = mix_file_ids_for_archive(page.archive, names)
        except (OSError, MixFormatError) as exc:
            QMessageBox.warning(self, self.tr("Unable to Paste Items"), str(exc))
            return
        conflicts = []
        for name, file_id in zip(names, file_ids, strict=True):
            existing = next((entry for entry in page.archive.entries if entry.file_id == file_id), None)
            if existing is not None:
                conflicts.append(f"{name} -> {existing.name or f'Unknown (0x{file_id:08X})'}")
        overwrite = False
        if conflicts:
            shown = "\n".join(conflicts[:8])
            if len(conflicts) > 8:
                shown += f"\n... and {len(conflicts) - 8} more"
            choice = QMessageBox.question(
                self,
                self.tr("Replace Existing MIX Entries?"),
                self.tr('Replace {0} existing item(s) in {1}?\n\n{2}').format(len(conflicts), page.location_text, shown),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
            overwrite = True
        self._begin_add_files(
            page,
            clipboard_paths,
            approved_overwrites=frozenset(),
            overwrite=overwrite,
        )

    # @arch mix-browser.begin-directory-operation handler | en: Runs filesystem copies and deletion on the shared task executor | zh: 使用共享任务执行器处理文件系统复制与删除
    def _begin_directory_operation(
        self,
        page: DirectoryBrowserPage,
        paths: tuple[Path, ...],
        *,
        operation: str,
        overwrite: bool = False,
    ) -> None:
        description = self.tr("Copying") if operation == "transfer" else self.tr("Deleting")
        display_name = f"{len(paths)} item(s)"
        task_id, task = self._start_progress_task(
            "directory",
            display_name,
            self.tr('{0} {1} filesystem item(s)...').format(description, len(paths)),
        )
        affected_keys = {str(page.directory.resolve()).casefold()}
        affected_keys.update(str(path.parent.resolve()).casefold() for path in paths)
        task.directory_keys = tuple(affected_keys)
        task.directory_operation = operation
        progress = lambda completed, total: self._external_open_signals.progress.emit(
            task_id,
            completed,
            total,
        )
        if operation == "transfer":
            task.future = self._task_executor.submit(
                self._browser_application.transfer_directory_entries,
                page.directory,
                paths,
                overwrite=overwrite,
                progress=progress,
                cancellation_requested=task.cancellation.is_cancelled,
            )
        else:
            task.future = self._task_executor.submit(
                self._browser_application.delete_directory_entries,
                paths,
                progress=progress,
                cancellation_requested=task.cancellation.is_cancelled,
            )
        task.future.add_done_callback(
            lambda completed, pending_id=task_id: self._forward_progress_task(pending_id, completed)
        )

    # @arch mix-browser.rename-browser-item handler | en: Renames a selected filesystem item or MIX entry | zh: 重命名选中的文件系统对象或 MIX 条目
    def _rename_selected_entry(self) -> None:
        page = self.tabs.currentWidget()
        if isinstance(page, MixArchivePage):
            self._rename_mix_entry()
            return
        if not isinstance(page, DirectoryBrowserPage):
            return
        entries = self._selected_directory_entries(page)
        if len(entries) != 1:
            return
        source = entries[0].path
        dialog = NameEntryDialog(
            self.tr("Rename Item"),
            self.tr("New name:"),
            source.name,
            lambda name: self._filesystem_name_state(
                source.parent,
                name,
                current_path=source,
            ),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name_edit.text()
        if name == source.name:
            return
        try:
            result = self._browser_application.rename_directory_entry(
                source,
                name,
                overwrite=dialog.overwrite_confirmed,
            )
        except ApplicationApiError as exc:
            QMessageBox.warning(self, self.tr("Unable to Rename Item"), exc.message)
            return
        self._close_pages_for_filesystem_paths((source, source.with_name(name)))
        self._refresh_directory_page(page)
        self.statusBar().showMessage(self.tr('Renamed to {0}').format(result['renamed_path']), 6000)

    # @arch mix-browser.delete-browser-items handler | en: Confirms and deletes selected filesystem items or MIX entries | zh: 确认并删除选中的文件系统对象或 MIX 条目
    def _delete_selected_entries(self) -> None:
        page = self.tabs.currentWidget()
        if isinstance(page, MixArchivePage):
            self._delete_mix_entries()
            return
        if not isinstance(page, DirectoryBrowserPage):
            return
        entries = self._selected_directory_entries(page)
        if not entries:
            return
        names = [entry.path.name for entry in entries]
        shown_names = "\n".join(names[:8])
        if len(names) > 8:
            shown_names += f"\n... and {len(names) - 8} more"
        choice = QMessageBox.question(
            self,
            self.tr("Delete Items?"),
            self.tr('Permanently delete {0} item(s)?\n\n{1}').format(len(entries), shown_names),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        self._begin_directory_operation(
            page,
            tuple(entry.path for entry in entries),
            operation="delete",
        )

    # @arch mix-browser.paste-mix-entries handler | en: Copies entries from the system clipboard's originating MIX archive | zh: 从系统剪贴板对应的源 MIX 归档复制条目
    def _paste_mix_entries(self, page: MixArchivePage) -> None:
        clipboard = self._mix_clipboard
        if clipboard is None:
            return
        target_parent_ids = tuple(parent.entry_id for parent in page.archive.parents)
        same_location = (
            page.archive.path.resolve() == clipboard.archive_path.resolve()
            and target_parent_ids == clipboard.parent_entry_ids
        )
        if same_location:
            self.statusBar().showMessage(self.tr("These entries are already in this MIX archive."), 5000)
            return
        self._begin_archive_edit(
            page.archive.path,
            target_parent_ids,
            page.archive.file_signature,
            page.location_text,
            target_page_key=page.path_key,
            source_archive_path=clipboard.archive_path,
            source_parent_entry_ids=clipboard.parent_entry_ids,
            copy_entry_ids=clipboard.entry_ids,
        )

    def _apply_auto_play_preferences(
        self,
        page: MixArchivePage | DirectoryBrowserPage,
    ) -> None:
        page.preview.set_auto_play_preferences(**self._auto_play_preferences)

    def _create_modified_file_banner(self) -> None:
        self._modified_file_banner = QWidget(self.container)
        layout = QHBoxLayout(self._modified_file_banner)
        layout.setContentsMargins(8, 4, 8, 4)
        self._modified_file_label = QLabel(self._modified_file_banner)
        self._modified_file_label.setWordWrap(True)
        layout.addWidget(self._modified_file_label, 1)
        self._write_back_button = QPushButton(self.tr("Update MIX"), self._modified_file_banner)
        self._write_back_button.clicked.connect(self._write_back_modified_file)
        layout.addWidget(self._write_back_button)
        self._dismiss_modified_file_button = QPushButton(self.tr("Not now"), self._modified_file_banner)
        self._dismiss_modified_file_button.clicked.connect(self._dismiss_modified_file)
        layout.addWidget(self._dismiss_modified_file_button)
        self._modified_file_banner.hide()

    def _create_split_status_bar(self) -> None:
        self._status_left = QLabel(self)
        self._status_left.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        self._status_document = QLabel(self.tr("Select an entry"), self)
        self._status_document.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

        right_status = QWidget(self)
        right_layout = QHBoxLayout(right_status)
        right_layout.setContentsMargins(0, 0, 4, 0)
        right_layout.setSpacing(6)
        divider = QFrame(right_status)
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFrameShadow(QFrame.Shadow.Sunken)
        right_layout.addWidget(divider)
        right_layout.addWidget(self._status_document, 1)

        self._status_encoding_label = QLabel(self.tr("Encoding"), right_status)
        right_layout.addWidget(self._status_encoding_label)
        self._status_encoding = QComboBox(right_status)
        for label, encoding in (
            ("ANSI", "ansi"),
            ("UTF-8", "utf-8"),
            ("UTF-16 LE", "utf-16-le"),
            ("UTF-16 BE", "utf-16-be"),
            ("Windows-1252", "cp1252"),
            ("GBK", "gbk"),
            ("Shift-JIS", "cp932"),
            ("ISO-8859-1", "latin-1"),
        ):
            self._status_encoding.addItem(label, encoding)
        self._status_encoding.setCurrentIndex(0)
        self._status_encoding.setFixedWidth(145)
        self._status_encoding_label.hide()
        self._status_encoding.hide()
        self._status_encoding.currentIndexChanged.connect(self._on_status_encoding_changed)
        right_layout.addWidget(self._status_encoding)

        self._status_splitter = QSplitter(Qt.Orientation.Horizontal, self.statusBar())
        self._status_splitter.setObjectName("SplitArchiveStatusBar")
        self._status_splitter.setHandleWidth(0)
        self._status_splitter.setChildrenCollapsible(False)
        self._status_splitter.addWidget(self._status_left)
        self._status_splitter.addWidget(right_status)
        self._status_splitter.setStretchFactor(0, 3)
        self._status_splitter.setStretchFactor(1, 2)
        self._status_splitter.setSizes([640, 384])
        self.statusBar().addWidget(self._status_splitter, 1)
        self.statusBar().messageChanged.connect(
            lambda *_args: QTimer.singleShot(0, self._sync_status_splitter)
        )

    def _on_status_encoding_changed(self, index: int) -> None:
        page = self.tabs.currentWidget()
        encoding = self._status_encoding.itemData(index)
        if isinstance(page, (MixArchivePage, DirectoryBrowserPage)) and isinstance(encoding, str):
            page.set_preview_encoding(encoding)

    def _choose_archives(self) -> None:
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            self.tr("Open MIX archives"),
            "",
            self.tr("MIX archives (*.mix *.mmx *.yro);;All files (*)"),
        )
        if paths:
            self.open_paths([Path(path) for path in paths])

    # @arch mix-browser.create-mix-handler handler | en: Creates an unsaved runtime MIX archive and opens it in a tab | zh: 创建未保存的运行期 MIX 归档并在标签页中打开
    def _create_mix(self) -> None:
        self._untitled_mix_count += 1
        title = (
            "Untitled MIX *"
            if self._untitled_mix_count == 1
            else f"Untitled MIX ({self._untitled_mix_count}) *"
        )
        runtime_path = self._temporary_root / f"untitled-{uuid4().hex}.mix"
        try:
            result = self._archive_application.create_empty_mix(
                runtime_path,
            )
        except ApplicationApiError as exc:
            QMessageBox.warning(self, self.tr("Unable to create MIX archive"), exc.message)
            return
        created_path = Path(str(result["archive_path"]))
        path_key = str(created_path.resolve()).casefold()
        self._unsaved_mix_roots.add(path_key)
        self._restore_active_path_key = path_key
        self._queue_archive_open(
            created_path,
            discover_names=False,
            display_title=title,
            location_text="Unsaved MIX archive",
        )
        self._sync_workspace_actions()
        self._update_open_status()

    def _unsaved_root_key_for_page(self, page: object) -> str | None:
        if not isinstance(page, MixArchivePage):
            return None
        candidate_keys = (page.path_key, *(key for key, _title in page.ancestors))
        return next(
            (key for key in candidate_keys if key in self._unsaved_mix_roots),
            None,
        )

    # @arch mix-browser.save-runtime-mix handler | en: Saves a newly created runtime MIX archive to a selected path | zh: 将新建的运行期 MIX 归档保存到用户选择的位置
    def _save_mix(self) -> None:
        page = self.tabs.currentWidget()
        root_key = self._unsaved_root_key_for_page(page)
        if root_key is None:
            return
        self._save_mix_to_new_path(root_key, remove_source=True)

    # @arch mix-browser.save-mix-as handler | en: Saves the active MIX archive to a new path and preserves any existing source file | zh: 将当前 MIX 归档保存到新路径，并保留已有源文件
    def _save_mix_as(self) -> None:
        page = self.tabs.currentWidget()
        root_key = self._mix_root_key_for_page(page)
        if root_key is None:
            return
        self._save_mix_to_new_path(
            root_key,
            remove_source=root_key in self._unsaved_mix_roots,
        )

    def _mix_root_key_for_page(self, page: object) -> str | None:
        if not isinstance(page, MixArchivePage):
            return None
        try:
            root_key = str(page.archive.path.resolve()).casefold()
        except OSError:
            return None
        return (
            root_key
            if isinstance(self._pages_by_path.get(root_key), MixArchivePage)
            else None
        )

    def _select_mix_save_destination(
        self,
        default_path: Path,
        source_path: Path,
    ) -> tuple[Path, bool] | None:
        name_dialog = NameEntryDialog(
            self.tr("Save MIX archive"),
            self.tr("MIX archive name:"),
            default_path.name,
            lambda name, directory: self._save_mix_name_state(
                name,
                directory,
                source_path=source_path,
            ),
            self,
            save_path=default_path,
        )
        if name_dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return name_dialog.destination_path, name_dialog.overwrite_confirmed

    @staticmethod
    def _save_mix_name_state(
        name: str,
        directory: Path,
        *,
        source_path: Path | None = None,
    ) -> str:
        if not name:
            return "empty"
        if not is_valid_leaf_name(name):
            return "invalid"
        candidate_name = name if Path(name).suffix else f"{name}.mix"
        candidate = directory / candidate_name
        if source_path is not None:
            try:
                same_source = candidate.resolve(strict=False) == source_path.resolve(strict=False)
            except (OSError, RuntimeError):
                same_source = os.path.normcase(os.path.abspath(candidate)) == os.path.normcase(os.path.abspath(source_path))
            if same_source:
                return "same"
        return "conflict" if os.path.lexists(candidate) else "available"

    def _save_mix_to_new_path(self, root_key: str, *, remove_source: bool) -> None:
        root_page = self._pages_by_path.get(root_key)
        if not isinstance(root_page, MixArchivePage):
            return
        source_path = root_page.archive.path
        nested_prefix = f"{root_key}!"
        busy = any(
            (task.page_key == root_key or (task.page_key or "").startswith(nested_prefix))
            or (
                task.archive is not None
                and task.archive.path.resolve() == source_path.resolve()
            )
            or (
                task.kind == "writeback"
                and (record := self._tracked_external_files.get(task.modified_path or "")) is not None
                and record.archive.path.resolve() == source_path.resolve()
            )
            for task in self._progress_tasks.values()
        ) or any(
            key == root_key or key.startswith(nested_prefix)
            for key in self._pending_paths
        ) or any(
            key == root_key or key.startswith(nested_prefix)
            for key in self._pending_drag_exports
        ) or (
            self._pending_clipboard_export_token is not None
            or root_key in self._saving_mix_roots
        )
        if busy:
            self.statusBar().showMessage(
                self.tr("Wait for active operations on this MIX archive to finish before saving."),
                7000,
            )
            return

        if remove_source:
            save_directory = self._palette_directory
            if save_directory is None or not save_directory.is_dir():
                save_directory = Path.home()
            default_path = save_directory / "Untitled.mix"
        else:
            default_path = source_path
        destination_result = self._select_mix_save_destination(default_path, source_path)
        if destination_result is None:
            return
        destination, overwrite_confirmed = destination_result
        if not destination.suffix:
            destination = destination.with_suffix(".mix")
        try:
            destination = destination.resolve()
            source_path = source_path.resolve()
            temporary_root = self._temporary_root.resolve()
        except OSError as exc:
            QMessageBox.warning(self, self.tr("Unable to save MIX archive"), str(exc))
            return
        if destination == source_path:
            QMessageBox.warning(
                self,
                self.tr("Unable to save MIX archive"),
                self.tr("Choose a different file path for Save As."),
            )
            return
        if destination == temporary_root or temporary_root in destination.parents:
            QMessageBox.warning(
                self,
                self.tr("Unable to save MIX archive"),
                self.tr("Choose a location outside the application's temporary workspace."),
            )
            return
        destination_key = str(destination).casefold()
        if destination_key in self._pending_paths or any(
            isinstance(open_page, MixArchivePage)
            and open_page.archive.path.resolve() == destination
            for open_page in self._pages_by_path.values()
        ):
            QMessageBox.warning(
                self,
                self.tr("Unable to save MIX archive"),
                self.tr("This MIX archive is already open in another tab."),
            )
            return
        try:
            total = source_path.stat().st_size
        except OSError as exc:
            QMessageBox.warning(self, self.tr("Unable to save MIX archive"), str(exc))
            return
        if total <= 0:
            QMessageBox.warning(
                self,
                self.tr("Unable to save MIX archive"),
                self.tr("The MIX archive is empty or unavailable."),
            )
            return

        task_id, task = self._start_progress_task(
            "save",
            root_page.display_title,
            self.tr('Saving {0}...').format(root_page.display_title),
            total=total,
        )
        task.save_root_key = root_key
        task.save_source_path = source_path
        task.save_destination_path = destination
        task.save_remove_source = remove_source
        self._saving_mix_roots.add(root_key)
        progress = lambda completed, expected: self._external_open_signals.progress.emit(
            task_id,
            completed,
            expected,
        )
        task.future = self._task_executor.submit(
            _save_mix_archive_copy,
            source_path,
            destination,
            root_page.archive.file_signature,
            overwrite_confirmed,
            progress,
            task.cancellation.is_cancelled,
        )
        task.future.add_done_callback(
            lambda completed, pending_id=task_id: self._forward_progress_task(pending_id, completed)
        )
        self._sync_workspace_actions()

    # @arch mix-browser.finish-mix-save handler | en: Applies a completed MIX archive save to its open tabs | zh: 将已完成的 MIX 归档保存结果应用到打开的标签页
    def _finish_save_mix_task(
        self,
        task: _ExternalProgressTask,
        result: object,
        error: str,
    ) -> None:
        root_key = task.save_root_key
        if root_key is not None:
            self._saving_mix_roots.discard(root_key)
        if error:
            if error == "cancelled":
                message = self.tr("MIX archive save cancelled.")
            elif error == "source-changed":
                message = self.tr("The MIX archive changed while saving. Try saving again.")
            elif error == "access-denied":
                message = self.tr("Could not save the MIX archive because the destination denied access.")
            elif error == "io-error":
                message = self.tr("Could not save the MIX archive. Check the destination and available disk space.")
            else:
                message = self.tr("Could not save MIX archive: {0}").format(result or error)
            self.statusBar().showMessage(message, 8000)
            self._sync_workspace_actions()
            return
        if (
            root_key is None
            or task.save_source_path is None
            or task.save_destination_path is None
            or not isinstance(result, tuple)
            or len(result) != 2
        ):
            self.statusBar().showMessage(self.tr("The MIX archive save did not return a usable result."), 8000)
            self._sync_workspace_actions()
            return

        signature = (int(result[0]), int(result[1]))
        self._close_pages_for_filesystem_paths((task.save_destination_path,))
        destination_parent = task.save_destination_path.parent.resolve()
        for page in tuple(self._pages_by_path.values()):
            if (
                isinstance(page, DirectoryBrowserPage)
                and page.directory.resolve() == destination_parent
            ):
                self._refresh_directory_page(page)
        try:
            self._rebase_saved_mix_archive(
                root_key,
                task.save_source_path,
                task.save_destination_path,
                signature,
                remove_source=task.save_remove_source,
            )
        except Exception as exc:
            self.statusBar().showMessage(
                self.tr('The MIX archive was copied, but its open tabs could not be switched to the saved path: {0}').format(exc),
                10000,
            )
            self._sync_workspace_actions()
            return
        self.statusBar().showMessage(
            self.tr('Saved MIX archive to {0}.').format(task.save_destination_path),
            8000,
        )

    # @arch mix-browser.rebase-saved-mix service | en: Rebinds open MIX views to the saved path and optionally removes a temporary source | zh: 将打开的 MIX 视图重新绑定到保存路径，并可选删除临时源文件
    def _rebase_saved_mix_archive(
        self,
        root_key: str,
        source_path: Path,
        destination_path: Path,
        signature: tuple[int, int],
        *,
        remove_source: bool,
    ) -> None:
        root_page = self._pages_by_path.get(root_key)
        if not isinstance(root_page, MixArchivePage):
            raise RuntimeError("The MIX archive tab is no longer open.")
        source_path = source_path.resolve()
        destination_path = destination_path.resolve()
        new_root_key = str(destination_path).casefold()
        new_title = destination_path.name
        old_base_location = root_page.location_text
        new_base_location = str(destination_path)
        pages = [
            (key, page)
            for key, page in self._pages_by_path.items()
            if isinstance(page, MixArchivePage)
            and page.archive.path.resolve() == source_path
            and (key == root_key or key.startswith(f"{root_key}!"))
        ]
        if not any(key == root_key for key, _page in pages):
            raise RuntimeError("The MIX archive tab could not be found.")
        key_mapping = {
            key: new_root_key + key[len(root_key):]
            for key, _page in pages
        }

        for old_key, page in pages:
            self._cancel_entry_preview(old_key)
            page.replace_archive(
                replace(page.archive, path=destination_path, file_signature=signature)
            )
        for old_key, _page in pages:
            self._pages_by_path.pop(old_key, None)
        for old_key, page in pages:
            new_key = key_mapping[old_key]
            page.path_key = new_key
            if old_key == root_key:
                page.display_title = new_title
                page.location_text = new_base_location
            elif page.location_text.startswith(old_base_location):
                page.location_text = new_base_location + page.location_text[len(old_base_location):]
            ancestors = tuple(
                (
                    key_mapping.get(ancestor_key, ancestor_key),
                    new_title if ancestor_key == root_key else title,
                )
                for ancestor_key, title in page.ancestors
            )
            page.set_navigation_context(ancestors, page.location_text)
            page.preview_requested.disconnect()
            page.preview_requested.connect(
                lambda entry, path_key=new_key: self._request_entry_preview(path_key, entry)
            )
            self._pages_by_path[new_key] = page
            tab_index = self.tabs.indexOf(page)
            if tab_index >= 0:
                self.tabs.setTabText(tab_index, page.display_title)
                self.tabs.setTabToolTip(tab_index, page.location_text)

        for tracked in self._tracked_external_files.values():
            if tracked.archive.path.resolve() == source_path:
                tracked.archive = replace(
                    tracked.archive,
                    path=destination_path,
                    file_signature=signature,
                )
                tracked.archive_signature = signature
                tracked.page_key = key_mapping.get(tracked.page_key, tracked.page_key)
        for attribute in ("_mix_clipboard", "_pending_mix_clipboard"):
            clipboard = getattr(self, attribute)
            if clipboard is not None and clipboard.archive_path.resolve() == source_path:
                setattr(self, attribute, replace(clipboard, archive_path=destination_path))

        self._unsaved_mix_roots.discard(root_key)
        self._saving_mix_roots.discard(root_key)
        if self._restore_active_path_key in key_mapping:
            self._restore_active_path_key = key_mapping[self._restore_active_path_key]
        if remove_source:
            try:
                source_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._sync_breadcrumb_navigation()
        current_page = self.tabs.currentWidget()
        if isinstance(current_page, MixArchivePage) and current_page.path_key in key_mapping.values():
            self._request_entry_preview(current_page.path_key, current_page.current_entry())
        self._update_window_title()
        self._sync_workspace_actions()

    def _choose_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.tr("Open Folder"))
        if path:
            self._open_directory(Path(path))

    def _open_game_directory(self) -> None:
        directory = self._palette_directory
        if directory is None or not directory.is_dir():
            self._open_preferences("palette")
            directory = self._palette_directory
        if directory is not None and directory.is_dir():
            self._open_directory(directory)

    def _open_recursive_search(self) -> None:
        page = self.tabs.currentWidget()
        if not isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
            return
        developer_tools = self._developer_tools_enabled
        while page.ancestors:
            root_page = self._pages_by_path.get(page.ancestors[0][0])
            if not isinstance(root_page, (MixArchivePage, DirectoryBrowserPage)):
                break
            page = root_page

        if isinstance(page, DirectoryBrowserPage):
            root = SearchRoot(
                directory=DirectoryPageLocation(
                    page.directory,
                    page.path_key,
                    page.display_title,
                    page.ancestors,
                )
            )
        else:
            root = SearchRoot(
                archive=ArchivePageLocation(
                    page.archive,
                    page.path_key,
                    page.display_title,
                    page.location_text,
                    page.ancestors,
                )
            )

        dialog = SearchResultsDialog(
            root.label,
            self,
            developer_tools_enabled=developer_tools,
            copy_action=self._copy_action,
        )
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._search_dialogs.add(dialog)
        dialog.table.selectionModel().selectionChanged.connect(
            self._sync_workspace_actions
        )
        dialog.destroyed.connect(
            lambda _object=None, search_dialog=dialog: self._on_search_dialog_destroyed(
                search_dialog
            )
        )
        dialog.result_selected.connect(self._navigate_to_search_hit)
        dialog.result_open_requested.connect(self._open_search_hit)
        dialog.copy_context_changed.connect(self._set_search_copy_context)
        dialog.result_drag_requested.connect(
            lambda hits, search_dialog=dialog: self._start_search_results_drag(
                search_dialog,
                hits,
            )
        )
        dialog.drag_cancelled.connect(
            lambda search_dialog=dialog: self._cancel_search_results_drag(
                search_dialog
            )
        )
        dialog.search_requested.connect(
            lambda query, regex, fallback_only, search_dialog=dialog, search_root=root: self._start_recursive_search(
                search_dialog,
                search_root,
                query,
                regex,
                fallback_only,
            )
        )
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _start_recursive_search(
        self,
        dialog: SearchResultsDialog,
        root: SearchRoot,
        query: str,
        regular_expression: bool,
        fallback_palette_only: bool,
    ) -> None:
        cancellation = TaskCancellationToken()
        progress = TaskProgressDialog(
            self._progress_controller,
            self.tr("Searching"),
            (
                self.tr('Finding assets using the fallback grayscale palette from {0}...').format(root.label)
                if fallback_palette_only
                else self.tr('Searching recursively from {0}...').format(root.label)
            ),
            mode=ProgressMode.INDETERMINATE,
            cancel_callback=cancellation.cancel,
            parent=dialog,
        )
        progress.open()
        future = self._task_executor.submit(
            search_from_root,
            root,
            query,
            regular_expression=regular_expression,
            archive_loader=self._archive_loader,
            cancellation_requested=cancellation.is_cancelled,
            classify_fallback_palettes=dialog.developer_tools_enabled,
            fallback_palette_only=fallback_palette_only,
            palette_directory=self._palette_directory,
            palette_theater=self._palette_theater,
            palette_library=self._palette_library_rules,
        )
        future.add_done_callback(
            lambda completed, search_dialog=dialog, task_dialog=progress: self._forward_recursive_search(
                search_dialog,
                task_dialog,
                completed,
            )
        )

    def _forward_recursive_search(
        self,
        dialog: SearchResultsDialog,
        progress: TaskProgressDialog,
        future: Future[SearchOutcome],
    ) -> None:
        try:
            outcome = future.result()
        except CancelledError:
            outcome = SearchOutcome((), cancelled=True)
            error = ""
        except Exception as exc:
            outcome = None
            error = str(exc)
        else:
            error = ""
        try:
            self._search_signals.completed.emit(dialog, progress, outcome, error)
        except RuntimeError:
            return

    @Slot(object, object, object, str)
    def _on_recursive_search_completed(
        self,
        dialog: object,
        progress: object,
        outcome: object,
        error: str,
    ) -> None:
        if isinstance(progress, TaskProgressDialog):
            progress.finish()
        if not isinstance(dialog, SearchResultsDialog):
            return
        if error or not isinstance(outcome, SearchOutcome):
            dialog.show_search_error(error or "The search could not be completed.")
            return
        dialog.show_outcome(outcome)

    def _navigate_to_search_hit(self, hit: SearchHit) -> None:
        self._show_search_hit(hit)

    def _open_search_hit(self, hit: SearchHit) -> None:
        self._show_search_hit(hit, open_result=True)

    def _on_search_dialog_destroyed(self, dialog: SearchResultsDialog) -> None:
        self._search_dialogs.discard(dialog)
        if self._search_copy_context is dialog:
            self._search_copy_context = None
        self._cancel_search_results_drag(dialog)
        self._sync_workspace_actions()

    def _focused_search_dialog(self) -> SearchResultsDialog | None:
        focus_widget = QApplication.focusWidget()
        if focus_widget is None:
            return None
        for dialog in tuple(self._search_dialogs):
            try:
                if focus_widget is dialog.table or dialog.table.isAncestorOf(focus_widget):
                    return dialog
            except RuntimeError:
                continue
        return None

    # @arch mix-browser.search-copy-context handler | en: Enables browser copy for the focused recursive search result table | zh: 为获得焦点的递归搜索结果表启用复制
    def _set_search_copy_context(self, dialog_value: object) -> None:
        if (
            isinstance(dialog_value, SearchResultsDialog)
            and dialog_value in self._search_dialogs
        ):
            self._search_copy_context = dialog_value
        elif dialog_value is None:
            self._search_copy_context = self._focused_search_dialog()
        else:
            self._search_copy_context = None
        self._sync_workspace_actions()

    # @arch mix-browser.drag-search-results handler | en: Starts copy-only drags from selected recursive search results | zh: 从选中的递归搜索结果启动仅复制拖拽
    def _start_search_results_drag(
        self,
        dialog: SearchResultsDialog,
        hits_value: object,
    ) -> None:
        hits = tuple(hit for hit in hits_value if isinstance(hit, SearchHit))
        if not hits:
            dialog.cancel_pending_drag()
            return
        if all(hit.physical_path is not None for hit in hits):
            paths = tuple(
                hit.physical_path for hit in hits if hit.physical_path is not None
            )
            if any(not path.exists() and not path.is_symlink() for path in paths):
                dialog.cancel_pending_drag()
                self.statusBar().showMessage(
                    self.tr("Some search results are no longer available."),
                    6000,
                )
                return
            dialog.start_drag(paths)
            return

        self._cancel_search_results_drag(dialog)
        temporary_root = self._temporary_root / f"drag-{uuid4().hex}"
        cancellation = Event()
        self._pending_search_drag_exports[dialog] = _PendingDragExport(
            temporary_root,
            cancellation,
        )
        self.statusBar().showMessage(self.tr("Preparing search results for drag..."))
        future = self._task_executor.submit(
            prepare_search_hit_targets,
            hits,
            temporary_root,
            cancellation_requested=cancellation.is_set,
        )
        future.add_done_callback(
            lambda completed, search_dialog=dialog, root=temporary_root: self._forward_search_drag_export(
                search_dialog,
                root,
                completed,
            )
        )

    def _cancel_search_results_drag(self, dialog: SearchResultsDialog) -> None:
        pending = self._pending_search_drag_exports.pop(dialog, None)
        if pending is not None:
            pending.cancellation.set()

    def _forward_search_drag_export(
        self,
        dialog: SearchResultsDialog,
        temporary_root: Path,
        future: Future,
    ) -> None:
        try:
            paths = future.result()
        except InterruptedError:
            paths = ()
            error = "cancelled"
        except Exception as exc:
            paths = ()
            error = str(exc)
        else:
            error = ""
        try:
            self._search_drag_signals.completed.emit(
                dialog,
                temporary_root,
                paths,
                error,
            )
        except RuntimeError:
            shutil.rmtree(temporary_root, ignore_errors=True)

    @Slot(object, object, object, str)
    def _on_search_drag_export_completed(
        self,
        dialog_value: object,
        temporary_root_value: object,
        paths_value: object,
        error: str,
    ) -> None:
        temporary_root = Path(temporary_root_value)
        if not isinstance(dialog_value, SearchResultsDialog):
            shutil.rmtree(temporary_root, ignore_errors=True)
            return
        dialog = dialog_value
        pending = self._pending_search_drag_exports.get(dialog)
        if pending is None or pending.temporary_root != temporary_root:
            shutil.rmtree(temporary_root, ignore_errors=True)
            return
        self._pending_search_drag_exports.pop(dialog, None)
        if self.statusBar().currentMessage() == "Preparing search results for drag...":
            self.statusBar().clearMessage()
        paths = paths_value if isinstance(paths_value, tuple) else ()
        if (
            error
            or pending.cancellation.is_set()
            or dialog not in self._search_dialogs
            or not dialog.drag_pending
            or not paths
        ):
            if dialog in self._search_dialogs:
                dialog.cancel_pending_drag()
            shutil.rmtree(temporary_root, ignore_errors=True)
            if error and error != "cancelled":
                self.statusBar().showMessage(
                    self.tr('Could not prepare search results for drag: {0}').format(error),
                    8000,
                )
            return

        drag_action = dialog.start_drag(paths)
        if drag_action == Qt.DropAction.IgnoreAction:
            shutil.rmtree(temporary_root, ignore_errors=True)

    def _copy_search_hits(self, hits_value: object) -> None:
        hits = tuple(hit for hit in hits_value if isinstance(hit, SearchHit))
        if not hits:
            return
        archive_hits = tuple(hit for hit in hits if hit.physical_path is None)
        if not archive_hits:
            paths = tuple(hit.physical_path for hit in hits if hit.physical_path is not None)
            if any(not path.exists() and not path.is_symlink() for path in paths):
                self.statusBar().showMessage(
                    self.tr("Some search results are no longer available."),
                    6000,
                )
                return
            self._cancel_pending_clipboard_export()
            self._set_system_clipboard_paths(paths)
            self.statusBar().showMessage(self.tr('Copied {0} item(s).').format(len(paths)), 5000)
            self._sync_workspace_actions()
            return

        self._cancel_pending_clipboard_export()
        token = uuid4().hex
        cancellation = Event()
        export_root = self._clipboard_export_base / f"copy-{token}"
        try:
            self._clipboard_export_base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.statusBar().showMessage(
                self.tr('Could not prepare the system clipboard: {0}').format(exc),
                8000,
            )
            return
        self._pending_clipboard_export_token = token
        self._pending_clipboard_export_cancellation = cancellation
        self._pending_mix_clipboard = self._mix_clipboard_for_search_hits(hits)
        self.statusBar().showMessage(self.tr("Preparing search results for the system clipboard..."))
        future = self._task_executor.submit(
            prepare_search_hit_targets,
            hits,
            export_root,
            cancellation_requested=cancellation.is_set,
        )
        future.add_done_callback(
            lambda completed, pending_token=token, root=export_root: self._forward_clipboard_export(
                pending_token,
                root,
                completed,
            )
        )

    @staticmethod
    def _mix_clipboard_for_search_hits(
        hits: tuple[SearchHit, ...],
    ) -> _MixClipboard | None:
        if any(
            hit.physical_path is not None
            or not hit.archive_chain
            or hit.entry_id is None
            for hit in hits
        ):
            return None
        archive = hits[0].archive_chain[-1].archive
        archive_identity = (
            str(archive.path).casefold(),
            archive.source_offset,
            archive.source_size,
        )
        if any(
            (
                str(hit.archive_chain[-1].archive.path).casefold(),
                hit.archive_chain[-1].archive.source_offset,
                hit.archive_chain[-1].archive.source_size,
            )
            != archive_identity
            for hit in hits
        ):
            return None
        return _MixClipboard(
            archive.path,
            tuple(parent.entry_id for parent in archive.parents),
            tuple(hit.entry_id for hit in hits if hit.entry_id is not None),
            (),
        )

    def _show_search_hit(self, hit: SearchHit, *, open_result: bool = False) -> None:
        self._pending_search_selections.clear()
        self._pending_search_opens.clear()
        if hit.physical_path is not None:
            for location in hit.directory_chain:
                self._open_directory(location.path, ancestors=location.ancestors)
            parent = hit.physical_path.parent
            page_key = str(parent.resolve()).casefold()
            page = self._pages_by_path.get(page_key)
            if not isinstance(page, DirectoryBrowserPage):
                return
            self.tabs.setCurrentWidget(page)
            if page_key in self._directory_futures:
                self._pending_search_selections[page_key] = hit.physical_path
                if open_result:
                    self._pending_search_opens[page_key] = hit.physical_path
            elif not self._select_directory_entry(page, hit.physical_path):
                self.statusBar().showMessage(self.tr("The search result is no longer present."), 5000)
            elif open_result:
                self._open_directory_entry(page, page.table.currentIndex())
            return

        for location in hit.directory_chain:
            self._open_directory(location.path, ancestors=location.ancestors)
        for location in hit.archive_chain:
            self._show_archive(
                location.archive,
                path_key=location.key,
                display_title=location.title,
                ancestors=location.ancestors,
                location_text=location.location_text,
            )
        if not hit.archive_chain or hit.entry_id is None:
            return
        target = hit.archive_chain[-1]
        page = self._pages_by_path.get(target.key)
        if not isinstance(page, MixArchivePage):
            return
        model = page.entry_table.source_model
        if not isinstance(model, MixEntryTableModel):
            return
        row = None
        for index in range(model.rowCount()):
            entry = model.entry_at(index)
            if entry is not None and entry.file_id == hit.entry_id:
                row = index
                break
        if row is None:
            self.statusBar().showMessage(self.tr("The search result is no longer present."), 5000)
            return
        self._select_table_row(page.table, row)
        if open_result:
            self._open_entry(page, page.table.currentIndex())

    def _select_directory_entry(self, page: DirectoryBrowserPage, path: Path) -> bool:
        model = page.entry_table.source_model
        if not isinstance(model, DirectoryEntryTableModel):
            return False
        target_key = str(path).casefold()
        row = next(
            (
                index
                for index in range(model.rowCount())
                if (entry := model.entry_at(index)) is not None
                and str(entry.path).casefold() == target_key
            ),
            None,
        )
        if row is None:
            return False
        self._select_table_row(page.table, row)
        return True

    @staticmethod
    def _select_table_row(table, row: int) -> None:
        index = table.model().index(row, 0)
        table.selectionModel().setCurrentIndex(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        table.scrollTo(index)

    @staticmethod
    def _path_is_mix_archive(path: Path) -> bool:
        if path.suffix.casefold() in MIX_CONTAINER_SUFFIXES:
            return True
        try:
            with path.open("rb") as source:
                prefix = source.read(128)
            file_size = path.stat().st_size
        except OSError:
            return False
        return detect_content_type(prefix, file_size) == "MIX"

    # @arch mix-browser.open-paths-from-shell handler | en: Opens filesystem paths as folders, MIX archives, or external files | zh: 将文件系统路径作为目录、MIX 归档或外部文件打开
    def open_paths(self, paths: list[Path]) -> None:
        for path in paths:
            if path.is_dir():
                self._open_directory(path)
                continue
            if not path.is_file():
                continue
            if self._path_is_mix_archive(path):
                self._queue_archive_open(path)
            else:
                self._open_with_default_application(path)
        self._update_open_status()

    def _start_table_drag(self, page: MixArchivePage | DirectoryBrowserPage) -> None:
        if isinstance(page, DirectoryBrowserPage):
            entries = self._selected_directory_entries(page)
            page.entry_table.start_drag(tuple(entry.path for entry in entries))
            return

        entries = self._selected_mix_entries(page)
        if not entries:
            page.entry_table.cancel_pending_drag()
            return
        previous = self._pending_drag_exports.get(page.path_key)
        if previous is not None:
            previous.cancellation.set()
        temporary_root = self._temporary_root / f"drag-{uuid4().hex}"
        cancellation = Event()
        self._pending_drag_exports[page.path_key] = _PendingDragExport(
            temporary_root,
            cancellation,
        )
        self._active_drag_status_root = temporary_root
        self.statusBar().showMessage(self.tr("Preparing MIX entries for drag..."))
        future = self._task_executor.submit(
            extract_entries_for_drag,
            page.archive,
            entries,
            temporary_root,
            cancellation_requested=cancellation.is_set,
        )
        future.add_done_callback(
            lambda completed, page_key=page.path_key, root=temporary_root: self._forward_drag_export(
                page_key,
                root,
                completed,
            )
        )

    def _cancel_table_drag(self, page: MixArchivePage | DirectoryBrowserPage) -> None:
        pending = self._pending_drag_exports.get(page.path_key)
        if pending is not None:
            pending.cancellation.set()
            if self._active_drag_status_root == pending.temporary_root:
                if self.statusBar().currentMessage() == self.tr(
                    "Preparing MIX entries for drag..."
                ):
                    self.statusBar().clearMessage()
                self._active_drag_status_root = None

    def _forward_drag_export(self, page_key: str, temporary_root: Path, future: Future) -> None:
        try:
            paths = future.result()
        except InterruptedError:
            paths = ()
            error = "cancelled"
        except Exception as exc:
            paths = ()
            error = str(exc)
        else:
            error = ""
        try:
            self._drag_export_signals.completed.emit(
                page_key,
                temporary_root,
                paths,
                error,
            )
        except RuntimeError:
            shutil.rmtree(temporary_root, ignore_errors=True)

    @Slot(str, object, object, str)
    def _on_drag_export_completed(
        self,
        page_key: str,
        temporary_root_value: object,
        paths_value: object,
        error: str,
    ) -> None:
        temporary_root = Path(temporary_root_value)
        pending = self._pending_drag_exports.get(page_key)
        if pending is None or pending.temporary_root != temporary_root:
            shutil.rmtree(temporary_root, ignore_errors=True)
            return
        self._pending_drag_exports.pop(page_key, None)
        page = self._pages_by_path.get(page_key)
        paths = paths_value if isinstance(paths_value, tuple) else ()
        owns_status = self._active_drag_status_root == temporary_root
        if owns_status:
            if self.statusBar().currentMessage() == self.tr(
                "Preparing MIX entries for drag..."
            ):
                self.statusBar().clearMessage()
            self._active_drag_status_root = None
        if (
            error
            or pending.cancellation.is_set()
            or not isinstance(page, MixArchivePage)
            or self.tabs.currentWidget() is not page
            or not page.entry_table.drag_pending
        ):
            if isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
                page.entry_table.cancel_pending_drag()
            shutil.rmtree(temporary_root, ignore_errors=True)
            if error and error != "cancelled" and owns_status:
                self.statusBar().showMessage(self.tr('Could not prepare MIX entries for drag: {0}').format(error), 8000)
            return

        drag_action = page.entry_table.start_drag(paths)
        if drag_action == Qt.DropAction.IgnoreAction:
            shutil.rmtree(temporary_root, ignore_errors=True)

    def _show_drop_action_dialog(self, paths: tuple[Path, ...]) -> bool:
        if not paths:
            return False
        page = self.tabs.currentWidget()
        files = tuple(path for path in paths if path.is_file() and not path.is_dir())
        all_files = bool(paths) and len(files) == len(paths)
        duplicate_names = len({path.name.casefold() for path in paths}) != len(paths)
        has_directories = any(path.is_dir() for path in paths)
        requires_open_choice = has_directories or any(
            path.is_file() and self._path_is_mix_archive(path)
            for path in paths
        )
        destination = ""
        overwrite_names: list[str] = []
        disabled_reason = ""
        add_label = self.tr("Add Files")
        add_enabled = all_files and not duplicate_names
        add_mode = "files"

        if duplicate_names:
            add_enabled = False
            disabled_reason = self.tr(
                "The dropped items contain duplicate names, so they cannot be added together."
            )

        if isinstance(page, DirectoryBrowserPage):
            target = page.directory
            destination = str(target)
            add_label = self.tr("Add to Folder")
            if has_directories:
                add_mode = "transfer"
                add_enabled = not duplicate_names
            if not os.access(target, os.W_OK):
                add_enabled = False
                disabled_reason = self.tr("The active folder is not writable.")
            for source in (paths if add_mode == "transfer" else files):
                target_path = target / source.name
                if source.resolve() == target_path.resolve(strict=False):
                    if add_mode == "files":
                        add_enabled = False
                        disabled_reason = self.tr(
                            "A file cannot be added to the folder it already belongs to."
                        )
                    continue
                elif target_path.exists():
                    source_is_directory = source.is_dir()
                    target_is_directory = target_path.is_dir()
                    if source_is_directory != target_is_directory:
                        add_enabled = False
                        disabled_reason = self.tr(
                            "An item of a different type already uses the name {0}."
                        ).format(source.name)
                        continue
                    overwrite_names.append(source.name)
        elif isinstance(page, MixArchivePage):
            target = page.archive.path
            destination = page.location_text
            add_label = self.tr("Add to MIX")
            if not all_files and paths:
                add_enabled = False
                disabled_reason = self.tr("Folders cannot be added to a MIX archive.")
            if not os.access(target, os.W_OK) or not os.access(target.parent, os.W_OK):
                add_enabled = False
                disabled_reason = self.tr("The active MIX archive is not writable.")
            if files:
                try:
                    file_ids = mix_file_ids_for_archive(
                        page.archive,
                        tuple(source.name for source in files),
                    )
                except (OSError, MixFormatError) as exc:
                    add_enabled = False
                    disabled_reason = self.tr(
                        "The active MIX entry table could not be checked: {0}"
                    ).format(exc)
                else:
                    for source, file_id in zip(files, file_ids, strict=True):
                        if source.resolve() == target.resolve():
                            add_enabled = False
                            disabled_reason = self.tr(
                                "The active MIX archive cannot be added to itself."
                            )
                            continue
                        if not is_readable_mix_name(source.name):
                            add_enabled = False
                            disabled_reason = self.tr(
                                "{0} cannot be stored as a MIX entry name."
                            ).format(source.name)
                            continue
                        if source.name.casefold() == LOCAL_MIX_DATABASE_NAME.casefold():
                            add_enabled = False
                            disabled_reason = self.tr(
                                "{0} is reserved for embedded MIX name data."
                            ).format(LOCAL_MIX_DATABASE_NAME)
                            continue
                        existing = next(
                            (entry for entry in page.archive.entries if entry.file_id == file_id),
                            None,
                        )
                        if existing is not None:
                            target_name = existing.name or f"Unknown (0x{file_id:08X})"
                            overwrite_names.append(f"{source.name} -> {target_name}")
        else:
            add_enabled = False
            disabled_reason = self.tr("Open a folder or MIX archive tab before adding files.")

        if not requires_open_choice:
            if not add_enabled or not isinstance(page, (DirectoryBrowserPage, MixArchivePage)):
                QMessageBox.warning(
                    self,
                    self.tr("Unable to Add Items"),
                    disabled_reason or "Open a folder or MIX archive tab before adding files.",
                )
                return False
            if overwrite_names:
                shown = "\n".join(overwrite_names[:8])
                if len(overwrite_names) > 8:
                    shown += f"\n... and {len(overwrite_names) - 8} more"
                choice = QMessageBox.question(
                    self,
                    self.tr("Replace Existing Items?"),
                    self.tr('Replace {0} existing item(s) in {1}?\n\n{2}').format(len(overwrite_names), destination, shown),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if choice != QMessageBox.StandardButton.Yes:
                    return False
            self._begin_add_files(
                page,
                files,
                approved_overwrites=frozenset(overwrite_names),
                overwrite=bool(overwrite_names),
            )
            return True

        if not all_files and not (isinstance(page, DirectoryBrowserPage) and add_mode == "transfer"):
            add_enabled = False
            if isinstance(page, MixArchivePage):
                disabled_reason = self.tr("Folders cannot be added to a MIX archive.")
            else:
                disabled_reason = self.tr(
                    "Adding is available only for files and folders dropped into a folder."
                )
        dialog = DropActionDialog(
            paths,
            destination=destination,
            overwrite_names=tuple(overwrite_names),
            open_enabled=bool(paths),
            add_enabled=add_enabled,
            add_label=add_label,
            add_disabled_reason=disabled_reason,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if dialog.action == "open":
            self.open_paths(list(paths))
            return True
        elif dialog.action == "add" and isinstance(page, (DirectoryBrowserPage, MixArchivePage)):
            if isinstance(page, DirectoryBrowserPage) and add_mode == "transfer":
                self._begin_directory_operation(
                    page,
                    paths,
                    operation="transfer",
                    overwrite=bool(overwrite_names),
                )
            else:
                approved_overwrites = (
                    frozenset(overwrite_names)
                    if isinstance(page, DirectoryBrowserPage)
                    else frozenset()
                )
                self._begin_add_files(
                    page,
                    files,
                    approved_overwrites=approved_overwrites,
                    overwrite=bool(overwrite_names),
                )
            return True
        return False

    def _begin_add_files(
        self,
        page: DirectoryBrowserPage | MixArchivePage,
        paths: tuple[Path, ...],
        *,
        approved_overwrites: frozenset[str],
        overwrite: bool = True,
        cleanup_root: Path | None = None,
    ) -> None:
        task_id, task = self._start_progress_task(
            "add",
            f"{len(paths)} file(s)",
            self.tr('Adding {0} file(s) to {1}...').format(len(paths), page.location_text),
        )
        task.page_key = page.path_key
        task.cleanup_root = cleanup_root
        progress = lambda completed, total: self._external_open_signals.progress.emit(
            task_id,
            completed,
            total,
        )
        if isinstance(page, DirectoryBrowserPage):
            task.future = self._task_executor.submit(
                _add_files_to_directory,
                self._browser_application,
                page.directory,
                paths,
                overwrite,
                approved_overwrites,
                progress,
                task.cancellation.is_cancelled,
            )
        else:
            root_path = page.archive.path
            reload_targets: dict[str, tuple[int, ...]] = {}
            for open_page in self._pages_by_path.values():
                if isinstance(open_page, MixArchivePage) and open_page.archive.path == root_path:
                    reload_targets[f"page:{open_page.path_key}"] = tuple(
                        parent.entry_id for parent in open_page.archive.parents
                    )
            for tracked_path, tracked in self._tracked_external_files.items():
                if tracked.archive.path == root_path:
                    reload_targets[f"file:{tracked_path}"] = tuple(
                        parent.entry_id for parent in tracked.archive.parents
                    )
            task.future = self._task_executor.submit(
                _add_files_to_mix_and_refresh,
                self._archive_application,
                self._archive_loader,
                root_path,
                tuple(parent.entry_id for parent in page.archive.parents),
                paths,
                overwrite,
                page.archive.file_signature,
                tuple(reload_targets.items()),
                progress,
                task.cancellation.is_cancelled,
            )
        task.future.add_done_callback(
            lambda completed, pending_id=task_id: self._forward_progress_task(pending_id, completed)
        )

    # @arch mix-browser.rename-mix-entry handler | en: Renames one MIX entry and recalculates its hash ID | zh: 重命名单个 MIX 条目并重新计算哈希 ID
    def _rename_mix_entry(self) -> None:
        page = self.tabs.currentWidget()
        if not isinstance(page, MixArchivePage):
            return
        entries = self._selected_mix_entries(page)
        if len(entries) != 1:
            return
        entry = entries[0]
        old_name = entry.name or ""
        dialog = NameEntryDialog(
            self.tr("Rename MIX Entry"),
            self.tr("New name:"),
            old_name,
            lambda name: self._mix_entry_name_state(
                page,
                name.strip(),
                excluded_entry_id=entry.file_id,
            ),
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.name_edit.text().strip()
        if name == old_name:
            return
        if (
            not is_readable_mix_name(name)
            or Path(name).name != name
            or name.casefold() == LOCAL_MIX_DATABASE_NAME.casefold()
        ):
            QMessageBox.warning(self, self.tr("Invalid MIX Entry Name"), self.tr("The name cannot be stored in a MIX archive."))
            return
        try:
            new_id = mix_file_ids_for_archive(page.archive, (name,))[0]
        except (MixFormatError, OSError, ValueError) as exc:
            QMessageBox.warning(self, self.tr("Unable to Check MIX Entry"), str(exc))
            return
        collision = next(
            (candidate for candidate in page.archive.entries if candidate.file_id == new_id and candidate.file_id != entry.file_id),
            None,
        )
        if collision is not None:
            existing_name = collision.name or f"Unknown (0x{collision.file_id:08X})"
            if not dialog.overwrite_confirmed:
                choice = QMessageBox.question(
                    self,
                    self.tr("Replace MIX Entry?"),
                    self.tr('{0} resolves to the existing entry {1}. Replace its contents?').format(name, existing_name),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if choice != QMessageBox.StandardButton.Yes:
                    return
        self._begin_archive_edit(
            page.archive.path,
            tuple(parent.entry_id for parent in page.archive.parents),
            page.archive.file_signature,
            page.location_text,
            target_page_key=page.path_key,
            remove_entry_ids=(collision.file_id,) if collision is not None else (),
            rename_entries={entry.file_id: name},
        )

    # @arch mix-browser.delete-mix-entries handler | en: Confirms and deletes selected MIX entries | zh: 确认并删除选中的 MIX 条目
    def _delete_mix_entries(self) -> None:
        page = self.tabs.currentWidget()
        if not isinstance(page, MixArchivePage):
            return
        entries = self._selected_mix_entries(page)
        if not entries:
            return
        names = [entry.name or f"Unknown (0x{entry.file_id:08X})" for entry in entries]
        shown_names = "\n".join(names[:8])
        if len(names) > 8:
            shown_names += f"\n... and {len(names) - 8} more"
        choice = QMessageBox.question(
            self,
            self.tr("Delete MIX Entries?"),
            self.tr('Delete {0} item(s) from {1}?\n\n{2}').format(len(entries), page.location_text, shown_names),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        self._begin_archive_edit(
            page.archive.path,
            tuple(parent.entry_id for parent in page.archive.parents),
            page.archive.file_signature,
            page.location_text,
            target_page_key=page.path_key,
            remove_entry_ids=tuple(entry.file_id for entry in entries),
        )

    # @arch mix-browser.begin-archive-edit handler | en: Starts a cancellable MIX entry edit and refresh operation | zh: 启动可取消的 MIX 条目编辑与刷新任务
    def _begin_archive_edit(
        self,
        archive_path: Path,
        target_parent_entry_ids: tuple[int, ...],
        expected_archive_signature: tuple[int, int] | None,
        display_name: str,
        *,
        target_page_key: str | None = None,
        remove_entry_ids: tuple[int, ...] = (),
        rename_entries: dict[int, str] | None = None,
        source_archive_path: Path | None = None,
        source_parent_entry_ids: tuple[int, ...] = (),
        copy_entry_ids: tuple[int, ...] = (),
    ) -> None:
        task_id, task = self._start_progress_task(
            "edit",
            "MIX entries",
            self.tr('Updating entries in {0}...').format(display_name),
        )
        task.page_key = target_page_key
        task.target_parent_entry_ids = target_parent_entry_ids
        task.affected_entry_ids = tuple(dict.fromkeys((*remove_entry_ids, *((rename_entries or {}).keys()))))
        root_path = archive_path.resolve()
        close_prefixes: list[str] = []
        if target_page_key is not None:
            target_page = self._pages_by_path.get(target_page_key)
            for entry_id in task.affected_entry_ids:
                entry = (
                    next(
                        (candidate for candidate in target_page.archive.entries if candidate.file_id == entry_id),
                        None,
                    )
                    if isinstance(target_page, MixArchivePage)
                    else None
                )
                if entry is not None and (
                    Path(entry.name or "").suffix.casefold() == ".mix"
                    or (entry.file_type or "").casefold() == "mix"
                ):
                    close_prefixes.append(f"{target_page_key}!{entry_id:08x}")
        task.close_page_prefixes = tuple(close_prefixes)
        reload_targets = self._collect_archive_reload_targets(root_path, task.close_page_prefixes)
        progress = lambda completed, total: self._external_open_signals.progress.emit(
            task_id,
            completed,
            total,
        )
        task.future = self._task_executor.submit(
            _edit_mix_entries_and_refresh,
            self._archive_application,
            self._archive_loader,
            root_path,
            target_parent_entry_ids,
            remove_entry_ids,
            rename_entries,
            source_archive_path,
            source_parent_entry_ids,
            copy_entry_ids,
            expected_archive_signature,
            reload_targets,
            progress,
            task.cancellation.is_cancelled,
        )
        task.future.add_done_callback(
            lambda completed, pending_id=task_id: self._forward_progress_task(pending_id, completed)
        )

    def _collect_archive_reload_targets(
        self,
        root_path: Path,
        excluded_page_prefixes: tuple[str, ...] = (),
    ) -> tuple[tuple[str, tuple[int, ...]], ...]:
        targets: dict[str, tuple[int, ...]] = {}
        for open_page in self._pages_by_path.values():
            if not isinstance(open_page, MixArchivePage) or open_page.archive.path != root_path:
                continue
            if any(open_page.path_key.startswith(prefix) for prefix in excluded_page_prefixes):
                continue
            targets[f"page:{open_page.path_key}"] = tuple(
                parent.entry_id for parent in open_page.archive.parents
            )
        for tracked_path, tracked in self._tracked_external_files.items():
            if tracked.archive.path != root_path:
                continue
            if any(tracked.page_key.startswith(prefix) for prefix in excluded_page_prefixes):
                continue
            targets[f"file:{tracked_path}"] = tuple(
                parent.entry_id for parent in tracked.archive.parents
            )
        return tuple(targets.items())

    def _finish_add_files_task(self, task: _ExternalProgressTask, result: object, error: str) -> None:
        if error == "cancelled":
            self.statusBar().showMessage(self.tr("File addition cancelled."), 5000)
            return
        if error:
            detail = str(result) if result else {
                "access-denied": "Check write access to the destination.",
                "unsupported-format": "This MIX format cannot be safely rewritten.",
                "format-limit": "The selected files exceed a MIX format limit.",
                "io-error": "Check available disk space and file access.",
            }.get(error, "The files could not be added.")
            self.statusBar().showMessage(self.tr('Could not add files. {0}').format(detail), 9000)
            return
        if not isinstance(result, _AddedFilesResult):
            self.statusBar().showMessage(self.tr("The file addition did not return a usable result."), 7000)
            return

        page = self._pages_by_path.get(task.page_key or "")
        if result.archive_signature is not None:
            root_path = Path(result.destination)
            refreshed_archives = result.refreshed_archives or {}
            for target_key, archive in refreshed_archives.items():
                if target_key.startswith("page:"):
                    target_page = self._pages_by_path.get(target_key[len("page:"):])
                    if isinstance(target_page, MixArchivePage):
                        target_page.replace_archive(archive)
                elif target_key.startswith("file:"):
                    tracked_path = target_key[len("file:"):]
                    tracked = self._tracked_external_files.get(tracked_path)
                    if tracked is not None:
                        tracked.archive = archive
                        tracked.entry = next(
                            (entry for entry in archive.entries if entry.file_id == tracked.entry.file_id),
                            tracked.entry,
                        )
            for tracked in self._tracked_external_files.values():
                if tracked.archive.path == root_path:
                    tracked.archive_signature = result.archive_signature
        elif isinstance(page, DirectoryBrowserPage):
            self._refresh_directory_page(page)

        replaced = (
            self.tr(" Replaced: {0}.").format(", ".join(result.replaced_names))
            if result.replaced_names
            else ""
        )
        if result.refresh_error:
            self.statusBar().showMessage(
                self.tr("Files were added, but open MIX views could not be refreshed. Reopen the archive to see the changes."),
                10000,
            )
        else:
            target_description = (
                page.location_text
                if isinstance(page, (MixArchivePage, DirectoryBrowserPage))
                else result.destination
            )
            self.statusBar().showMessage(
                self.tr('Added {0} to {1}.{2}').format(', '.join(result.added_names), target_description, replaced),
                9000,
            )

    def _refresh_directory_page(self, page: DirectoryBrowserPage) -> None:
        previous = self._directory_futures.pop(page.path_key, None)
        if previous is not None:
            previous.cancel()
        future = self._task_executor.submit(load_directory_entries, page.directory)
        self._directory_futures[page.path_key] = future
        future.add_done_callback(
            lambda completed, page_key=page.path_key: self._forward_directory_result(page_key, completed)
        )

    def _start_open_progress(
        self,
        key: str,
        title: str,
        message: str,
    ) -> None:
        if key in self._open_progress_tasks:
            return
        self._open_progress_tasks[key] = (None, message)
        if self._open_progress_dialog is None:
            self._open_progress_dialog = TaskProgressDialog(
                self._progress_controller,
                title,
                message,
                mode=ProgressMode.INDETERMINATE,
                cancel_callback=lambda: None,
                cancelable=False,
                parent=self,
            )
            self._open_progress_dialog.show()
        else:
            self._sync_open_progress_message()

    def _bind_open_progress(self, key: str, future: Future) -> None:
        current = self._open_progress_tasks.get(key)
        if current is not None:
            self._open_progress_tasks[key] = (future, current[1])

    def _finish_open_progress(self, key: str, future: Future | None = None) -> None:
        current = self._open_progress_tasks.get(key)
        if current is None or (future is not None and current[0] is not future):
            return
        self._open_progress_tasks.pop(key, None)
        if not self._open_progress_tasks:
            dialog = self._open_progress_dialog
            self._open_progress_dialog = None
            if dialog is not None:
                dialog.finish()
            return
        self._sync_open_progress_message()

    def _sync_open_progress_message(self) -> None:
        dialog = self._open_progress_dialog
        if dialog is None or not self._open_progress_tasks:
            return
        if len(self._open_progress_tasks) == 1:
            message = next(iter(self._open_progress_tasks.values()))[1]
        else:
            message = self.tr("Opening {0} items...").format(len(self._open_progress_tasks))
        dialog.set_message(message)

    def _open_with_default_application(self, path: Path) -> None:
        display_name = path.name or str(path)
        self._next_open_task_id += 1
        task_key = f"default-application:{self._next_open_task_id}"
        self._start_open_progress(
            task_key,
            self.tr("Opening Item"),
            self.tr('Opening {0} with the default application...').format(display_name),
        )

        def finish_open(opened: bool) -> None:
            self._finish_open_progress(task_key)
            if not opened:
                QMessageBox.warning(
                    self,
                    self.tr("Unable to Open Item"),
                    self.tr('No default application could open:\n{0}').format(path),
                )

        def dispatch_open() -> None:
            try:
                opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            except Exception:
                opened = False
            QTimer.singleShot(80, lambda launch_result=opened: finish_open(launch_result))

        QTimer.singleShot(0, dispatch_open)

    def _open_directory(
        self,
        directory: Path,
        *,
        ancestors: tuple[tuple[str, str], ...] = (),
    ) -> None:
        try:
            normalized = directory.expanduser().resolve()
            if not normalized.is_dir():
                return
        except OSError:
            return
        key = str(normalized).casefold()
        existing = self._pages_by_path.get(key)
        if existing is not None:
            if isinstance(existing, DirectoryBrowserPage):
                self._update_page_navigation_context(existing, ancestors)
            self.tabs.setCurrentWidget(existing)
            return
        if key in self._directory_futures:
            return

        title = normalized.name or str(normalized)
        page = DirectoryBrowserPage(
            normalized,
            key,
            title,
            ancestors=ancestors,
            parent=self.tabs,
        )
        self._configure_entry_type_filters(page.entry_table)
        self._apply_auto_play_preferences(page)
        page.preview.auto_play_preference_changed.connect(
            self._set_auto_play_preference
        )
        page.navigate_requested.connect(self._activate_page)
        page.preview_requested.connect(
            lambda entry, page_key=key: self._request_entry_preview(page_key, entry)
        )
        page.preview_state_changed.connect(self._sync_active_status)
        page.filter_state_changed.connect(self._sync_active_status)
        page.context_menu_requested.connect(
            lambda position, target=page: self._show_entry_context_menu(target, position)
        )
        page.drag_requested.connect(lambda target=page: self._start_table_drag(target))
        page.drag_cancelled.connect(lambda target=page: self._cancel_table_drag(target))
        page.table.selectionModel().selectionChanged.connect(self._sync_workspace_actions)
        page.content_splitter.splitterMoved.connect(
            lambda *_args: self._sync_status_splitter()
        )
        self._pages_by_path[key] = page
        index = self.tabs.addTab(
            page,
            system_icon_for_object(is_directory=True),
            title,
        )
        self.tabs.setTabToolTip(index, page.location_text)
        self.tabs.setCurrentIndex(index)
        self._sync_breadcrumb_navigation()
        self._register_drop_targets(page)
        page.table.doubleClicked.connect(
            lambda model_index, opened_page=page: self._open_directory_entry(
                opened_page,
                model_index,
            )
        )
        self._sync_empty_state()
        self._update_window_title()

        self.statusBar().showMessage(self.tr('Loading {0}...').format(normalized))
        future = self._task_executor.submit(load_directory_entries, normalized)
        self._directory_futures[key] = future
        future.add_done_callback(
            lambda completed, page_key=key: self._forward_directory_result(page_key, completed)
        )

    def _forward_directory_result(self, path_key: str, future: Future) -> None:
        try:
            entries = future.result()
        except CancelledError:
            return
        except Exception as exc:
            entries = ()
            error = str(exc)
        else:
            error = ""
        try:
            self._directory_signals.completed.emit(path_key, future, entries, error)
        except RuntimeError:
            return

    @Slot(str, object, object, str)
    def _on_directory_loaded(
        self,
        path_key: str,
        future: object,
        entries: object,
        error: str,
    ) -> None:
        if self._directory_futures.get(path_key) is not future:
            return
        self._directory_futures.pop(path_key, None)
        page = self._pages_by_path.get(path_key)
        if not isinstance(page, DirectoryBrowserPage):
            return
        loaded_entries = entries if isinstance(entries, tuple) else ()
        page.show_directory_result(loaded_entries, error)
        pending_selection = self._pending_search_selections.pop(path_key, None)
        if pending_selection is not None:
            selected = self._select_directory_entry(page, pending_selection)
            pending_open = self._pending_search_opens.pop(path_key, None)
            if selected and pending_open == pending_selection:
                self._open_directory_entry(page, page.table.currentIndex())
        if error:
            self.statusBar().showMessage(self.tr('Unable to read {0}: {1}').format(page.directory, error), 8000)
        else:
            self.statusBar().clearMessage()

    def _queue_archive_open(
        self,
        path: Path,
        *,
        page_key: str | None = None,
        display_title: str | None = None,
        ancestors: tuple[tuple[str, str], ...] = (),
        location_text: str | None = None,
        source_offset: int = 0,
        source_size: int | None = None,
        parents: tuple[MixArchiveParent, ...] = (),
        discover_names: bool = True,
        reload_existing: bool = False,
    ) -> None:
        if not path.is_file():
            return
        try:
            normalized_path = path.expanduser().resolve()
        except OSError:
            return
        if normalized_path.suffix.casefold() != ".mix":
            try:
                with normalized_path.open("rb") as source:
                    prefix = source.read(128)
                file_size = normalized_path.stat().st_size
            except OSError:
                return
            if detect_content_type(prefix, file_size) != "MIX":
                return
        key = page_key or str(normalized_path).casefold()
        if key in self._pending_paths:
            return
        existing = self._pages_by_path.get(key)
        if existing is not None and not (
            reload_existing and isinstance(existing, MixArchivePage)
        ):
            if isinstance(existing, MixArchivePage):
                self._update_page_navigation_context(
                    existing,
                    ancestors,
                    location_text or str(existing.archive.path),
                )
            self.tabs.setCurrentWidget(existing)
            return
        if reload_existing:
            self._pending_replacements.add(key)
        self._pending_paths[key] = normalized_path
        if display_title is not None:
            self._pending_titles[key] = display_title
        if ancestors:
            self._pending_ancestors[key] = ancestors
        if location_text is not None:
            self._pending_locations[key] = location_text
        if discover_names:
            self._start_open_progress(
                key,
                self.tr("Opening MIX Archive"),
                self.tr("Matching known MIX names in {0}...").format(
                    display_title or normalized_path.name
                ),
            )
        future = self._task_executor.submit(
            self._archive_load_session.load,
            normalized_path,
            source_offset=source_offset,
            source_size=source_size,
            parents=parents,
            discover_names=discover_names,
            refresh_candidates=discover_names,
        )
        self._bind_open_progress(key, future)
        future.add_done_callback(
            lambda completed, pending_key=key: self._forward_archive_result(pending_key, completed)
        )

    def _forward_archive_result(self, path_key: str, future: Future[MixArchiveIndex]) -> None:
        try:
            archive = future.result()
        except CancelledError:
            return
        except Exception as exc:
            self._open_signals.completed.emit(path_key, None, str(exc))
        else:
            self._open_signals.completed.emit(path_key, archive, "")

    @Slot(str, object, str)
    def _on_archive_opened(self, path_key: str, archive: object, error: str) -> None:
        path = self._pending_paths.pop(path_key, None)
        if path is None:
            return
        replace_existing = path_key in self._pending_replacements
        self._pending_replacements.discard(path_key)
        display_title = self._pending_titles.pop(path_key, None)
        ancestors = self._pending_ancestors.pop(path_key, ())
        location_text = self._pending_locations.pop(path_key, None)
        is_nested_archive = bool(ancestors)
        if isinstance(archive, MixArchiveIndex):
            existing = self._pages_by_path.get(path_key)
            try:
                if replace_existing and isinstance(existing, MixArchivePage):
                    existing.replace_archive(archive)
                    self._update_page_navigation_context(
                        existing,
                        ancestors,
                        location_text or str(archive.path),
                    )
                    self.tabs.setCurrentWidget(existing)
                    existing.table.setFocus()
                else:
                    self._show_archive(
                        archive,
                        path_key=path_key,
                        display_title=display_title,
                        ancestors=ancestors,
                        location_text=location_text,
                    )
            finally:
                self._finish_open_progress(path_key)
        else:
            self._finish_open_progress(path_key)
            location = display_title if is_nested_archive and display_title else str(path)
            QMessageBox.warning(self, self.tr("Unable to open MIX archive"), self.tr('{0}\n\n{1}').format(location, error))
            if path_key in self._unsaved_mix_roots:
                self._unsaved_mix_roots.discard(path_key)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        if not self._pending_paths and self._restore_active_path_key:
            page = self._pages_by_path.get(self._restore_active_path_key)
            if page is not None:
                self.tabs.setCurrentWidget(page)
                page.table.setFocus()
            self._restore_active_path_key = None
        if not self._pending_paths and self._reload_archives_when_idle:
            QTimer.singleShot(0, self._reload_open_archives)
        self._update_open_status()
        self._sync_workspace_actions()

    # @arch mix-browser.community-name-database-download-confirmation handler | en: Confirms the remote database size before starting a download | zh: 下载前显示社区数据库大小并等待用户确认
    def _request_community_name_database_download(
        self,
        page: MixNameSourcesPage,
    ) -> None:
        if self._community_database_size_request_pending:
            return
        if self._community_database_size_bytes is not None:
            self._confirm_community_name_database_download(
                page,
                self._community_database_size_bytes,
            )
            return

        page.community_download_button.setEnabled(False)
        self._community_database_size_request_pending = True
        confirmation = QMessageBox(page)
        confirmation.setIcon(QMessageBox.Icon.Question)
        confirmation.setWindowTitle(self.tr("Confirm Community Database Download"))
        confirmation.setText(
            self._community_name_database_download_confirmation_text(
                page,
                None,
                checking_size=True,
            )
        )
        confirmation.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        confirmation.setDefaultButton(QMessageBox.StandardButton.No)
        yes_button = confirmation.button(QMessageBox.StandardButton.Yes)
        if yes_button is not None:
            yes_button.setEnabled(False)
        confirmation.setWindowModality(Qt.WindowModality.WindowModal)
        confirmation.finished.connect(
            lambda result, source_page=page, dialog=confirmation: self._on_community_name_database_download_confirmation_finished(
                source_page,
                dialog,
                result,
            )
        )
        self._community_database_confirmation_page = page
        self._community_database_confirmation_box = confirmation
        confirmation.open()

        future = self._task_executor.submit(
            self._archive_application.community_name_database_size_bytes
        )
        future.add_done_callback(
            lambda completed, source_page=page: self._forward_community_name_database_download_confirmation_size(
                source_page,
                completed,
            )
        )

    def _forward_community_name_database_download_confirmation_size(
        self,
        page: MixNameSourcesPage,
        future: Future,
    ) -> None:
        try:
            size_bytes = future.result()
        except Exception as exc:
            size_bytes = None
            error = str(exc)
        else:
            error = ""
        try:
            self._community_name_database_signals.download_confirmation_size_completed.emit(
                page,
                size_bytes,
                error,
            )
        except RuntimeError:
            return

    @Slot(object, object, str)
    def _on_community_name_database_download_confirmation_size_completed(
        self,
        page: object,
        size_bytes: object,
        _error: str,
    ) -> None:
        self._community_database_size_request_pending = False
        if not isinstance(page, MixNameSourcesPage):
            return
        try:
            page.community_download_button.setEnabled(True)
            if isinstance(size_bytes, int) and size_bytes > 0:
                self._community_database_size_bytes = size_bytes
            else:
                size_bytes = self._community_database_size_bytes
            confirmation = self._community_database_confirmation_box
            if (
                confirmation is None
                or self._community_database_confirmation_page is not page
                or not confirmation.isVisible()
            ):
                return
            confirmation.setText(
                self._community_name_database_download_confirmation_text(
                    page,
                    size_bytes if isinstance(size_bytes, int) else None,
                )
            )
            yes_button = confirmation.button(QMessageBox.StandardButton.Yes)
            if yes_button is not None:
                yes_button.setEnabled(True)
        except RuntimeError:
            return

    # @arch mix-browser.community-name-database-confirmation-finished handler | en: Starts a confirmed community database download and releases its size dialog | zh: 根据用户确认启动社区数据库下载并释放大小提示框
    def _on_community_name_database_download_confirmation_finished(
        self,
        page: MixNameSourcesPage,
        confirmation: QMessageBox,
        result: int,
    ) -> None:
        if self._community_database_confirmation_box is confirmation:
            self._community_database_confirmation_box = None
            self._community_database_confirmation_page = None
        try:
            if not self._community_database_size_request_pending:
                page.community_download_button.setEnabled(True)
        except RuntimeError:
            return
        confirmation.deleteLater()
        if (
            result == QMessageBox.StandardButton.Yes.value
            and not self._community_database_size_request_pending
        ):
            self._start_community_name_database_download(page)

    def _confirm_community_name_database_download(
        self,
        page: MixNameSourcesPage,
        size_bytes: int | None,
    ) -> None:
        answer = QMessageBox.question(
            page,
            self.tr("Confirm Community Database Download"),
            self._community_name_database_download_confirmation_text(
                page,
                size_bytes,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_community_name_database_download(page)

    def _community_name_database_download_confirmation_text(
        self,
        page: MixNameSourcesPage,
        size_bytes: int | None,
        *,
        checking_size: bool = False,
    ) -> str:
        if checking_size:
            details = self.tr("Checking file size...")
        elif size_bytes is not None:
            details = self.tr("File size: {0}").format(format_byte_size(size_bytes))
        else:
            details = self.tr("File size unavailable")
        message = self.tr(
            "Start downloading the CnCNet community MIX name database?\n\n{0}"
        ).format(details)
        if page.community_database_downloaded:
            message += "\n\n" + self.tr(
                "The existing copy will be replaced after the new download is validated."
            )
        return message

    # @arch mix-browser.download-community-name-database-handler handler | en: Starts the optional community database download with shared progress UI | zh: 使用共享进度界面启动可选社区数据库下载
    def _start_community_name_database_download(
        self,
        page: MixNameSourcesPage,
    ) -> None:
        page.community_download_button.setEnabled(False)
        cancellation = TaskCancellationToken()
        progress = TaskProgressDialog(
            self._progress_controller,
            self.tr("Downloading Community Database"),
            self.tr("Downloading the CnCNet community MIX name database..."),
            mode=ProgressMode.INDETERMINATE,
            cancel_callback=cancellation.cancel,
            parent=page.window(),
        )
        progress.show()
        report_progress = lambda completed, total: self._community_name_database_signals.progress.emit(
            progress,
            completed,
            total,
        )
        future = self._task_executor.submit(
            self._archive_application.download_community_name_database,
            progress=report_progress,
            cancellation_requested=cancellation.is_cancelled,
        )
        future.add_done_callback(
            lambda completed, source_page=page, task_dialog=progress: self._forward_community_name_database_download(
                source_page,
                task_dialog,
                completed,
            )
        )

    def _forward_community_name_database_download(
        self,
        page: MixNameSourcesPage,
        progress: TaskProgressDialog,
        future: Future,
    ) -> None:
        try:
            result = future.result()
        except (CancelledError, InterruptedError):
            result = None
            error = "cancelled"
        except Exception as exc:
            result = None
            error = str(exc)
        else:
            error = ""
        try:
            self._community_name_database_signals.completed.emit(
                page,
                progress,
                result,
                error,
            )
        except RuntimeError:
            return

    @Slot(object, int, int)
    def _on_community_name_database_progress(
        self,
        progress: object,
        completed: int,
        total: int,
    ) -> None:
        if not isinstance(progress, TaskProgressDialog):
            return
        if total > 0:
            if (
                progress.mode is not ProgressMode.DETERMINATE
                or progress.total != total
            ):
                progress.set_mode(ProgressMode.DETERMINATE, total)
            progress.set_progress(completed, total)
        elif completed > 0:
            progress.set_message(
                self.tr("Downloaded {0}").format(format_byte_size(completed))
            )

    @Slot(object, object, object, str)
    def _on_community_name_database_download_completed(
        self,
        page: object,
        progress: object,
        result: object,
        error: str,
    ) -> None:
        if isinstance(progress, TaskProgressDialog):
            try:
                progress.finish()
            except RuntimeError:
                pass
        if not isinstance(page, MixNameSourcesPage):
            return
        try:
            page.community_download_button.setEnabled(True)
            if error == "cancelled":
                return
            if error or not isinstance(result, dict):
                QMessageBox.warning(
                    page,
                    self.tr("Community Database Download Failed"),
                    self.tr(
                        "The community MIX name database could not be downloaded:\n{0}"
                    ).format(error or self.tr("The download returned no database.")),
                )
                return
            size_bytes = result.get("size_bytes")
            if isinstance(size_bytes, int) and size_bytes > 0:
                self._community_database_size_bytes = size_bytes
            enable_source = (
                page.community_checkbox.isChecked()
                if page.community_database_downloaded
                else True
            )
            page.set_community_database_downloaded(
                True,
                enable_source=enable_source,
            )
            if self._community_names_enabled:
                self._archive_load_session = self._archive_loader.create_session()
                self._reload_open_archives()
        except RuntimeError:
            return

    def _start_palette_catalog_refresh(
        self,
        dialog: PaletteSourcesPage,
    ) -> None:
        raw_directory = dialog.directory_edit.text().strip()
        directory = Path(raw_directory).expanduser() if raw_directory else None
        if directory is None or not directory.is_dir():
            QMessageBox.warning(
                dialog,
                self.tr("Invalid Game Directory"),
                self.tr("Select an existing game directory before refreshing palette search."),
            )
            return
        try:
            directory = directory.resolve()
        except OSError:
            pass

        dialog.refresh_palette_button.setEnabled(False)
        cancellation = Event()
        progress = TaskProgressDialog(
            self._progress_controller,
            self.tr("Refreshing Palette Search"),
            self.tr('Scanning palettes and art rules in {0}...').format(directory),
            mode=ProgressMode.INDETERMINATE,
            cancel_callback=cancellation.set,
            parent=dialog,
        )
        progress.show()
        future = self._task_executor.submit(
            refresh_game_palette_catalog,
            directory,
            cancellation_event=cancellation,
        )
        future.add_done_callback(
            lambda completed, palette_dialog=dialog, task_dialog=progress, scanned_directory=directory: self._forward_palette_catalog_refresh(
                palette_dialog,
                task_dialog,
                scanned_directory,
                completed,
            )
        )

    def _forward_palette_catalog_refresh(
        self,
        dialog: PaletteSourcesPage,
        progress: TaskProgressDialog,
        directory: Path,
        future: Future,
    ) -> None:
        try:
            result = future.result()
        except CancelledError:
            result = None
            error = "cancelled"
        except Exception as exc:
            result = None
            error = str(exc)
        else:
            error = ""
        try:
            self._palette_catalog_signals.completed.emit(
                dialog,
                progress,
                directory,
                result,
                error,
            )
        except RuntimeError:
            return

    @Slot(object, object, object, object, str)
    def _on_palette_catalog_refresh_completed(
        self,
        dialog: object,
        progress: object,
        directory: object,
        result: object,
        error: str,
    ) -> None:
        if isinstance(progress, TaskProgressDialog):
            try:
                progress.finish()
            except RuntimeError:
                pass
        if not isinstance(dialog, PaletteSourcesPage):
            return
        try:
            dialog.refresh_palette_button.setEnabled(
                bool(dialog.directory_edit.text().strip())
            )
        except RuntimeError:
            return
        if isinstance(directory, Path):
            preload_key = game_palette_catalog_directory_key(directory)
            self._palette_catalog_preloads.pop(preload_key, None)
        if error == "cancelled":
            return
        if error or result is None:
            QMessageBox.warning(
                dialog,
                self.tr("Palette Search Refresh Failed"),
                error or "The palette search could not be refreshed.",
            )
            return
        if self._palette_directory is None:
            return
        if not isinstance(directory, Path):
            return
        requested_directory = directory
        try:
            same_directory = requested_directory.resolve() == self._palette_directory.resolve()
        except OSError:
            same_directory = requested_directory == self._palette_directory
        if same_directory:
            self._refresh_current_preview()

    def _refresh_current_preview(self) -> None:
        page = self.tabs.currentWidget()
        if not isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
            return
        index = page.table.currentIndex()
        model = page.entry_table.source_model
        if not index.isValid():
            return
        entry = model.entry_at(index.row())
        if isinstance(entry, (MixEntry, DirectoryEntry)):
            self._request_entry_preview(page.path_key, entry)

    def _ensure_game_palette_catalog_snapshot(self, directory: Path) -> None:
        if game_palette_catalog_is_ready_or_loading(directory):
            return
        key = game_palette_catalog_directory_key(directory)
        existing = self._palette_catalog_preloads.get(key)
        if existing is not None:
            return

        mark_game_palette_catalog_scheduled(directory)
        cancellation = Event()
        self._palette_catalog_cancellations[key] = cancellation
        future = self._task_executor.submit(
            load_game_palette_catalog_snapshot,
            directory,
            cancellation_event=cancellation,
            scan_started=lambda scanned_directory=directory: self._palette_catalog_signals.scan_started.emit(
                scanned_directory
            ),
        )
        self._palette_catalog_preloads[key] = future
        future.add_done_callback(
            lambda completed, scanned_directory=directory: self._forward_game_palette_catalog_snapshot(
                scanned_directory,
                completed,
            )
        )

    def _forward_game_palette_catalog_snapshot(
        self,
        directory: Path,
        future: Future,
    ) -> None:
        try:
            result = future.result()
        except CancelledError:
            result = None
            error = "cancelled"
        except Exception as exc:
            result = None
            error = str(exc)
        else:
            error = ""
        try:
            self._palette_catalog_signals.snapshot_completed.emit(
                directory,
                result,
                error,
            )
        except RuntimeError:
            return

    @Slot(object)
    def _on_palette_catalog_scan_started(self, directory: object) -> None:
        if not isinstance(directory, Path):
            return
        key = game_palette_catalog_directory_key(directory)
        cancellation = self._palette_catalog_cancellations.get(key)
        if cancellation is None or cancellation.is_set():
            return
        if key in self._palette_catalog_progress:
            return
        progress = TaskProgressDialog(
            self._progress_controller,
            self.tr("Scanning Game Palette Data"),
            self.tr("Scanning palettes and art rules in {0}...").format(directory),
            mode=ProgressMode.INDETERMINATE,
            cancel_callback=cancellation.set,
            parent=self,
        )
        self._palette_catalog_progress[key] = progress
        progress.show()

    @Slot(object, object, str)
    def _on_palette_catalog_snapshot_completed(
        self,
        directory: object,
        result: object,
        error: str,
    ) -> None:
        if not isinstance(directory, Path):
            return
        key = game_palette_catalog_directory_key(directory)
        self._palette_catalog_preloads.pop(key, None)
        self._palette_catalog_cancellations.pop(key, None)
        progress = self._palette_catalog_progress.pop(key, None)
        if progress is not None:
            try:
                progress.finish()
            except RuntimeError:
                pass
        if error == "cancelled":
            return
        if error or result is None:
            QMessageBox.warning(
                self,
                self.tr("Game Palette Data Load Failed"),
                error or self.tr("The game palette data could not be loaded."),
            )

    def _reload_open_archives(self) -> None:
        if self._pending_paths:
            self._reload_archives_when_idle = True
            return
        self._reload_archives_when_idle = False
        pages = [
            self.tabs.widget(index)
            for index in range(self.tabs.count())
            if isinstance(self.tabs.widget(index), MixArchivePage)
        ]
        if not pages:
            return
        current_page = self.tabs.currentWidget()
        self._restore_active_path_key = getattr(current_page, "path_key", None)
        archives_to_reload = [
            (
                page.archive.path,
                page.path_key,
                page.display_title,
                page.ancestors,
                page.location_text,
                page.archive.source_offset,
                page.archive.source_size if page.archive.source_offset else None,
                page.archive.parents,
            )
            for page in pages
        ]
        for index in reversed(range(self.tabs.count())):
            page = self.tabs.widget(index)
            if not isinstance(page, MixArchivePage):
                continue
            self.tabs.removeTab(index)
            self._cancel_entry_preview(page.path_key)
            self._pages_by_path.pop(page.path_key, None)
            page.preview.shutdown()
            page.deleteLater()
        self._sync_breadcrumb_navigation()
        self._sync_empty_state()
        for (
            path,
            page_key,
            display_title,
            ancestors,
            location_text,
            source_offset,
            source_size,
            parents,
        ) in archives_to_reload:
            self._queue_archive_open(
                path,
                page_key=page_key,
                display_title=display_title,
                ancestors=ancestors,
                location_text=location_text,
                source_offset=source_offset,
                source_size=source_size,
                parents=parents,
            )
        self._update_open_status()

    def _update_open_status(self) -> None:
        if self._pending_paths:
            path_key = next(iter(self._pending_paths))
            path = self._pending_paths[path_key]
            title = self._pending_titles.get(path_key, path.name)
            self.statusBar().showMessage(self.tr('Opening {0} ({1} queued)').format(title, len(self._pending_paths)))
        else:
            self.statusBar().clearMessage()

    def _show_archive(
        self,
        archive: MixArchiveIndex,
        *,
        path_key: str | None = None,
        display_title: str | None = None,
        ancestors: tuple[tuple[str, str], ...] = (),
        location_text: str | None = None,
    ) -> None:
        path_key = path_key or str(archive.path).casefold()
        existing = self._pages_by_path.get(path_key)
        if existing is not None:
            self._update_page_navigation_context(
                existing,
                ancestors,
                location_text or str(existing.archive.path),
            )
            self.tabs.setCurrentWidget(existing)
            existing.table.setFocus()
            return

        title = display_title or archive.path.name
        page_location = location_text or str(archive.path)
        page = MixArchivePage(
            archive,
            path_key,
            title,
            ancestors=ancestors,
            location_text=page_location,
            parent=self.tabs,
        )
        self._configure_entry_type_filters(page.entry_table)
        self._apply_auto_play_preferences(page)
        page.preview.auto_play_preference_changed.connect(
            self._set_auto_play_preference
        )
        page.navigate_requested.connect(self._activate_page)
        page.preview_requested.connect(
            lambda entry, key=path_key: self._request_entry_preview(key, entry)
        )
        page.preview_state_changed.connect(self._sync_active_status)
        page.filter_state_changed.connect(self._sync_active_status)
        page.context_menu_requested.connect(
            lambda position, target=page: self._show_entry_context_menu(target, position)
        )
        page.drag_requested.connect(lambda target=page: self._start_table_drag(target))
        page.drag_cancelled.connect(lambda target=page: self._cancel_table_drag(target))
        page.table.selectionModel().selectionChanged.connect(self._sync_workspace_actions)
        page.content_splitter.splitterMoved.connect(
            lambda *_args: self._sync_status_splitter()
        )
        self._pages_by_path[path_key] = page
        index = self.tabs.addTab(
            page,
            system_icon_for_object(is_directory=False),
            title,
        )
        self.tabs.setTabToolTip(index, page.location_text)
        self._sync_empty_state()
        self.tabs.setCurrentIndex(index)
        page.table.setFocus()
        self._sync_breadcrumb_navigation()
        self._register_drop_targets(page)
        page.table.doubleClicked.connect(
            lambda index, opened_page=page: self._open_entry(opened_page, index)
        )
        self._update_window_title()

    def _request_entry_preview(self, path_key: str, entry: object) -> None:
        page = self._pages_by_path.get(path_key)
        if page is None:
            return
        if self.tabs.currentWidget() is not page:
            return
        self._cancel_entry_preview(path_key)
        if isinstance(page, MixArchivePage) and isinstance(entry, MixEntry):
            loader = load_entry_preview
            source = page.archive
        elif isinstance(page, DirectoryBrowserPage) and isinstance(entry, DirectoryEntry):
            loader = load_path_preview
            source = entry.path
        else:
            page.clear_preview()
            return

        self._next_preview_request_id += 1
        request_id = self._next_preview_request_id
        page.show_preview_loading(request_id, entry)
        self._preview_requests[request_id] = path_key
        palette_context = tuple(title for _, title in page.ancestors) + (
            page.display_title,
        )
        if isinstance(entry, MixEntry):
            future = self._task_executor.submit(
                loader,
                source,
                entry,
                self._palette_directory,
                palette_theater=self._palette_theater,
                xcc_names_enabled=self._xcc_names_enabled,
                community_names_enabled=self._community_names_enabled,
                palette_library=self._palette_library_rules,
                include_game_palettes=self._palette_directory is None,
                palette_context=palette_context,
            )
        else:
            future = self._task_executor.submit(
                loader,
                source,
                self._palette_directory,
                palette_theater=self._palette_theater,
                xcc_names_enabled=self._xcc_names_enabled,
                community_names_enabled=self._community_names_enabled,
                palette_library=self._palette_library_rules,
                include_game_palettes=self._palette_directory is None,
                palette_context=palette_context,
            )
        self._preview_futures[path_key] = (request_id, future)
        future.add_done_callback(
            lambda completed, pending_id=request_id: self._forward_entry_preview(pending_id, completed)
        )

    def _cancel_entry_preview(self, path_key: str) -> bool:
        pending = self._preview_futures.pop(path_key, None)
        if pending is None:
            return False
        request_id, future = pending
        self._preview_requests.pop(request_id, None)
        cancellation_event = self._preview_cancellations.pop(request_id, None)
        if cancellation_event is not None:
            cancellation_event.set()
        future.cancel()
        return True

    def _forward_entry_preview(
        self,
        request_id: int,
        future: Future[EntryPreviewResult],
    ) -> None:
        try:
            result = future.result()
        except CancelledError:
            result = None
            error = "cancelled"
        except Exception:
            result = None
            error = "read-failed"
        else:
            error = ""
        try:
            self._preview_signals.completed.emit(request_id, result, error)
        except RuntimeError:
            return

    @Slot(int, object, str)
    def _on_entry_preview_completed(
        self,
        request_id: int,
        result: object,
        error: str,
    ) -> None:
        path_key = self._preview_requests.get(request_id)
        if path_key is None:
            return
        pending = self._preview_futures.get(path_key)
        if pending is not None and pending[0] == request_id:
            self._preview_futures.pop(path_key, None)
        page = self._pages_by_path.get(path_key)
        if page is None:
            self._preview_requests.pop(request_id, None)
            return
        if error or not isinstance(result, EntryPreviewResult):
            result = EntryPreviewResult(
                "message",
                message=self.tr("The entry could not be read from the archive."),
            )
        if (
            self._palette_directory is not None
            and isinstance(result, EntryPreviewResult)
            and (result.frames or result.voxel_model is not None)
        ):
            self._ensure_game_palette_catalog_snapshot(self._palette_directory)
        page.show_preview_result(request_id, result)
        if (
            not error
            and isinstance(result, EntryPreviewResult)
            and self._palette_directory is not None
            and (result.frames or result.voxel_model is not None)
        ):
            preview_entry = page.preview_entry
            cancellation_event = Event()
            if (
                isinstance(page, MixArchivePage)
                and isinstance(preview_entry, MixEntry)
            ):
                future = self._task_executor.submit(
                    load_entry_palette_update,
                    result,
                    page.archive,
                    preview_entry,
                    self._palette_directory,
                    palette_theater=self._palette_theater,
                    xcc_names_enabled=self._xcc_names_enabled,
                    community_names_enabled=self._community_names_enabled,
                    palette_library=self._palette_library_rules,
                    cancellation_event=cancellation_event,
                    palette_context=tuple(title for _, title in page.ancestors)
                    + (page.display_title,),
                )
            elif (
                isinstance(page, DirectoryBrowserPage)
                and isinstance(preview_entry, DirectoryEntry)
            ):
                palette_entry = MixEntry(
                    0,
                    0,
                    preview_entry.size,
                    preview_entry.path.name,
                    file_type=preview_entry.file_type,
                )
                future = self._task_executor.submit(
                    load_path_palette_update,
                    result,
                    preview_entry.path,
                    palette_entry,
                    self._palette_directory,
                    palette_theater=self._palette_theater,
                    xcc_names_enabled=self._xcc_names_enabled,
                    community_names_enabled=self._community_names_enabled,
                    palette_library=self._palette_library_rules,
                    cancellation_event=cancellation_event,
                    palette_context=tuple(title for _, title in page.ancestors)
                    + (page.display_title,),
                )
            else:
                future = None
            if future is not None:
                self._preview_cancellations[request_id] = cancellation_event
                self._preview_futures[path_key] = (request_id, future)
                future.add_done_callback(
                    lambda completed, pending_id=request_id: self._forward_entry_palette_update(
                        pending_id,
                        completed,
                    )
                )
                return
        self._preview_requests.pop(request_id, None)

    def _forward_entry_palette_update(
        self,
        request_id: int,
        future: Future[EntryPreviewResult],
    ) -> None:
        try:
            result = future.result()
        except CancelledError:
            result = None
            error = "cancelled"
        except Exception:
            result = None
            error = "read-failed"
        else:
            error = ""
        try:
            self._preview_signals.palette_completed.emit(request_id, result, error)
        except RuntimeError:
            return

    @Slot(int, object, str)
    def _on_entry_palette_update_completed(
        self,
        request_id: int,
        result: object,
        error: str,
    ) -> None:
        path_key = self._preview_requests.pop(request_id, None)
        if path_key is None:
            return
        self._preview_cancellations.pop(request_id, None)
        pending = self._preview_futures.get(path_key)
        if pending is not None and pending[0] == request_id:
            self._preview_futures.pop(path_key, None)
        if error or not isinstance(result, EntryPreviewResult):
            page = self._pages_by_path.get(path_key)
            if page is not None:
                page.preview.show_palette_lookup_failure()
            return
        page = self._pages_by_path.get(path_key)
        if page is not None:
            page.update_preview_palette_result(request_id, result)

    def _open_entry(self, page: MixArchivePage, index: QModelIndex) -> None:
        model = page.entry_table.source_model
        entry = model.entry_at(index.row()) if isinstance(model, MixEntryTableModel) else None
        if entry is None:
            return
        is_named_mix = Path(entry.name or "").suffix.casefold() == ".mix"
        is_detected_mix = (entry.file_type or "").casefold() == "mix"
        if not is_named_mix and not is_detected_mix:
            self._open_entry_with_default_application(page.archive, entry, page.path_key)
            return

        nested_key = f"{page.path_key}!{entry.file_id:08x}"
        existing = self._pages_by_path.get(nested_key)
        if existing is not None:
            if isinstance(existing, MixArchivePage):
                title = entry.name or f"{entry.file_id:08X}.mix"
                self._update_page_navigation_context(
                    existing,
                    (*page.ancestors, (page.path_key, page.display_title)),
                    f"{page.location_text} > {title}",
                )
            self.tabs.setCurrentWidget(existing)
            return
        if nested_key in self._pending_paths:
            return

        title = entry.name or f"{entry.file_id:08X}.mix"
        self._pending_paths[nested_key] = page.archive.path
        self._pending_titles[nested_key] = title
        self._pending_ancestors[nested_key] = (*page.ancestors, (page.path_key, page.display_title))
        self._pending_locations[nested_key] = f"{page.location_text} > {title}"
        self._start_open_progress(
            nested_key,
            self.tr("Opening Nested MIX"),
            self.tr('Loading {0}...').format(title),
        )
        future = self._task_executor.submit(
            self._archive_load_session.load_nested,
            page.archive,
            entry,
            refresh_candidates=True,
        )
        self._bind_open_progress(nested_key, future)
        future.add_done_callback(
            lambda completed, pending_key=nested_key: self._forward_archive_result(pending_key, completed)
        )
        self._update_open_status()

    def _open_directory_entry(self, page: DirectoryBrowserPage, index: QModelIndex) -> None:
        model = page.entry_table.source_model
        entry = model.entry_at(index.row()) if isinstance(model, DirectoryEntryTableModel) else None
        if entry is None:
            return
        ancestors = (*page.ancestors, (page.path_key, page.display_title))
        if entry.is_directory:
            self._open_directory(entry.path, ancestors=ancestors)
            return
        if self._path_is_mix_archive(entry.path):
            self._queue_archive_open(
                entry.path,
                display_title=entry.path.name,
                ancestors=ancestors,
                location_text=f"{page.location_text} > {entry.path.name}",
            )
            self._update_open_status()
            return
        self._open_with_default_application(entry.path)

    def _open_entry_with_default_application(
        self,
        archive: MixArchiveIndex,
        entry: MixEntry,
        page_key: str,
    ) -> None:
        display_name = entry.name or f"Unknown (0x{entry.file_id:08X})"
        task_id, task = self._start_progress_task(
            "extract",
            display_name,
            self.tr('Creating a temporary copy of {0}...').format(display_name),
        )
        task.archive = archive
        task.entry = entry
        task.page_key = page_key
        progress = lambda completed, total: self._external_open_signals.progress.emit(
            task_id,
            completed,
            total,
        )
        task.future = self._task_executor.submit(
            extract_entry_to_temporary_file,
            archive,
            entry,
            self._temporary_root,
            progress=progress,
            cancellation_requested=task.cancellation.is_cancelled,
        )
        task.future.add_done_callback(
            lambda completed, pending_id=task_id: self._forward_progress_task(pending_id, completed)
        )

    def _start_progress_task(
        self,
        kind: str,
        display_name: str,
        message: str,
        *,
        modified_path: str | None = None,
        total: int | None = None,
    ) -> tuple[int, _ExternalProgressTask]:
        self._next_progress_task_id += 1
        task_id = self._next_progress_task_id
        cancellation = TaskCancellationToken()
        title = {
            "extract": self.tr("Creating temporary file"),
            "add": self.tr("Adding files"),
            "directory": self.tr("Updating folder items"),
            "save": self.tr("Saving MIX archive"),
        }.get(kind, self.tr("Updating MIX archive"))
        dialog = TaskProgressDialog(
            self._progress_controller,
            title,
            message,
            mode=(
                ProgressMode.DETERMINATE
                if total is not None
                else ProgressMode.INDETERMINATE
            ),
            total=total,
            cancel_callback=lambda pending_id=task_id: self._cancel_progress_task(pending_id),
            parent=self,
        )
        task = _ExternalProgressTask(kind, display_name, dialog, cancellation, modified_path=modified_path)
        self._progress_tasks[task_id] = task
        dialog.show()
        return task_id, task

    def _cancel_progress_task(self, task_id: int) -> None:
        task = self._progress_tasks.get(task_id)
        if task is None:
            return
        task.cancellation.cancel()
        if task.future is not None:
            task.future.cancel()

    @Slot(int, int, int)
    def _on_progress_task_progress(self, task_id: int, completed: int, total: int) -> None:
        task = self._progress_tasks.get(task_id)
        if task is not None and total > 0:
            if (
                task.dialog.mode is not ProgressMode.DETERMINATE
                or task.dialog.total != total
            ):
                task.dialog.set_mode(ProgressMode.DETERMINATE, total)
            task.dialog.set_progress(completed, total)

    def _forward_progress_task(self, task_id: int, future: Future) -> None:
        try:
            result = future.result()
        except CancelledError:
            error = "cancelled"
            result = None
        except InterruptedError:
            error = "cancelled"
            result = None
        except NoExternalChangesError:
            error = "no-changes"
            result = None
        except ExternalFileChangedError:
            error = "source-changed"
            result = None
        except PermissionError:
            result = None
            error = "access-denied"
        except MixFormatError:
            result = None
            error = "unsupported-format"
        except ValueError:
            result = None
            error = "format-limit"
        except ApplicationApiError as exc:
            result = exc.message
            error = f"api:{exc.code}"
        except OSError:
            result = None
            error = "io-error"
        except Exception:
            result = None
            error = "failed"
        else:
            error = ""
        try:
            self._external_open_signals.completed.emit(task_id, result, error)
        except RuntimeError:
            return

    @Slot(int, object, str)
    def _on_external_entry_extracted(self, task_id: int, result: object, error: str) -> None:
        task = self._progress_tasks.pop(task_id, None)
        if task is None:
            return

        if task.kind == "extract":
            if error == "cancelled":
                task.dialog.finish()
                self.statusBar().showMessage(self.tr("Temporary file creation cancelled."), 5000)
                return
            if error or not isinstance(result, ExtractedEntry):
                task.dialog.finish()
                self.statusBar().showMessage(
                    self.tr('Could not create a temporary copy of {0}.').format(task.display_name),
                    8000,
                )
                return
            if task.cancellation.is_cancelled():
                task.dialog.finish()
                shutil.rmtree(result.path.parent, ignore_errors=True)
                self.statusBar().showMessage(self.tr("Temporary file creation cancelled."), 5000)
                return
            try:
                opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.path)))
            except Exception:
                opened = False
            finally:
                task.dialog.finish()
            if not opened:
                shutil.rmtree(result.path.parent, ignore_errors=True)
                self.statusBar().showMessage(
                    self.tr('No default application could open {0}.').format(task.display_name),
                    8000,
                )
                return
            self._track_external_file(
                task.display_name,
                task.archive,
                task.entry,
                task.page_key,
                result,
            )
            self.statusBar().showMessage(
                self.tr('Opened {0} with the default application.').format(task.display_name),
                5000,
            )
            return

        task.dialog.finish()
        if task.kind == "save":
            self._finish_save_mix_task(task, result, error)
            return
        if task.kind == "directory":
            self._finish_directory_operation(task, result, error)
            return
        if task.kind == "add":
            try:
                self._finish_add_files_task(task, result, error)
            finally:
                self._cleanup_progress_task(task)
            return
        if task.kind == "edit":
            self._finish_edit_entries_task(task, result, error)
            return

        self._finish_write_back_task(task, result, error)

    def _finish_directory_operation(
        self,
        task: _ExternalProgressTask,
        result: object,
        error: str,
    ) -> None:
        if error == "cancelled":
            self.statusBar().showMessage(self.tr("Filesystem operation cancelled."), 6000)
            return
        if error or not isinstance(result, dict):
            message = (
                str(result)
                if result
                else self.tr("The filesystem operation could not be completed.")
            )
            self.statusBar().showMessage(self.tr('Filesystem operation failed: {0}').format(message), 9000)
            return

        affected_item_paths = list(result.get("deleted_paths", ()))
        destination = result.get("destination")
        if destination:
            affected_item_paths.extend(
                str(Path(destination) / name) for name in result.get("replaced_names", ())
            )
        self._close_pages_for_filesystem_paths(tuple(Path(path) for path in affected_item_paths))

        affected_keys = set(task.directory_keys)
        for page in tuple(self._pages_by_path.values()):
            if (
                isinstance(page, DirectoryBrowserPage)
                and str(page.directory.resolve()).casefold() in affected_keys
            ):
                self._refresh_directory_page(page)

        delete_failures = tuple(result.get("delete_failures", ()))
        if delete_failures:
            self.statusBar().showMessage(
                self.tr("Some filesystem items could not be deleted: {0}").format(
                    "; ".join(delete_failures)
                ),
                10000,
            )
        else:
            transferred = tuple(result.get("transferred_names", ()))
            deleted = tuple(result.get("deleted_paths", ()))
            created = result.get("created_path")
            if result.get("cancelled"):
                message = (
                    self.tr("Deleted {0} item(s) before cancellation.").format(len(deleted))
                    if deleted
                    else self.tr("Deletion cancelled.")
                )
            elif transferred:
                message = self.tr("Copied {0} to {1}.").format(
                    ", ".join(transferred), result.get("destination", "")
                )
            elif deleted:
                message = self.tr("Deleted {0} filesystem item(s).").format(len(deleted))
            elif created:
                message = self.tr("Created {0}.").format(created)
            else:
                message = self.tr("Filesystem operation completed.")
            self.statusBar().showMessage(message, 8000)
        self._sync_workspace_actions()

    def _close_pages_for_filesystem_paths(self, paths: tuple[Path, ...]) -> None:
        roots = tuple(path.resolve(strict=False) for path in paths)
        if not roots:
            return
        for page in tuple(self._pages_by_path.values()):
            page_path = (
                page.directory
                if isinstance(page, DirectoryBrowserPage)
                else page.archive.path
            ).resolve(strict=False)
            if any(page_path == root or root in page_path.parents for root in roots):
                self._close_page(page)

    @staticmethod
    def _cleanup_progress_task(task: _ExternalProgressTask) -> None:
        if task.cleanup_root is not None:
            shutil.rmtree(task.cleanup_root, ignore_errors=True)
            task.cleanup_root = None

    # @arch mix-browser.finish-archive-edit handler | en: Applies committed MIX edits to open views and clipboard state | zh: 将已提交的 MIX 编辑结果应用到打开视图与剪贴板状态
    def _finish_edit_entries_task(
        self,
        task: _ExternalProgressTask,
        result: object,
        error: str,
    ) -> None:
        if error == "cancelled":
            self.statusBar().showMessage(self.tr("MIX edit cancelled."), 7000)
            return
        if error:
            detail = str(result) if result else {
                "access-denied": "Check write access to the MIX archive.",
                "unsupported-format": "This MIX format cannot be safely rewritten.",
                "format-limit": "The operation exceeds a MIX format limit.",
                "io-error": "Check available disk space and file access.",
            }.get(error, "The MIX entries could not be edited.")
            self.statusBar().showMessage(self.tr('Could not edit MIX entries. {0}').format(detail), 9000)
            return
        if not isinstance(result, _EditedEntriesResult):
            self.statusBar().showMessage(self.tr("The MIX edit did not return a usable result."), 7000)
            return

        for prefix in task.close_page_prefixes:
            for path_key in tuple(self._pages_by_path):
                if path_key.startswith(prefix):
                    page = self._pages_by_path.get(path_key)
                    if page is not None:
                        self._close_page(page)
            for tracked_path, tracked in tuple(self._tracked_external_files.items()):
                if tracked.page_key.startswith(prefix):
                    self._file_watcher.removePath(str(tracked.path))
                    self._tracked_external_files.pop(tracked_path, None)
                    self._pending_external_hashes.discard(tracked_path)
                    self._remove_modified_external_file(tracked_path)

        root_path = Path(result.destination)
        for target_key, archive in result.refreshed_archives.items():
            if target_key.startswith("page:"):
                target_page = self._pages_by_path.get(target_key[len("page:"):])
                if isinstance(target_page, MixArchivePage):
                    target_page.replace_archive(archive)
            elif target_key.startswith("file:"):
                tracked_path = target_key[len("file:"):]
                tracked = self._tracked_external_files.get(tracked_path)
                if tracked is not None:
                    tracked.archive = archive
                    tracked.entry = next(
                        (entry for entry in archive.entries if entry.file_id == tracked.entry.file_id),
                        tracked.entry,
                    )
        target_page = self._pages_by_path.get(task.page_key or "")
        for tracked_path, tracked in tuple(self._tracked_external_files.items()):
            if tracked.archive.path != root_path:
                continue
            if (
                tuple(parent.entry_id for parent in tracked.archive.parents) == task.target_parent_entry_ids
                and tracked.entry.file_id in task.affected_entry_ids
            ):
                self._file_watcher.removePath(str(tracked.path))
                self._tracked_external_files.pop(tracked_path, None)
                self._remove_modified_external_file(tracked_path)
            else:
                tracked.archive_signature = result.archive_signature

        if result.refresh_error:
            self.statusBar().showMessage(
                self.tr("MIX entries were updated, but some open views could not be refreshed. Reopen the archive to see the changes."),
                10000,
            )
        else:
            details = []
            if result.removed_names:
                details.append(self.tr("Deleted {0}").format(", ".join(result.removed_names)))
            if result.renamed_names:
                details.append(self.tr("Renamed to {0}").format(", ".join(result.renamed_names)))
            if result.copied_names:
                details.append(self.tr("Copied {0}").format(", ".join(result.copied_names)))
            destination = (
                target_page.location_text
                if isinstance(target_page, MixArchivePage)
                else result.destination
            )
            self.statusBar().showMessage(
                self.tr('{0} in {1}.').format(
                    ' | '.join(details) or self.tr("Updated MIX entries"),
                    destination,
                ),
                9000,
            )

        self._sync_workspace_actions()

    def _track_external_file(
        self,
        display_name: str,
        archive: MixArchiveIndex | None,
        entry: MixEntry | None,
        page_key: str | None,
        extracted: ExtractedEntry,
    ) -> None:
        if page_key is None or archive is None or entry is None:
            return
        path_key = str(extracted.path)
        self._tracked_external_files[path_key] = _TrackedExternalFile(
            archive,
            entry,
            page_key,
            display_name,
            extracted.path,
            extracted.content_hash,
            extracted.content_hash,
            extracted.archive_signature,
            extracted.file_signature,
        )
        self._file_watcher.addPath(str(extracted.path))
        self._file_watcher.addPath(str(extracted.path.parent))

    def _on_external_file_hash_completed(
        self,
        path_key: str,
        result: object,
        error: str,
    ) -> None:
        self._hashing_external_files.discard(path_key)
        record = self._tracked_external_files.get(path_key)
        if record is None:
            return
        if error or not isinstance(result, tuple) or len(result) != 2:
            if record.path.exists():
                self._pending_external_hashes.add(path_key)
                self._external_hash_timer.start()
            return
        digest, signature = result
        if not isinstance(digest, str) or not isinstance(signature, tuple):
            return
        record.file_signature = signature
        if digest == record.original_hash:
            record.current_hash = record.original_hash
            record.dismissed_hash = None
            self._remove_modified_external_file(path_key)
        else:
            record.current_hash = digest
            if record.dismissed_hash == digest:
                self._remove_modified_external_file(path_key)
            elif path_key not in self._modified_external_files:
                self._modified_external_files.append(path_key)
        if record.path.exists() and str(record.path) not in self._file_watcher.files():
            self._file_watcher.addPath(str(record.path))
        if path_key in self._pending_external_hashes and not self._external_hash_timer.isActive():
            self._external_hash_timer.start()
        self._sync_modified_file_banner()

    def _queue_external_file_hash(self, path: str) -> None:
        if path in self._tracked_external_files:
            self._pending_external_hashes.add(path)
            self._external_hash_timer.start()

    def _queue_external_directory_hash(self, directory: str) -> None:
        for path_key, record in self._tracked_external_files.items():
            if record.path.parent == Path(directory):
                self._pending_external_hashes.add(path_key)
        if self._pending_external_hashes:
            self._external_hash_timer.start()

    def _poll_external_file_signatures(self) -> None:
        for path_key, record in self._tracked_external_files.items():
            try:
                current = record.path.stat()
            except OSError:
                continue
            if (current.st_size, current.st_mtime_ns) != record.file_signature:
                self._pending_external_hashes.add(path_key)
        if self._pending_external_hashes:
            self._external_hash_timer.start()

    def _check_pending_external_hashes(self) -> None:
        for path_key in tuple(self._pending_external_hashes):
            if path_key in self._hashing_external_files:
                continue
            self._pending_external_hashes.discard(path_key)
            record = self._tracked_external_files.get(path_key)
            if record is None:
                continue
            try:
                record.path.stat()
            except OSError:
                continue
            self._hashing_external_files.add(path_key)
            future = self._task_executor.submit(hash_file, record.path)
            future.add_done_callback(
                lambda completed, pending_path=path_key: self._forward_external_file_hash(
                    pending_path,
                    completed,
                )
            )

    def _forward_external_file_hash(self, path_key: str, future: Future) -> None:
        try:
            result = future.result()
            error = ""
        except Exception:
            result = None
            error = "hash-failed"
        try:
            self._external_open_signals.file_hash_completed.emit(path_key, result, error)
        except RuntimeError:
            return

    def _remove_modified_external_file(self, path_key: str) -> None:
        if path_key in self._modified_external_files:
            self._modified_external_files.remove(path_key)

    def _sync_modified_file_banner(self) -> None:
        path_key = next(
            (path for path in self._modified_external_files if path in self._tracked_external_files),
            None,
        )
        if path_key is None:
            self._modified_file_banner.hide()
            return
        record = self._tracked_external_files[path_key]
        self._modified_file_label.setText(
            self.tr('Changed file: {0}. Write the new version back to the MIX archive?').format(record.display_name)
        )
        self._modified_file_banner.show()

    def _dismiss_modified_file(self) -> None:
        path_key = next(
            (path for path in self._modified_external_files if path in self._tracked_external_files),
            None,
        )
        if path_key is None:
            return
        record = self._tracked_external_files[path_key]
        record.dismissed_hash = record.current_hash
        self._remove_modified_external_file(path_key)
        self._sync_modified_file_banner()

    def _write_back_modified_file(self) -> None:
        path_key = next(
            (path for path in self._modified_external_files if path in self._tracked_external_files),
            None,
        )
        if path_key is None:
            return
        record = self._tracked_external_files[path_key]
        root_path = record.archive.path
        reload_targets: dict[str, tuple[int, ...]] = {}
        for page in self._pages_by_path.values():
            if isinstance(page, MixArchivePage) and page.archive.path == root_path:
                reload_targets[f"page:{page.path_key}"] = tuple(
                    parent.entry_id for parent in page.archive.parents
                )
        for tracked_path, tracked in self._tracked_external_files.items():
            if tracked.archive.path == root_path:
                reload_targets[f"file:{tracked_path}"] = tuple(
                    parent.entry_id for parent in tracked.archive.parents
                )
        task_id, task = self._start_progress_task(
            "writeback",
            record.display_name,
            self.tr('Rebuilding {0} with the modified file...').format(root_path.name),
            modified_path=path_key,
        )
        progress = lambda completed, total: self._external_open_signals.progress.emit(
            task_id,
            completed,
            total,
        )
        archive_ids = tuple(parent.entry_id for parent in record.archive.parents)
        task.future = self._task_executor.submit(
            _write_back_and_refresh_archives,
            self._archive_loader,
            root_path,
            archive_ids,
            record.entry.file_id,
            record.path,
            self._temporary_root,
            record.original_hash,
            record.current_hash,
            record.archive_signature,
            tuple(reload_targets.items()),
            progress,
            task.cancellation.is_cancelled,
        )
        task.future.add_done_callback(
            lambda completed, pending_id=task_id: self._forward_progress_task(pending_id, completed)
        )

    def _finish_write_back_task(self, task: _ExternalProgressTask, result: object, error: str) -> None:
        path_key = task.modified_path
        record = self._tracked_external_files.get(path_key or "")
        if record is None:
            return
        if error == "cancelled":
            self.statusBar().showMessage(self.tr("MIX update cancelled."), 5000)
            self._sync_modified_file_banner()
            return
        if error == "no-changes":
            record.current_hash = record.original_hash
            record.dismissed_hash = None
            try:
                file_stat = record.path.stat()
                record.file_signature = (file_stat.st_size, file_stat.st_mtime_ns)
            except OSError:
                pass
            self._remove_modified_external_file(path_key)
            self.statusBar().showMessage(self.tr("The file matches the version already stored in the MIX archive."), 6000)
            self._sync_modified_file_banner()
            return
        if error == "source-changed":
            self.statusBar().showMessage(self.tr("The edited file or MIX archive changed. Check the file again before retrying."), 8000)
            self._queue_external_file_hash(path_key)
            self._sync_modified_file_banner()
            return
        if error or not isinstance(result, _WriteBackResult):
            reason = {
                "access-denied": "Check that the MIX archive is writable and not locked.",
                "unsupported-format": "This MIX format cannot be safely rewritten.",
                "format-limit": "The updated file exceeds a MIX format size limit.",
                "io-error": "Check available disk space and file access.",
            }.get(error, "The MIX archive could not be rewritten.")
            self.statusBar().showMessage(
                self.tr('Could not update {0}. {1}').format(record.display_name, reason),
                8000,
            )
            self._sync_modified_file_banner()
            return

        root_path = record.archive.path
        for target_key, archive in result.refreshed_archives.items():
            if target_key.startswith("page:"):
                page = self._pages_by_path.get(target_key[len("page:"):])
                if page is not None:
                    page.replace_archive(archive)
            elif target_key.startswith("file:"):
                tracked_path = target_key[len("file:"):]
                tracked = self._tracked_external_files.get(tracked_path)
                if tracked is not None:
                    tracked.archive = archive
                    tracked.entry = next(
                        item for item in archive.entries if item.file_id == tracked.entry.file_id
                    )
        for tracked in self._tracked_external_files.values():
            if tracked.archive.path == root_path:
                tracked.archive_signature = result.archive_signature
        record.original_hash = record.current_hash
        record.dismissed_hash = None
        self._remove_modified_external_file(path_key)
        if result.refresh_error:
            self.statusBar().showMessage(
                self.tr("The MIX was updated, but open views could not be refreshed. Reopen the archive to see the new contents."),
                10000,
            )
        else:
            self.statusBar().showMessage(
                self.tr('Updated {0} in {1}.').format(record.display_name, root_path.name),
                6000,
            )
        self._sync_modified_file_banner()

    def _close_tab(self, index: int) -> None:
        page = self.tabs.widget(index)
        if not isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
            return
        unsaved_root_key = self._unsaved_root_key_for_page(page)
        if unsaved_root_key is not None:
            related_pages = [
                candidate
                for candidate in self._pages_by_path.values()
                if isinstance(candidate, MixArchivePage)
                and (
                    candidate.path_key == unsaved_root_key
                    or any(key == unsaved_root_key for key, _title in candidate.ancestors)
                )
            ]
            pending_nested_paths = any(
                key.startswith(f"{unsaved_root_key}!")
                for key in self._pending_paths
            )
            if page.path_key == unsaved_root_key and (
                len(related_pages) > 1 or pending_nested_paths
            ):
                QMessageBox.information(
                    self,
                    self.tr("Unsaved MIX archive"),
                    self.tr("Close nested MIX tabs before closing this unsaved archive."),
                )
                return
            if len(related_pages) == 1:
                choice = QMessageBox.question(
                    self,
                    self.tr("Discard unsaved MIX archive?"),
                    self.tr("This MIX archive has not been saved. Close and discard it?"),
                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if choice != QMessageBox.StandardButton.Discard:
                    return
                self._unsaved_mix_roots.discard(unsaved_root_key)
                if isinstance(page, MixArchivePage):
                    try:
                        page.archive.path.unlink(missing_ok=True)
                    except OSError:
                        pass
        pending_drag = self._pending_drag_exports.get(page.path_key)
        if pending_drag is not None:
            pending_drag.cancellation.set()
            page.entry_table.cancel_pending_drag()
        page.preview.set_active(False)
        self._cancel_entry_preview(page.path_key)
        if isinstance(page, DirectoryBrowserPage):
            future = self._directory_futures.pop(page.path_key, None)
            self._pending_search_selections.pop(page.path_key, None)
            self._pending_search_opens.pop(page.path_key, None)
            if future is not None:
                future.cancel()
        self._pages_by_path.pop(page.path_key, None)
        self.tabs.removeTab(index)
        page.preview.shutdown()
        page.deleteLater()
        self._sync_breadcrumb_navigation()
        self._sync_empty_state()
        self._update_window_title()
        self._sync_workspace_actions()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._unsaved_mix_roots:
            message = QMessageBox(self)
            message.setWindowTitle(self.tr("Discard unsaved MIX archives?"))
            message.setText(self.tr("One or more new MIX archives have not been saved."))
            discard_button = message.addButton(
                self.tr("Discard and Close"),
                QMessageBox.ButtonRole.DestructiveRole,
            )
            cancel_button = message.addButton(
                QMessageBox.StandardButton.Cancel,
            )
            message.setDefaultButton(cancel_button)
            message.exec()
            if message.clickedButton() is not discard_button:
                event.ignore()
                return
            self._unsaved_mix_roots.clear()
        for path_key, pending_drag in self._pending_drag_exports.items():
            pending_drag.cancellation.set()
            page = self._pages_by_path.get(path_key)
            if isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
                page.entry_table.cancel_pending_drag()
        for cancellation_event in self._preview_cancellations.values():
            cancellation_event.set()
        for _, future in self._preview_futures.values():
            future.cancel()
        self._preview_requests.clear()
        self._preview_futures.clear()
        self._preview_cancellations.clear()
        for page in self._pages_by_path.values():
            page.preview.shutdown()
        self._remove_external_file_watches()
        super().closeEvent(event)

    def _close_page(self, page: QWidget) -> None:
        index = self.tabs.indexOf(page)
        if index >= 0:
            self._close_tab(index)

    def _show_tab_context_menu(self, position: QPoint) -> None:
        tab_bar = self.tabs.tabBar()
        index = tab_bar.tabAt(position)
        if index < 0:
            return
        target = self.tabs.widget(index)
        if not isinstance(target, (MixArchivePage, DirectoryBrowserPage)):
            return

        menu = QMenu(self)
        close_tab_action = menu.addAction(self.tr("Close Tab"))
        menu.addSeparator()
        close_others_action = menu.addAction(self.tr("Close Other Tabs"))
        close_others_action.setEnabled(self.tabs.count() > 1)
        close_left_action = menu.addAction(self.tr("Close Tabs to the Left"))
        close_left_action.setEnabled(index > 0)
        close_right_action = menu.addAction(self.tr("Close Tabs to the Right"))
        close_right_action.setEnabled(index < self.tabs.count() - 1)
        menu.addSeparator()
        close_all_action = menu.addAction(self.tr("Close All Tabs"))

        selected_action = menu.exec(tab_bar.mapToGlobal(position))
        if selected_action is close_tab_action:
            self._close_page(target)
        elif selected_action is close_others_action:
            for candidate in reversed(
                [self.tabs.widget(tab_index) for tab_index in range(self.tabs.count())]
            ):
                if candidate is not target:
                    self._close_page(candidate)
        elif selected_action is close_left_action:
            target_index = self.tabs.indexOf(target)
            for candidate in reversed(
                [self.tabs.widget(tab_index) for tab_index in range(target_index)]
            ):
                self._close_page(candidate)
        elif selected_action is close_right_action:
            target_index = self.tabs.indexOf(target)
            for candidate in reversed(
                [
                    self.tabs.widget(tab_index)
                    for tab_index in range(target_index + 1, self.tabs.count())
                ]
            ):
                self._close_page(candidate)
        elif selected_action is close_all_action:
            for candidate in reversed(
                [self.tabs.widget(tab_index) for tab_index in range(self.tabs.count())]
            ):
                self._close_page(candidate)

    def _activate_page(self, path_key: str) -> None:
        page = self._pages_by_path.get(path_key)
        if page is not None:
            self.tabs.setCurrentWidget(page)

    def _update_page_navigation_context(
        self,
        page: MixArchivePage | DirectoryBrowserPage,
        ancestors: tuple[tuple[str, str], ...],
        location_text: str | None = None,
    ) -> None:
        if isinstance(page, MixArchivePage):
            page.set_navigation_context(ancestors, location_text)
            tab_index = self.tabs.indexOf(page)
            if tab_index >= 0:
                self.tabs.setTabToolTip(tab_index, page.location_text)
        else:
            page.set_navigation_context(ancestors)
        self._sync_breadcrumb_navigation()

    def _sync_breadcrumb_navigation(self) -> None:
        available_keys = set(self._pages_by_path)
        for page in self._pages_by_path.values():
            page.set_available_ancestor_keys(available_keys)

    def _sync_empty_state(self) -> None:
        has_pages = self.tabs.count() > 0
        self.empty_state.setVisible(not has_pages)
        self.tabs.setVisible(has_pages)

    def _on_current_tab_changed(self, index: int) -> None:
        current_page = self.tabs.widget(index)
        for path_key, page in self._pages_by_path.items():
            if page is current_page:
                continue
            page.preview.set_active(False)
            if self._cancel_entry_preview(path_key):
                page.clear_preview()

        if isinstance(current_page, (MixArchivePage, DirectoryBrowserPage)):
            entry = current_page.current_entry()
            if entry is None:
                if current_page.preview_entry is not None:
                    current_page.clear_preview()
            elif current_page.preview_entry != entry:
                self._request_entry_preview(current_page.path_key, entry)
            current_page.preview.set_active(True)
        self._update_window_title(index)
        self._sync_workspace_actions()

    def _sync_active_status(self) -> None:
        page = self.tabs.currentWidget()
        encoding_visible = False
        if isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
            count = page.entry_table.visible_row_count
            self._status_left.setText(self.tr('{0:,} items').format(count))
            self._status_document.setText(page.preview_status_text)
            self._status_document.setToolTip(page.preview_status_text)
            encoding_index = self._status_encoding.findData(page.preview_encoding)
            encoding_visible = page.preview_encoding_enabled
            self._status_encoding.setEnabled(encoding_visible)
            self._status_encoding.setToolTip(
                self.tr("ANSI uses the system code page. Change the encoding if the text is not readable.")
            )
        else:
            self._status_left.clear()
            self._status_document.setText(self.tr("Select an entry"))
            self._status_document.setToolTip("")
            self._status_encoding.setEnabled(False)
            encoding_index = self._status_encoding.findData("ansi")

        self._status_encoding_label.setVisible(encoding_visible)
        self._status_encoding.setVisible(encoding_visible)
        if encoding_index < 0:
            encoding_index = 0
        was_blocked = self._status_encoding.blockSignals(True)
        self._status_encoding.setCurrentIndex(encoding_index)
        self._status_encoding.blockSignals(was_blocked)

    def _sync_status_splitter(self) -> None:
        status_width = self._status_splitter.width()
        if status_width <= 1:
            return
        page = self.tabs.currentWidget()
        if isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
            handle = page.content_splitter.handle(1)
            status_origin = self._status_splitter.mapTo(self, QPoint(0, 0)).x()
            content_boundary = handle.mapTo(self, QPoint(handle.width() // 2, 0)).x()
            left_width = content_boundary - status_origin
        else:
            left_width = round(status_width * 0.6)
        left_width = max(1, min(status_width - 1, left_width))
        self._status_splitter.setSizes([left_width, status_width - left_width])

    def _update_window_title(self, _index: int = -1) -> None:
        page = self.tabs.currentWidget()
        self._search_action.setEnabled(isinstance(page, (MixArchivePage, DirectoryBrowserPage)))
        if isinstance(page, (MixArchivePage, DirectoryBrowserPage)):
            self.setWindowTitle(self.tr('{0} - {1}').format(page.display_title, APPLICATION_DISPLAY_NAME))
        else:
            self.setWindowTitle(APPLICATION_DISPLAY_NAME)
        self._sync_active_status()
        QTimer.singleShot(0, self._sync_status_splitter)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_status_splitter"):
            QTimer.singleShot(0, self._sync_status_splitter)

    def _register_drop_targets(self, parent: QWidget) -> None:
        targets = [parent, *parent.findChildren(QWidget)]
        for target in targets:
            target.setAcceptDrops(True)
            target.installEventFilter(self)

    @staticmethod
    def _openable_paths_from_event(event) -> list[Path]:
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_dir() or path.is_file():
                paths.append(path)
        return paths

    def eventFilter(self, watched, event) -> bool:
        event_type = event.type()
        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if watched is self.tabs.tabBar():
                index = self.tabs.tabBar().tabAt(event.position().toPoint())
                if index >= 0 and index != self.tabs.currentIndex():
                    self.tabs.setCurrentIndex(index)
            if self._openable_paths_from_event(event):
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return True
        elif event_type == QEvent.Type.Drop:
            if watched is self.tabs.tabBar():
                index = self.tabs.tabBar().tabAt(event.position().toPoint())
                if index >= 0 and index != self.tabs.currentIndex():
                    self.tabs.setCurrentIndex(index)
            paths = self._openable_paths_from_event(event)
            if paths:
                if self._show_drop_action_dialog(tuple(paths)):
                    event.setDropAction(Qt.DropAction.CopyAction)
                    event.accept()
                else:
                    event.ignore()
                return True
        return super().eventFilter(watched, event)
