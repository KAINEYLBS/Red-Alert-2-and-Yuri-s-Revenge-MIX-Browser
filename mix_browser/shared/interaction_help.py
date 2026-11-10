from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence

# @arch mix-browser.interaction-help-entry model | en: Describes one registered user interaction | zh: 描述一项已注册的用户交互
@dataclass(frozen=True)
class InteractionHelpEntry:
    entry_id: str
    trigger: str
    description: str

    def __post_init__(self) -> None:
        values = (self.entry_id, self.trigger, self.description)
        if any(
            not isinstance(value, str) or not value.strip() or value != value.strip()
            for value in values
        ):
            raise ValueError("Interaction help entries require an ID, trigger, and description.")


# @arch mix-browser.interaction-help-catalog component | en: Owns validated interaction guidance for the desktop application | zh: 管理桌面应用中经过校验的交互说明
class InteractionHelpCatalog:
    def __init__(self) -> None:
        self._entries: dict[str, InteractionHelpEntry] = {}

    def register_gesture(self, entry_id: str, trigger: str, description: str) -> InteractionHelpEntry:
        entry = InteractionHelpEntry(entry_id, trigger, description)
        if entry.entry_id in self._entries:
            raise ValueError(f"Duplicate interaction help ID: {entry.entry_id}")
        self._entries[entry.entry_id] = entry
        return entry

    def create_action(
        self,
        parent,
        *,
        entry_id: str,
        text: str,
        shortcut: QKeySequence.StandardKey | QKeySequence | str,
        description: str,
    ) -> QAction:
        sequence = shortcut if isinstance(shortcut, QKeySequence) else QKeySequence(shortcut)
        action = QAction(text, parent)
        action.setShortcut(sequence)
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.register_gesture(
            entry_id,
            sequence.toString(QKeySequence.SequenceFormat.PortableText),
            description,
        )
        return action

    def entries(self) -> tuple[InteractionHelpEntry, ...]:
        return tuple(self._entries.values())
