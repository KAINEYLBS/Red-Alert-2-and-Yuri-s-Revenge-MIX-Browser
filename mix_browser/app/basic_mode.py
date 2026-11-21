from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from mix_browser.app.api import MixBrowserApplication
from mix_browser.features.system_integration.basic_operations import (
    ShellBasicOperationDialog,
)
from mix_browser.features.system_integration.explorer_selection import (
    ExplorerSelectionError,
    resolve_explorer_selection,
)
from mix_browser.shared.application_identity import APPLICATION_DISPLAY_NAME
from mix_browser.shared.application_settings import create_application_settings
from mix_browser.shared.application_style import apply_application_style
from mix_browser.shared.localization import install_translations
from mix_browser.shared.task_progress_dialog import TaskProgressController


# @arch mix-browser.basic-mode-entrypoint entrypoint | en: Runs file operations from Explorer without importing the full desktop window | zh: 不导入完整桌面窗口，运行资源管理器发起的文件操作
def run_basic_mode(arguments: list[str]) -> int:
    if not arguments:
        return 2
    operation, *raw_paths = arguments
    if operation not in {"pack-copy", "pack-move", "extract-containers"}:
        return 2

    app = QApplication([sys.argv[0]])
    app.setApplicationName("MIX Browser")
    app.setApplicationDisplayName(APPLICATION_DISPLAY_NAME)
    settings = create_application_settings()
    language = settings.value("ui/language", "system", type=str)
    install_translations(app, language)
    apply_application_style(app)
    app.setWindowIcon(
        QIcon(
            str(
                Path(__file__).resolve().parents[1]
                / "data"
                / "icons"
                / "MIX-EXE.ico"
            )
        )
    )
    if not raw_paths:
        QMessageBox.warning(
            None,
            QCoreApplication.translate("ShellBasicOperationDialog", "MIX File Operation"),
            QCoreApplication.translate(
                "ShellBasicOperationDialog",
                "Windows did not pass any selected files to the operation.",
            ),
        )
        return 2

    shell_paths = tuple(Path(raw_path) for raw_path in raw_paths)
    try:
        selected_paths = resolve_explorer_selection(shell_paths)
    except ExplorerSelectionError:
        selected_paths = shell_paths

    progress_controller = TaskProgressController(app, language=language)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mix-shell")
    try:
        dialog = ShellBasicOperationDialog(
            operation,
            selected_paths,
            MixBrowserApplication(
                xcc_names_enabled=False,
                community_names_enabled=False,
            ),
            progress_controller,
            executor,
            settings,
        )
        if dialog.can_run_without_dialog:
            dialog.automatic_operation_finished.connect(app.quit)
            dialog.finished.connect(app.quit)
            QTimer.singleShot(0, dialog.start_without_dialog)
            app.exec()
        else:
            dialog.exec()
        return dialog.result_code
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        progress_controller.shutdown()
