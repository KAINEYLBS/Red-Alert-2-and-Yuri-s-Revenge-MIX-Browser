from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from mix_browser.features.archive.type_detection import MIX_CONTAINER_SUFFIXES
from mix_browser.shared.application_identity import APPLICATION_DISPLAY_NAME


# @arch mix-browser.system-integration-preferences component | en: Lets users configure Windows Explorer integration for supported container extensions | zh: 让用户配置受支持容器扩展名的 Windows 资源管理器集成
class SystemIntegrationSettingsPage(QWidget):
    open_container_default_requested = Signal(str)

    def __init__(
        self,
        state: dict[str, object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._initial_state = dict(state)

        layout = QVBoxLayout(self)
        context_group = QGroupBox(self.tr("Windows Explorer"), self)
        context_layout = QVBoxLayout(context_group)
        self.directory_context_menu_checkbox = QCheckBox(
            self.tr('Add "Browse with {0}" to directory menus').format(
                APPLICATION_DISPLAY_NAME
            ),
            context_group,
        )
        self.mix_new_menu_checkbox = QCheckBox(
            self.tr("Add MIX archive to the New menu"),
            context_group,
        )
        self.directory_context_menu_checkbox.setChecked(
            bool(state.get("directory_context_menu"))
        )
        self.mix_new_menu_checkbox.setChecked(bool(state.get("mix_new_menu")))
        context_layout.addWidget(self.directory_context_menu_checkbox)
        context_layout.addWidget(self.mix_new_menu_checkbox)
        layout.addWidget(context_group)

        self.container_tables: dict[str, QTableWidget] = {}
        self.container_context_checks: dict[str, QTableWidgetItem] = {}
        self.container_handler_checks: dict[str, QTableWidgetItem] = {}
        self.container_default_statuses: dict[str, QLabel] = {}
        self.container_default_buttons: dict[str, QPushButton] = {}
        self._pending_probe_extensions: set[str] = set()
        associations_group = QGroupBox(self.tr("Container file integration"), self)
        associations_layout = QVBoxLayout(associations_group)
        association_notice = QLabel(
            self.tr(
                "Choose which container extensions appear in the Windows context "
                "menu and register as open handlers. Windows controls the default app."
            ),
            associations_group,
        )
        association_notice.setWordWrap(True)
        association_notice.setProperty("visualRole", "description")
        associations_layout.addWidget(association_notice)

        bulk_row = QHBoxLayout()
        self.select_all_containers_button = QPushButton(
            self.tr("Select all extensions"), associations_group
        )
        self.clear_all_containers_button = QPushButton(
            self.tr("Clear all extensions"), associations_group
        )
        self.select_all_containers_button.clicked.connect(
            lambda: self._set_all_container_integrations(True)
        )
        self.clear_all_containers_button.clicked.connect(
            lambda: self._set_all_container_integrations(False)
        )
        bulk_row.addWidget(self.select_all_containers_button)
        bulk_row.addWidget(self.clear_all_containers_button)
        bulk_row.addStretch(1)
        associations_layout.addLayout(bulk_row)

        self._container_state = dict(state)
        extensions_widget = QWidget(associations_group)
        extensions_layout = QVBoxLayout(extensions_widget)
        extensions_layout.setContentsMargins(0, 0, 0, 0)
        context_states = state.get("container_file_context_menus", {})
        handler_states = state.get("container_file_associations", {})
        for extension in sorted(MIX_CONTAINER_SUFFIXES):
            extension_group = QGroupBox(extension, extensions_widget)
            extension_layout = QVBoxLayout(extension_group)
            extension_buttons = QHBoxLayout()
            select_extension_button = QPushButton(
                self.tr("Select all for {0}").format(extension), extension_group
            )
            clear_extension_button = QPushButton(
                self.tr("Clear {0}").format(extension), extension_group
            )
            select_extension_button.clicked.connect(
                lambda _checked=False, suffix=extension: self._set_extension_integrations(
                    suffix, True
                )
            )
            clear_extension_button.clicked.connect(
                lambda _checked=False, suffix=extension: self._set_extension_integrations(
                    suffix, False
                )
            )
            extension_buttons.addWidget(select_extension_button)
            extension_buttons.addWidget(clear_extension_button)
            extension_buttons.addStretch(1)
            extension_layout.addLayout(extension_buttons)

            table = QTableWidget(2, 4, extension_group)
            table.setHorizontalHeaderLabels(
                [
                    self.tr("Integration"),
                    self.tr("Registered"),
                    self.tr("Windows default"),
                    self.tr("Action"),
                ]
            )
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Fixed
            )
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.Stretch
            )
            table.horizontalHeader().setSectionResizeMode(
                1, QHeaderView.ResizeMode.ResizeToContents
            )
            table.horizontalHeader().setSectionResizeMode(
                2, QHeaderView.ResizeMode.Stretch
            )
            table.horizontalHeader().setSectionResizeMode(
                3, QHeaderView.ResizeMode.ResizeToContents
            )
            table.setItem(0, 0, QTableWidgetItem(self.tr("Browse in context menu")))
            table.setItem(1, 0, QTableWidgetItem(self.tr("Open file handler")))
            context_item = QTableWidgetItem()
            context_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            )
            context_item.setCheckState(
                Qt.CheckState.Checked
                if bool(context_states.get(extension, False))
                else Qt.CheckState.Unchecked
            )
            handler_item = QTableWidgetItem()
            handler_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            )
            handler_item.setCheckState(
                Qt.CheckState.Checked
                if bool(handler_states.get(extension, False))
                else Qt.CheckState.Unchecked
            )
            table.setItem(0, 1, context_item)
            table.setItem(1, 1, handler_item)
            table.setCellWidget(
                0,
                2,
                QLabel(self.tr("Not applicable"), table),
            )
            default_status = QLabel(
                self._container_default_status(extension, state), table
            )
            default_status.setWordWrap(True)
            default_status.setToolTip(default_status.text())
            table.setCellWidget(1, 2, default_status)
            default_button = QPushButton(
                self.tr("Open sample..."), table
            )
            default_button.clicked.connect(
                lambda _checked=False, suffix=extension: self.open_container_default_requested.emit(
                    suffix
                )
            )
            default_button.setEnabled(
                bool(state.get("supported"))
                and bool(handler_states.get(extension, False))
            )
            table.setCellWidget(1, 3, default_button)
            table.setCellWidget(0, 3, QWidget(table))
            table.itemChanged.connect(
                lambda _item, suffix=extension: self._refresh_container_default_button(
                    suffix
                )
            )
            for row in range(table.rowCount()):
                table.setRowHeight(row, 48)
            table.setFixedHeight(
                table.horizontalHeader().sizeHint().height()
                + table.rowHeight(0)
                + table.rowHeight(1)
                + 2 * table.frameWidth()
            )
            extension_layout.addWidget(table)
            extension_group.setEnabled(bool(state.get("supported")))
            extensions_layout.addWidget(extension_group)
            self.container_tables[extension] = table
            self.container_context_checks[extension] = context_item
            self.container_handler_checks[extension] = handler_item
            self.container_default_statuses[extension] = default_status
            self.container_default_buttons[extension] = default_button
        associations_scroll = QScrollArea(associations_group)
        associations_scroll.setWidgetResizable(True)
        associations_scroll.setWidget(extensions_widget)
        associations_layout.addWidget(associations_scroll, 1)
        layout.addWidget(associations_group, 1)

        if not bool(state.get("supported")):
            self.platform_notice = QLabel(self)
            self.platform_notice.setWordWrap(True)
            self.platform_notice.setText(
                self.tr("Windows shell integration is only available on Windows.")
            )
            for checkbox in (
                self.directory_context_menu_checkbox,
                self.mix_new_menu_checkbox,
            ):
                checkbox.setEnabled(False)
            for table in self.container_tables.values():
                table.setEnabled(False)
            self.select_all_containers_button.setEnabled(False)
            self.clear_all_containers_button.setEnabled(False)
            layout.addWidget(self.platform_notice)

    def _container_default_status(
        self,
        extension: str,
        state: dict[str, object],
    ) -> str:
        is_default = bool(
            state.get("container_file_is_default", {}).get(extension, False)
        )
        is_registered = bool(
            state.get("container_file_associations", {}).get(extension, False)
        )
        if is_default and not is_registered:
            return self.tr(
                "Windows still selects {0} for {1}, but its handler is unregistered."
            ).format(APPLICATION_DISPLAY_NAME, extension)
        if is_default:
            return self.tr("{0} is the current default for {1}.").format(
                APPLICATION_DISPLAY_NAME,
                extension,
            )
        if is_registered:
            return self.tr(
                "{0} is available for {1}; Windows uses another default or asks."
            ).format(APPLICATION_DISPLAY_NAME, extension)
        return self.tr("Windows controls which application opens {0}.").format(
            extension
        )

    def _refresh_container_default_button(self, extension: str) -> None:
        table = self.container_tables[extension]
        handler_enabled = (
            table.item(1, 1).checkState() == Qt.CheckState.Checked
        )
        self.container_default_buttons[extension].setEnabled(
            bool(self._container_state.get("supported"))
            and handler_enabled
            and extension not in self._pending_probe_extensions
        )

    def _set_extension_integrations(self, extension: str, enabled: bool) -> None:
        table = self.container_tables[extension]
        table.blockSignals(True)
        try:
            state = Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
            self.container_context_checks[extension].setCheckState(state)
            self.container_handler_checks[extension].setCheckState(state)
        finally:
            table.blockSignals(False)
        self._refresh_container_default_button(extension)

    def _set_all_container_integrations(self, enabled: bool) -> None:
        for extension in self.container_tables:
            self._set_extension_integrations(extension, enabled)

    def registrations(self) -> dict[str, object]:
        return {
            "directory_context_menu": self.directory_context_menu_checkbox.isChecked(),
            "mix_new_menu": self.mix_new_menu_checkbox.isChecked(),
            "container_file_context_menus": {
                extension: item.checkState() == Qt.CheckState.Checked
                for extension, item in self.container_context_checks.items()
            },
            "container_file_associations": {
                extension: item.checkState() == Qt.CheckState.Checked
                for extension, item in self.container_handler_checks.items()
            },
        }

    @property
    def initial_state(self) -> dict[str, object]:
        return dict(self._initial_state)

    def update_container_file_state(
        self,
        extension: str,
        state: dict[str, object],
    ) -> None:
        self._container_state.update(state)
        handler_states = state.get("container_file_associations", {})
        context_states = state.get("container_file_context_menus", {})
        if extension in self.container_handler_checks:
            self.container_handler_checks[extension].setCheckState(
                Qt.CheckState.Checked
                if handler_states.get(extension, False)
                else Qt.CheckState.Unchecked
            )
        if extension in self.container_context_checks:
            self.container_context_checks[extension].setCheckState(
                Qt.CheckState.Checked
                if context_states.get(extension, False)
                else Qt.CheckState.Unchecked
            )
        self.container_default_statuses[extension].setText(
            self._container_default_status(extension, self._container_state)
        )
        self.container_default_statuses[extension].setToolTip(
            self.container_default_statuses[extension].text()
        )
        self._refresh_container_default_button(extension)
        for key in (
            "container_file_associations",
            "container_file_context_menus",
            "container_file_is_default",
        ):
            self._initial_state[key] = dict(state.get(key, {}))

    def set_probe_result(
        self,
        extension: str,
        result: str,
        error: str | None = None,
    ) -> None:
        status = self.container_default_statuses.get(extension)
        if status is None:
            return
        if result == "default":
            text = self.tr("Windows reports {0} as the default for {1}.").format(
                APPLICATION_DISPLAY_NAME,
                extension,
            )
            color = "#1a7f37"
        elif result == "received":
            text = self.tr(
                "Request received. If {0} files are not associated with this app, "
                "change the default app in a {0} file's Properties."
            ).format(extension)
            color = "#0969da"
        elif result == "error":
            text = self.tr("Could not open the {0} sample.").format(extension)
            color = "#cf222e"
        elif result == "timeout":
            text = self.tr("No result received for {0}. You can try again.").format(
                extension
            )
            color = "#b45309"
        else:
            text = self.tr(
                "Request received. If {0} files are not associated with this app, "
                "change the default app in a {0} file's Properties."
            ).format(
                extension
            )
            color = "#0969da"
        status.setText(text)
        status.setToolTip(
            f"{text}\n{error or self.tr('Unknown error')}"
            if result == "error"
            else text
        )
        status.setStyleSheet(f"color: {color}; font-weight: 600;")
        self._pending_probe_extensions.discard(extension)
        for suffix in self.container_default_buttons:
            self._refresh_container_default_button(suffix)

    def set_probe_pending(self, extension: str) -> None:
        status = self.container_default_statuses.get(extension)
        if status is None:
            return
        self._pending_probe_extensions.add(extension)
        text = self.tr("Waiting for the Windows result...")
        status.setText(text)
        status.setToolTip(text)
        status.setStyleSheet("color: #0969da; font-weight: 600;")
        for suffix in self.container_default_buttons:
            self._refresh_container_default_button(suffix)


