from __future__ import annotations

from html import escape

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QCursor, QHelpEvent, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QToolTip,
    QTreeView,
    QWidget,
)

from mix_browser.shared.semantic_colors import refresh_semantic_status_style
from mix_browser.shared.table_row_delegate import ApplicationTableRowDelegate


BROWSER_TOOLBAR_CONTROL_HEIGHT = 28


_APPLICATION_TABLE_POLICY_PROPERTY = "_ra2ayrmbTableInteractionPolicyInstalled"
_TABLE_VIEWPORT_POLICY_PROPERTY = "_ra2ayrmbTableViewportPolicyInstalled"
_TABLE_VIEW_POLICY_PROPERTY = "_ra2ayrmbTableViewPolicyApplied"
_TABLE_HEADER_FILL_PENDING_PROPERTY = "_ra2ayrmbHeaderFillPending"


# @arch mix-browser.application-table-interaction-policy utility | en: Applies row selection, resizable filled headers, and delegate-aware cell tooltips to application table and tree views | zh: 统一应用内表格和树形视图的整行选中、铺满且可调的表头与委托提示
class _ApplicationTableInteractionPolicy(QObject):
    def eventFilter(self, watched, event) -> bool:
        if (
            isinstance(watched, QWidget)
            and event.type()
            in {
                QEvent.Type.PaletteChange,
                QEvent.Type.ApplicationPaletteChange,
            }
        ):
            refresh_semantic_status_style(watched)

        if (
            event.type() == QEvent.Type.Enter
            and isinstance(watched, QWidget)
        ):
            self._update_cell_widget_hover(watched)

        if (
            isinstance(watched, (QTableView, QTreeView))
            and event.type() == QEvent.Type.Show
        ):
            watched.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
            watched.setMouseTracking(True)
            viewport = watched.viewport()
            viewport.setMouseTracking(True)
            if not viewport.property(_TABLE_VIEWPORT_POLICY_PROPERTY):
                viewport.setToolTip(" ")
                viewport.installEventFilter(self)
                viewport.setProperty(_TABLE_VIEWPORT_POLICY_PROPERTY, True)
            header = (
                watched.horizontalHeader()
                if isinstance(watched, QTableView)
                else watched.header()
            )
            header.setStretchLastSection(False)
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            if not watched.property(_TABLE_VIEW_POLICY_PROPERTY):
                delegate = watched.itemDelegate()
                if type(delegate) is QStyledItemDelegate:
                    watched.setItemDelegate(ApplicationTableRowDelegate(watched))
                watched.setProperty(_TABLE_VIEW_POLICY_PROPERTY, True)
                self._fill_header(watched)
            return False

        if (
            event.type() == QEvent.Type.Resize
            and isinstance(watched, QWidget)
            and watched.property(_TABLE_VIEWPORT_POLICY_PROPERTY)
        ):
            parent = watched.parentWidget()
            if (
                isinstance(parent, (QTableView, QTreeView))
                and parent.viewport() is watched
            ):
                self._schedule_header_fill(parent, watched)

        view = None
        viewport = None
        if isinstance(event, QHelpEvent) and isinstance(watched, QWidget):
            candidate = watched
            while candidate is not None:
                if isinstance(candidate, (QTableView, QTreeView)):
                    candidate_viewport = candidate.viewport()
                    if (
                        watched is candidate
                        or watched is candidate_viewport
                        or candidate_viewport.isAncestorOf(watched)
                    ):
                        view = candidate
                        viewport = candidate_viewport
                    break
                candidate = candidate.parentWidget()
        if view is not None and event.type() == QEvent.Type.ToolTip and isinstance(
            event, QHelpEvent
        ):
            position = viewport.mapFromGlobal(event.globalPos())
            index = view.indexAt(position)
            delegate = view.itemDelegate()
            tooltip_at_position = getattr(
                delegate,
                "tooltip_at_position",
                None,
            )
            value = (
                tooltip_at_position(index, position)
                if index.isValid() and callable(tooltip_at_position)
                else None
            )
            if not value and index.isValid():
                value = index.data(Qt.ItemDataRole.DisplayRole)
            text = "" if value is None else str(value)
            if not text:
                QToolTip.hideText()
            else:
                tooltip = escape(text).replace("\r\n", "\n").replace("\r", "\n")
                tooltip = tooltip.replace("\n", "<br>")
                QToolTip.showText(
                    event.globalPos(),
                    tooltip,
                    viewport,
                    view.visualRect(index),
                )
            return True

        return False

    def _update_cell_widget_hover(self, widget: QWidget) -> None:
        candidate = widget
        while candidate is not None:
            if isinstance(candidate, (QTableView, QTreeView)):
                viewport = candidate.viewport()
                if widget is not viewport and viewport.isAncestorOf(widget):
                    delegate = candidate.itemDelegate()
                    if isinstance(delegate, ApplicationTableRowDelegate):
                        position = viewport.mapFromGlobal(QCursor.pos())
                        index = candidate.indexAt(position)
                        delegate.set_hovered_row(
                            index.row() if index.isValid() else -1
                        )
                return
            candidate = candidate.parentWidget()

    def _fill_header(self, view) -> None:
        header = (
            view.horizontalHeader()
            if isinstance(view, QTableView)
            else view.header()
        )
        sections = [
            section
            for section in range(header.count())
            if not header.isSectionHidden(section)
        ]
        if not sections:
            return

        minimum = max(header.minimumSectionSize(), 1)
        maximum = max(header.maximumSectionSize(), minimum)
        viewport_width = view.viewport().width()
        if viewport_width <= 0:
            return
        target = min(
            max(viewport_width, minimum * len(sections)),
            maximum * len(sections),
        )
        weights = {
            section: max(header.sectionSize(section), 1)
            for section in sections
        }
        widths: dict[int, int] = {}
        active = list(sections)
        remaining = target

        while active:
            weight_total = sum(weights[section] for section in active)
            constrained = []
            for section in active:
                proposed = remaining * weights[section] / weight_total
                if proposed < minimum:
                    widths[section] = minimum
                    constrained.append(section)
                elif proposed > maximum:
                    widths[section] = maximum
                    constrained.append(section)
            if constrained:
                remaining -= sum(widths[section] for section in constrained)
                active = [
                    section for section in active if section not in constrained
                ]
                continue

            raw = {
                section: remaining * weights[section] / weight_total
                for section in active
            }
            for section in active:
                widths[section] = int(raw[section])
            remainder = remaining - sum(widths[section] for section in active)
            for section in sorted(
                active,
                key=lambda item: raw[item] - widths[item],
                reverse=True,
            )[:remainder]:
                widths[section] += 1
            break

        for section in sections:
            header.resizeSection(section, widths[section])

    def _schedule_header_fill(self, view, viewport) -> None:
        if viewport.property(_TABLE_HEADER_FILL_PENDING_PROPERTY):
            return
        viewport.setProperty(_TABLE_HEADER_FILL_PENDING_PROPERTY, True)
        QTimer.singleShot(
            0,
            lambda view=view, viewport=viewport: self._apply_scheduled_header_fill(
                view, viewport
            ),
        )

    def _apply_scheduled_header_fill(self, view, viewport) -> None:
        try:
            viewport.setProperty(_TABLE_HEADER_FILL_PENDING_PROPERTY, False)
            if view.viewport() is viewport:
                self._fill_header(view)
        except RuntimeError:
            return


