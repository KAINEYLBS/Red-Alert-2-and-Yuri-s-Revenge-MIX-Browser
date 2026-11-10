from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QCoreApplication, QProcess, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from mix_browser.features.system_integration.api import (
    SystemIntegrationApplication,
    desktop_launch_command,
)
from mix_browser.features.system_integration.open_with_dialog import (
    is_container_association_probe,
    write_container_association_probe_result,
)
from mix_browser.features.system_integration.preferences import (
    show_container_open_probe_notice,
)
from mix_browser.shared.application_identity import APPLICATION_DISPLAY_NAME
from mix_browser.shared.application_errors import ApplicationApiError
from mix_browser.shared.application_settings import create_application_settings
from mix_browser.shared.application_style import apply_application_style
from mix_browser.shared.interaction_help import InteractionHelpCatalog
from mix_browser.shared.localization import install_translations
from mix_browser.shared.task_progress_dialog import (
    ProgressMode,
    TaskProgressController,
    TaskProgressDialog,
)


def _center_window_on_primary_screen(window: QWidget) -> None:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    window.ensurePolished()
    frame = window.frameGeometry()
    frame.moveCenter(screen.availableGeometry().center())
    window.move(frame.topLeft())


# @arch mix-browser.desktop-entrypoint entrypoint | en: Starts RA2AYRMB and opens paths passed by the operating system | zh: 启动 RA2AYRMB 并打开操作系统传入的路径
def run() -> int:
    if sys.argv[1:2] == ["--progress-helper"]:
        from mix_browser.shared.progress_helper import main as run_progress_helper

        return run_progress_helper()

    startup_paths, qt_arguments = _startup_arguments(sys.argv[1:])
    application = QApplication([sys.argv[0], *qt_arguments])
    settings = create_application_settings()
    ui_language = settings.value("ui/language", "system", type=str)
    install_translations(application, ui_language)
    application.setApplicationName("MIX Browser")
    application.setApplicationDisplayName(APPLICATION_DISPLAY_NAME)
    application.setWindowIcon(
        QIcon(str(Path(__file__).resolve().parents[1] / "data" / "icons" / "MIX-EXE.ico"))
    )
    apply_application_style(application)
    probe_path = next(
        (path for path in startup_paths if is_container_association_probe(path)),
        None,
    )
    if probe_path is not None:
        extension = probe_path.suffix.casefold()
        try:
            is_default: bool | None = bool(
                SystemIntegrationApplication()
                .get_state()
                .get("container_file_is_default", {})
                .get(extension)
            )
        except ApplicationApiError:
            is_default = None
        try:
            write_container_association_probe_result(probe_path, is_default)
        except OSError:
            show_container_open_probe_notice(extension, is_default)
        return 0

    from mix_browser.features.browser.window import MixBrowserWindow

    task_executor = ThreadPoolExecutor(
        max_workers=2,
        thread_name_prefix="mix-browser",
    )
    startup_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="mix-browser-startup",
    )
    temporary_directory = TemporaryDirectory(
        prefix="mix-browser-",
        ignore_cleanup_errors=True,
    )
    progress_controller = TaskProgressController(
        application,
        language=ui_language,
    )
    application.aboutToQuit.connect(progress_controller.shutdown)
    progress_controller.start_helper()
    interaction_help = InteractionHelpCatalog()
    try:
        window = MixBrowserWindow(
            task_executor,
            Path(temporary_directory.name),
            startup_executor=startup_executor,
            interaction_help=interaction_help,
            progress_controller=progress_controller,
        )
        window.restart_requested.connect(lambda: _restart_desktop_application(window))
        window.resize(1200, 680)
        _center_window_on_primary_screen(window)
        startup_progress = TaskProgressDialog(
            progress_controller,
            QCoreApplication.translate("TaskProgressDialog", "Preparing Preview"),
            QCoreApplication.translate(
                "TaskProgressDialog",
                "Initializing preview and media playback...",
            ),
            mode=ProgressMode.INDETERMINATE,
            cancel_callback=lambda: None,
            cancelable=False,
            parent=window,
        )
        startup_completed = False

        def complete_startup() -> None:
            nonlocal startup_completed
            if startup_completed:
                return
            startup_completed = True
            try:
                window.preload_entry_preview()
            except Exception as exc:
                startup_progress.finish()
                QMessageBox.critical(
                    None,
                    QCoreApplication.translate(
                        "TaskProgressDialog",
                        "Preview Initialization Failed",
                    ),
                    str(exc),
                )
                application.quit()
                return
            window.show()
            startup_progress.finish()
            QTimer.singleShot(600, window.start_deferred_startup_work)
            QTimer.singleShot(180, window.prompt_missing_game_directory)
            if startup_paths:
                QTimer.singleShot(220, lambda: window.open_paths(startup_paths))

        startup_progress.shown.connect(complete_startup)
        startup_progress.helper_unavailable.connect(complete_startup)
        startup_progress.show()
        QTimer.singleShot(5000, complete_startup)
        return application.exec()
    finally:
        startup_executor.shutdown(wait=True, cancel_futures=True)
        task_executor.shutdown(wait=True, cancel_futures=True)
        progress_controller.shutdown()
        temporary_directory.cleanup()


# @arch mix-browser.restart-desktop-application service | en: Restarts the desktop process while respecting the main window close flow | zh: 遵循主窗口关闭流程重启桌面程序
def _restart_desktop_application(window: MixBrowserWindow) -> None:
    application = QApplication.instance()
    if application is None:
        return

    quit_on_last_window_closed = application.quitOnLastWindowClosed()
    application.setQuitOnLastWindowClosed(False)
    if not window.close():
        application.setQuitOnLastWindowClosed(quit_on_last_window_closed)
        return

    command = desktop_launch_command()
    started, _process_id = QProcess.startDetached(
        command[0],
        [*command[1:], *sys.argv[1:]],
        str(Path.cwd()),
    )
    if started:
        application.quit()
        return

    window.show()
    application.setQuitOnLastWindowClosed(quit_on_last_window_closed)
    QMessageBox.warning(
        window,
        window.tr("Unable to Restart / 无法重启"),
        window.tr(
            "The application could not be restarted. It remains open. / "
            "无法重启应用，当前窗口将继续保持打开。"
        ),
    )


def _startup_arguments(arguments: list[str]) -> tuple[list[Path], list[str]]:
    paths: list[Path] = []
    qt_arguments: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--open-path":
            index += 1
            if index < len(arguments):
                paths.append(Path(arguments[index]))
        elif argument.startswith("--open-path="):
            paths.append(Path(argument.partition("=")[2]))
        else:
            qt_arguments.append(argument)
        index += 1
    return paths, qt_arguments


if __name__ == "__main__":
    raise SystemExit(run())
