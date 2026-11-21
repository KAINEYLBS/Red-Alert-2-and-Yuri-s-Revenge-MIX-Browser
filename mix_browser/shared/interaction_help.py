from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


# @arch mix-browser.interaction-help-entry model | en: Describes one registered user interaction and its help category | zh: 描述一项已登记的用户交互及其帮助类别
@dataclass(frozen=True)
class InteractionHelpEntry:
    entry_id: str
    group: str
    trigger: str
    description: str
    include_in_global_guide: bool

    def __post_init__(self) -> None:
        values = (self.entry_id, self.group, self.trigger, self.description)
        if any(
            not isinstance(value, str) or not value.strip() or value != value.strip()
            for value in values
        ):
            raise ValueError(
                "Interaction help entries require an ID, group, trigger, and description."
            )
        if not isinstance(self.include_in_global_guide, bool):
            raise ValueError("Interaction help scope must be a boolean.")


# @arch mix-browser.interaction-help-catalog component | en: Owns validated interaction guidance for the desktop application | zh: 管理桌面应用中经过校验的交互说明
class InteractionHelpCatalog:
    def __init__(self) -> None:
        self._entries: dict[str, InteractionHelpEntry] = {}

    def register_gesture(
        self,
        entry_id: str,
        trigger: str,
        description: str,
        *,
        group: str,
        include_in_global_guide: bool = True,
    ) -> InteractionHelpEntry:
        entry = InteractionHelpEntry(
            entry_id,
            group,
            trigger,
            description,
            include_in_global_guide,
        )
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
        group: str,
    ) -> QAction:
        sequence = (
            shortcut
            if isinstance(shortcut, QKeySequence)
            else QKeySequence(shortcut)
        )
        action = QAction(text, parent)
        action.setShortcut(sequence)
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.register_gesture(
            entry_id,
            sequence.toString(QKeySequence.SequenceFormat.PortableText),
            description,
            group=group,
        )
        return action

    def entries(
        self,
        *,
        group: str | None = None,
    ) -> tuple[InteractionHelpEntry, ...]:
        entries = tuple(self._entries.values())
        if group is None:
            return tuple(entry for entry in entries if entry.include_in_global_guide)
        return tuple(entry for entry in entries if entry.group == group)