# @arch mix-browser.application-visual-style utility | en: Applies shared application-wide control and section hierarchy styles | zh: 应用统一的控件样式与分组层级
def apply_application_style(application: QApplication) -> None:
    """Install application-wide table interactions and shared control styles."""
    if not application.property(_APPLICATION_TABLE_POLICY_PROPERTY):
        policy = _ApplicationTableInteractionPolicy(application)
        application.installEventFilter(policy)
        application.setProperty(_APPLICATION_TABLE_POLICY_PROPERTY, True)

    palette = application.palette()
    button_background = palette.color(QPalette.ColorRole.Button).name()
    button_text = palette.color(QPalette.ColorRole.ButtonText).name()
    normal_border = palette.color(QPalette.ColorRole.Mid).name()
    hover_background = palette.color(QPalette.ColorRole.Midlight).name()
    active_border = palette.color(QPalette.ColorRole.Highlight).name()
    active_text = palette.color(QPalette.ColorRole.HighlightedText).name()
    pressed_background = palette.color(QPalette.ColorRole.Dark).name()
    disabled_background = palette.color(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Button,
    ).name()
    disabled_text = palette.color(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
    ).name()
    disabled_border = palette.color(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Mid,
    ).name()
    description_text = palette.color(QPalette.ColorRole.PlaceholderText).name()
    application.setStyleSheet(
        f"""
        QPushButton, QToolButton {{
            color: {button_text};
            background-color: {button_background};
            border: 1px solid {normal_border};
            border-radius: 4px;
            padding: 4px 9px;
        }}
        QToolButton {{
            padding: 3px 6px;
        }}
        QToolButton[menuButton="true"] {{
            padding: 3px 18px 3px 6px;
        }}
        QToolButton#ClearSortButton, QToolButton#InteractionHelpButton {{
            background-color: transparent;
            border: none;
            padding: 0px;
        }}
        QToolButton#ClearSortButton:hover,
        QToolButton#InteractionHelpButton:hover {{
            background-color: {hover_background};
        }}
        QPushButton:hover, QToolButton:hover,
        QPushButton:focus, QToolButton:focus {{
            background-color: {hover_background};
            border-color: {active_border};
        }}
        QPushButton:pressed, QToolButton:pressed {{
            background-color: {pressed_background};
            border-color: {active_border};
        }}
        QPushButton:default {{
            border-color: {active_border};
        }}
        QPushButton:disabled, QToolButton:disabled {{
            color: {disabled_text};
            background-color: {disabled_background};
            border-color: {disabled_border};
        }}
        QToolButton#BreadcrumbButton {{
            background-color: transparent;
            border-color: transparent;
            border-bottom-color: {normal_border};
            border-radius: 0px;
            padding: 3px 6px;
        }}
        QToolButton#BreadcrumbButton:hover,
        QToolButton#BreadcrumbButton:focus,
        QToolButton#BreadcrumbButton:pressed {{
            background-color: {hover_background};
            border-color: {active_border};
        }}
        QGroupBox {{
            font-weight: normal;
            border: 1px solid {normal_border};
            border-radius: 4px;
            margin-top: 12px;
            padding: 12px 10px 10px 10px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 8px;
            padding: 0px 4px;
            font-weight: 600;
        }}
        QLabel[visualRole="description"] {{
            color: {description_text};
        }}
        """
    )


# @arch mix-browser.mark-menu-tool-button utility | en: Marks a tool button for the shared application menu-button spacing rule | zh: 标记工具按钮以应用全局菜单按钮间距规则
def mark_menu_tool_button(button: QToolButton) -> None:
    button.setProperty("menuButton", True)
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.updateGeometry()
