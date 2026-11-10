from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QT_TRANSLATE_NOOP, QAbstractTableModel, QModelIndex, Qt

from mix_browser.features.browser.formatting import format_byte_size
from mix_browser.features.browser.directory_listing import (
    DirectoryEntry,
    load_directory_entries,
)
from mix_browser.features.browser.file_type_support import browser_entry_type_display
from mix_browser.features.browser.system_icons import system_icon_for_object


class DirectoryEntryTableModel(QAbstractTableModel):
    HEADERS = tuple(
        QT_TRANSLATE_NOOP("DirectoryEntryTableModel", label)
        for label in ("Name", "Type", "Size", "Modified")
    )

    def __init__(self, entries: tuple[DirectoryEntry, ...] = (), parent=None) -> None:
        super().__init__(parent)
        self._entries = list(entries)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

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

    def entry_at(self, row: int) -> DirectoryEntry | None:
        if not 0 <= row < len(self._entries):
            return None
        return self._entries[row]

    def replace_entries(self, entries: tuple[DirectoryEntry, ...]) -> None:
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return entry.path.name or str(entry.path)
            if column == 1:
                if entry.file_type == "Folder":
                    return self.tr("Folder")
                if entry.file_type == "File":
                    return self.tr("File")
                if entry.file_type == "Unknown":
                    return self.tr("Unknown")
                return browser_entry_type_display(
                    entry.file_type,
                    entry.path.name,
                )
            if column == 2:
                return "" if entry.is_directory else format_byte_size(entry.size)
            if column == 3:
                return datetime.fromtimestamp(entry.modified).strftime("%Y-%m-%d %H:%M")
        if role == Qt.ItemDataRole.UserRole:
            if column == 0:
                return entry.path.name.casefold()
            if column == 1:
                return entry.file_type.casefold()
            if column == 2:
                return -1 if entry.is_directory else entry.size
            if column == 3:
                return entry.modified
        if role == Qt.ItemDataRole.DecorationRole and column == 0:
            return system_icon_for_object(is_directory=entry.is_directory)
        if role == Qt.ItemDataRole.TextAlignmentRole and column == 2:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(entry.path)
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self.HEADERS):
                return self.tr(self.HEADERS[section])
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        if not 0 <= column < len(self.HEADERS):
            return
        self.layoutAboutToBeChanged.emit()
        reverse = order == Qt.SortOrder.DescendingOrder
        if column == 0:
            key = lambda entry: entry.path.name.casefold()
        elif column == 1:
            key = lambda entry: browser_entry_type_display(
                entry.file_type,
                entry.path.name,
            ).casefold()
        elif column == 2:
            key = lambda entry: (-1 if entry.is_directory else entry.size)
        else:
            key = lambda entry: entry.modified
        self._entries.sort(key=key, reverse=reverse)
        self.layoutChanged.emit()