# @arch mix-browser.interaction-help-popup component | en: Shows registered interaction guidance in a rounded, palette-aware popup | zh: 以适配调色板的圆角弹层展示已登记的交互说明
class InteractionHelpPopup(QFrame):
    _PANEL_MARGIN = 4
    _PANEL_RADIUS = 9
    _SHADOW_LAYERS = (
        (4.0, 1),
        (3.5, 1),
        (3.0, 2),
        (2.5, 3),
        (2.0, 4),
        (1.5, 6),
        (1.0, 8),
        (0.5, 8),
        (0.0, 7),
    )

    def __init__(
        self,
        catalog: InteractionHelpCatalog,
        title: str,
        parent: QWidget | None = None,
        *,
        group: str | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setObjectName("InteractionHelpPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedWidth(420)
        self._catalog = catalog
        self._group = group

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 13)
        layout.setSpacing(9)

        self._title = QLabel(title, self)
        self._title.setObjectName("InteractionHelpTitle")
        self._title.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._title)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setObjectName("InteractionHelpScrollArea")
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setMaximumHeight(520)
        self._scroll_area.setAutoFillBackground(False)
        self._scroll_area.viewport().setAutoFillBackground(False)
        self._rows_widget = QWidget(self._scroll_area)
        self._rows_widget.setObjectName("InteractionHelpRows")
        self._rows_widget.setAutoFillBackground(False)
        self._rows_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Minimum,
        )
        self._rows_layout = QGridLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 4, 0)
        self._rows_layout.setHorizontalSpacing(12)
        self._rows_layout.setVerticalSpacing(7)
        self._rows_layout.setColumnMinimumWidth(0, 142)
        self._rows_layout.setColumnStretch(1, 1)
        self._scroll_area.setWidget(self._rows_widget)
        layout.addWidget(self._scroll_area)
        self._refresh_entries()

    def show_below(self, anchor: QWidget, *, align_right: bool = True) -> None:
        self._resize_scroll_area_to_content()
        self.adjustSize()
        anchor_top = anchor.mapToGlobal(QPoint(0, 0))
        anchor_bottom = anchor.mapToGlobal(QPoint(0, anchor.height()))
        screen = QApplication.screenAt(
            anchor.mapToGlobal(anchor.rect().center())
        ) or QApplication.primaryScreen()

        x = (
            anchor_top.x() + anchor.width() - self.width()
            if align_right
            else anchor_top.x()
        )
        y = anchor_bottom.y() + 4
        if screen is not None:
            available = screen.availableGeometry()
            max_x = max(available.left(), available.right() - self.width() + 1)
            max_y = max(available.top(), available.bottom() - self.height() + 1)
            x = min(max(x, available.left()), max_x)
            if y + self.height() - 1 > available.bottom():
                y = anchor_top.y() - self.height() - 4
            y = min(max(y, available.top()), max_y)

        self.move(x, y)
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def _resize_scroll_area_to_content(self) -> None:
        self._rows_layout.activate()
        content_width = max(1, self.width() - 28)
        if self._rows_layout.hasHeightForWidth():
            content_height = self._rows_layout.heightForWidth(content_width)
        else:
            content_height = self._rows_layout.sizeHint().height()
        if content_height < 0:
            content_height = self._rows_layout.sizeHint().height()
        content_height = max(36, content_height + 8)
        self._scroll_area.setFixedHeight(
            min(self._scroll_area.maximumHeight(), content_height)
        )

    def _refresh_entries(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        entries = self._catalog.entries(group=self._group)
        row = 0
        current_group: str | None = None
        for entry in entries:
            if self._group is None and entry.group != current_group:
                current_group = entry.group
                group_label = QLabel(current_group, self._rows_widget)
                group_label.setObjectName("InteractionHelpGroup")
                group_label.setStyleSheet("font-weight: 600;")
                self._rows_layout.addWidget(group_label, row, 0, 1, 2)
                row += 1

            trigger_label = QLabel(entry.trigger, self._rows_widget)
            trigger_label.setObjectName("InteractionHelpTrigger")
            trigger_label.setWordWrap(True)
            trigger_label.setStyleSheet("font-weight: 600;")
            description_label = QLabel(entry.description, self._rows_widget)
            description_label.setObjectName("InteractionHelpDescription")
            description_label.setWordWrap(True)
            self._rows_layout.addWidget(
                trigger_label,
                row,
                0,
                Qt.AlignmentFlag.AlignTop,
            )
            self._rows_layout.addWidget(
                description_label,
                row,
                1,
                Qt.AlignmentFlag.AlignTop,
            )
            row += 1

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_Clear
        )
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver
        )

        panel = QRectF(self.rect()).adjusted(
            self._PANEL_MARGIN,
            self._PANEL_MARGIN,
            -self._PANEL_MARGIN,
            -self._PANEL_MARGIN,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        for spread, alpha in self._SHADOW_LAYERS:
            shadow_rect = panel.adjusted(
                -spread,
                1,
                spread,
                spread + 1,
            )
            radius = self._PANEL_RADIUS + spread
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(shadow_rect, radius, radius)

        panel_color = self.palette().color(QPalette.ColorRole.Window)
        border_color = self.palette().color(QPalette.ColorRole.Mid)
        painter.setBrush(panel_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawRoundedRect(panel, self._PANEL_RADIUS, self._PANEL_RADIUS)
        painter.end()


# @arch mix-browser.interaction-help-button component | en: Opens registered interaction guidance from a question-mark button | zh: 通过问号按钮打开已登记的交互说明
class InteractionHelpButton(QToolButton):
    def __init__(
        self,
        catalog: InteractionHelpCatalog,
        title: str,
        parent: QWidget | None = None,
        *,
        group: str | None = None,
        size: int = 22,
        align_popup_right: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InteractionHelpButton")
        self.setText("?")
        self.setAutoRaise(True)
        self.setFixedSize(size, size)
        self.setToolTip(title)
        self.setAccessibleName(title)
        self._popup_align_right = align_popup_right
        self._popup = InteractionHelpPopup(
            catalog,
            title,
            self,
            group=group,
        )
        self.clicked.connect(self.show_help)

    def show_help(self) -> None:
        if self._popup.isVisible():
            self._popup.close()
            return
        self._popup.show_below(
            self,
            align_right=self._popup_align_right,
        )
