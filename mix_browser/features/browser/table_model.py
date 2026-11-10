from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QT_TRANSLATE_NOOP, QAbstractTableModel, QModelIndex, Qt

from mix_browser.features.archive.domain import MixEntry
from mix_browser.features.browser.formatting import format_byte_size
from mix_browser.features.browser.file_type_support import browser_entry_type_display
from mix_browser.features.browser.system_icons import system_icon_for_object


class MixEntryTableModel(QAbstractTableModel):
    HEADERS = tuple(
        QT_TRANSLATE_NOOP("MixEntryTableModel", label)
        for label in ("Name", "Type", "Size", "ID")
    )

    def __init__(self, entries: tuple[MixEntry, ...], parent=None) -> None:
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

    def entry_at(self, row: int) -> MixEntry | None:
        if not 0 <= row < len(self._entries):
            return None
        return self._entries[row]

    def replace_entries(self, entries: tuple[MixEntry, ...]) -> None:
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
                return entry.name or self.tr("Unknown (0x{0:08X})").format(entry.file_id)
            if column == 1:
                return browser_entry_type_display(
                    entry.file_type or self.tr("Unknown"),
                    entry.name or "",
                )
            if column == 2:
                return format_byte_size(entry.size)
            if column == 3:
                return f"0x{entry.file_id:08X}"
        if role == Qt.ItemDataRole.TextAlignmentRole and column in (2, 3):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.DecorationRole and column == 0:
            return system_icon_for_object(is_directory=False)
        if role == Qt.ItemDataRole.UserRole:
            if column == 0:
                return (entry.name or f"{entry.file_id:08x}").casefold()
            if column == 1:
                return (entry.file_type or "").casefold()
            if column == 2:
                return entry.size
            if column == 3:
                return entry.file_id
        if role == Qt.ItemDataRole.ToolTipRole and column == 0 and entry.name:
            if entry.name_sources:
                sources = "\n".join(entry.name_sources[:4])
                return self.tr("{0}\n\nSource:\n{1}").format(entry.name, sources)
            return entry.name
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
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
            key = lambda entry: (entry.name or f"{entry.file_id:08x}").casefold()
        elif column == 1:
            key = lambda entry: browser_entry_type_display(
                entry.file_type or "",
                entry.name or "",
            ).casefold()
        elif column == 2:
            key = lambda entry: entry.size
        else:
            key = lambda entry: entry.file_id
        self._entries.sort(key=key, reverse=reverse)
        self.layoutChanged.emit()
