from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from mix_browser.features.browser.temporary_files import TemporaryFileCleanupResult


# @arch mix-browser.temporary-files-preferences component | en: Shows the runtime temporary-file count and exposes cleanup and folder actions | zh: 显示运行期临时文件数量并提供清理和打开目录操作
class TemporaryFilesSettingsPage(QWidget):
    refresh_requested = Signal()
    clean_requested = Signal()
    open_folder_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._file_count: int | None = None

        group = QGroupBox(self.tr("Application Temporary Files"), self)
        layout = QVBoxLayout(group)
        self.status_label = QLabel(self.tr("Counting temporary files..."), group)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.refresh_button = QPushButton(self.tr("Refresh Count"), group)
        self.open_folder_button = QPushButton(self.tr("Open Temporary Folder"), group)
        self.clean_button = QPushButton(self.tr("Clean Temporary Files"), group)
        self.clean_button.setEnabled(False)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.open_folder_button.clicked.connect(self.open_folder_requested.emit)
        self.clean_button.clicked.connect(self.clean_requested.emit)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.open_folder_button)
        buttons.addWidget(self.clean_button)
        layout.addLayout(buttons)

        page_layout = QVBoxLayout(self)
        page_layout.addWidget(group)
        page_layout.addStretch(1)

    def show_counting(self) -> None:
        self._file_count = None
        self.status_label.setText(self.tr("Counting temporary files..."))
        self.refresh_button.setEnabled(False)
        self.clean_button.setEnabled(False)

    def show_count_result(self, count: int) -> None:
        self._file_count = count
        if count:
            self.status_label.setText(self.tr("Temporary files: {0}").format(count))
        else:
            self.status_label.setText(self.tr("No temporary files."))
        self.refresh_button.setEnabled(True)
        self.clean_button.setEnabled(count > 0)

    def show_count_error(self, error: str) -> None:
        self._file_count = None
        self.status_label.setText(
            self.tr("Could not count temporary files: {0}").format(error)
        )
        self.refresh_button.setEnabled(True)
        self.clean_button.setEnabled(False)

    def show_cleaning(self) -> None:
        self._file_count = None
        self.status_label.setText(self.tr("Cleaning temporary files..."))
        self.refresh_button.setEnabled(False)
        self.clean_button.setEnabled(False)

    def show_cleanup_result(self, result: TemporaryFileCleanupResult) -> None:
        self._file_count = result.remaining_files
        if result.failed_entries:
            self.status_label.setText(
                self.tr(
                    "Removed {0} files; {1} remain, and some items could not be removed."
                ).format(result.removed_files, result.remaining_files)
            )
        elif result.remaining_files:
            self.status_label.setText(
                self.tr("Removed {0} files; {1} remain.").format(
                    result.removed_files,
                    result.remaining_files,
                )
            )
        else:
            self.status_label.setText(
                self.tr("Removed {0} temporary files.").format(result.removed_files)
            )
        self.refresh_button.setEnabled(True)
        self.clean_button.setEnabled(result.remaining_files > 0)

    def show_cleanup_error(self, error: str) -> None:
        self._file_count = None
        self.status_label.setText(
            self.tr("Could not clean temporary files: {0}").format(error)
        )
        self.refresh_button.setEnabled(True)
        self.clean_button.setEnabled(False)

    @property
    def file_count(self) -> int | None:
        return self._file_count