# @arch mix-browser.new-handler-setup-dialog component | en: Lets users selectively open reusable samples for changed container handlers and shows Windows results inline | zh: 让用户为已变更的容器处理程序选择性打开可复用样例，并在窗口内显示 Windows 结果
class ContainerDefaultHandlerDialog(QDialog):
    open_sample_requested = Signal(str)

    def __init__(
        self,
        extensions: tuple[str, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Windows Default App Setup"))
        self.resize(720, 440)
        self._statuses: dict[str, QLabel] = {}
        self._buttons: dict[str, QPushButton] = {}
        self._pending_extensions: set[str] = set()

        layout = QVBoxLayout(self)
        notice = QLabel(
            self.tr(
                "Windows security restrictions prevent apps from setting file "
                "defaults automatically. Open a sample for each extension you want "
                "to configure, then choose an app in Windows if prompted."
            ),
            self,
        )
        notice.setWordWrap(True)
        notice.setProperty("visualRole", "description")
        layout.addWidget(notice)

        self.table = QTableWidget(len(extensions), 3, self)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Extension"), self.tr("Result"), self.tr("Action")]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        for row, extension in enumerate(extensions):
            self.table.setItem(row, 0, QTableWidgetItem(extension))
            status = QLabel(self.tr("Not triggered"), self.table)
            status.setWordWrap(True)
            self._set_status_style(status, "neutral")
            self.table.setCellWidget(row, 1, status)
            button = QPushButton(self.tr("Open sample..."), self.table)
            button.clicked.connect(
                lambda _checked=False, suffix=extension: self._request_sample(suffix)
            )
            self.table.setCellWidget(row, 2, button)
            self.table.setRowHeight(row, 48)
            self._statuses[extension] = status
            self._buttons[extension] = button
        self.table.setMinimumHeight(min(320, max(120, len(extensions) * 48 + 30)))
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _request_sample(self, extension: str) -> None:
        if extension in self._pending_extensions:
            return
        self._pending_extensions.add(extension)
        status = self._statuses[extension]
        status.setText(self.tr("Waiting for the Windows result..."))
        self._set_status_style(status, "pending")
        self._buttons[extension].setEnabled(False)
        self.open_sample_requested.emit(extension)

    def set_probe_result(
        self,
        extension: str,
        result: str,
        error: str | None = None,
    ) -> None:
        status = self._statuses.get(extension)
        if status is None:
            return
        if result == "pending":
            text = self.tr("Waiting for the Windows result...")
            role = "pending"
        elif result == "default":
            text = self.tr("Windows reports {0} as the current default.").format(
                extension
            )
            role = "success"
        elif result == "received":
            text = self.tr(
                "Request received. If {0} files are not associated with this app, "
                "change the default app in a {0} file's Properties."
            ).format(extension)
            role = "info"
        elif result == "error":
            text = self.tr("Could not open sample.")
            role = "error"
        elif result == "timeout":
            text = self.tr("No result received. You can try again.")
            role = "warning"
        else:
            text = self.tr(
                "Request received. If {0} files are not associated with this app, "
                "change the default app in a {0} file's Properties."
            ).format(extension)
            role = "info"
        status.setText(text)
        status.setToolTip(
            f"{text}\n{error or self.tr('Unknown error')}"
            if result == "error"
            else text
        )
        self._set_status_style(status, role)
        self._pending_extensions.discard(extension)
        self._buttons[extension].setEnabled(True)

    @staticmethod
    def _set_status_style(label: QLabel, role: str) -> None:
        colors = {
            "neutral": "#8c959f",
            "pending": "#0969da",
            "info": "#0969da",
            "success": "#1a7f37",
            "warning": "#b45309",
            "error": "#cf222e",
        }
        label.setStyleSheet(f"color: {colors[role]}; font-weight: 600;")


# @arch mix-browser.container-association-probe-notice component | en: Reports whether Windows selected RA2AYRMB as the default for a container extension | zh: 报告 Windows 是否已将 RA2AYRMB 设为容器扩展名的默认程序
def show_container_open_probe_notice(
    extension: str,
    is_default: bool | None,
) -> None:
    context = "SystemIntegrationSettingsPage"
    if is_default is True:
        message = QApplication.translate(
            context,
            "Windows reports {0} as the current default for {1} files.",
        )
    elif is_default is False:
        message = QApplication.translate(
            context,
            "{0} received the sample-open request. If {1} files are not associated with {0}, change the default app in a {1} file's Properties.",
        )
    else:
        message = QApplication.translate(
            context,
            "{0} received the sample-open request. If {1} files are not associated with {0}, change the default app in a {1} file's Properties.",
        )
    QMessageBox.information(
        None,
        QApplication.translate(context, "Container File Association"),
        message.format(APPLICATION_DISPLAY_NAME, extension),
    )
