from __future__ import annotations

import json
import os
import sys
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from mix_browser.shared.application_style import apply_application_style
from mix_browser.shared.localization import install_translations


# @arch mix-browser.progress-helper-window component | en: Shows one task in a taskbar-free tool window | zh: 使用不显示在任务栏的工具窗口显示单项任务进度
class _TaskProgressWindow(QDialog):
    cancel_requested = Signal(str)
    task_hidden = Signal(str)

    def __init__(self, task_id: str) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._task_id = task_id
        self._cancelable = False
        self._total: int | None = None
        self.setObjectName("taskProgressSurface")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedWidth(400)
        self.setStyleSheet(
            "QDialog#taskProgressSurface {"
            "background: palette(window);"
            "border: 1px solid palette(mid);"
            "border-radius: 8px;"
            "}"
            "QLabel#taskProgressTitle { font-weight: 600; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)
        self._title_label = QLabel(self)
        self._title_label.setObjectName("taskProgressTitle")
        self._message_label = QLabel(self)
        self._message_label.setWordWrap(True)
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setTextVisible(False)
        self._detail_label = QLabel(self)
        self._detail_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._detail_label.setStyleSheet("color: palette(mid); font-size: 9pt;")
        self._cancel_button = QPushButton(
            QCoreApplication.translate("TaskProgressDialog", "Cancel"),
            self,
        )
        self._cancel_button.clicked.connect(self._request_cancel)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self._cancel_button)
        layout.addWidget(self._title_label)
        layout.addWidget(self._message_label)
        layout.addWidget(self._progress_bar)
        layout.addWidget(self._detail_label)
        layout.addLayout(button_row)

        self._finish_timer = QTimer(self)
        self._finish_timer.setSingleShot(True)
        self._finish_timer.timeout.connect(self._hide_finished_task)

    def show_task(self, command: dict[str, Any]) -> None:
        self._finish_timer.stop()
        self._cancelable = bool(command.get("cancelable", True))
        self._cancel_button.setEnabled(self._cancelable)
        self._cancel_button.setVisible(self._cancelable)
        self._cancel_button.setText(
            QCoreApplication.translate("TaskProgressDialog", "Cancel")
        )
        title = str(command.get("title", ""))
        self.setWindowTitle(title)
        self._title_label.setText(title)
        self._message_label.setText(str(command.get("message", "")))
        self._set_progress(command)
        self.adjustSize()
        self._move_near_parent(command.get("position"))
        self.show()
        self.raise_()
        self.activateWindow()

    def update_task(self, command: dict[str, Any]) -> None:
        if command.get("task_id") != self._task_id:
            return
        if "title" in command:
            self._title_label.setText(str(command["title"]))
        if "message" in command:
            self._message_label.setText(str(command["message"]))
        if "cancelable" in command:
            self._cancelable = bool(command["cancelable"])
            self._cancel_button.setVisible(self._cancelable)
            self._cancel_button.setEnabled(self._cancelable)
        if command.get("cancelling"):
            self._cancel_button.setText(
                QCoreApplication.translate("TaskProgressDialog", "Cancelling...")
            )
        if "mode" in command:
            self._set_progress(command)
        elif "completed" in command and self._total is not None:
            completed = int(command["completed"])
            self._progress_bar.setValue(
                min(1000, max(0, completed * 1000 // self._total))
            )
            self._set_detail(command.get("detail"), completed, self._total)
        self.adjustSize()

    def finish_task(self, command: dict[str, Any]) -> None:
        if command.get("task_id") != self._task_id:
            return
        self._cancelable = False
        self._cancel_button.setEnabled(False)
        self._cancel_button.hide()
        if command.get("message"):
            self._message_label.setText(str(command["message"]))
        self.adjustSize()
        self._finish_timer.start(max(0, int(command.get("dismiss_delay_ms", 0))))

    def closeEvent(self, event) -> None:
        if self._cancelable:
            self._request_cancel()
        event.ignore()

    def reject(self) -> None:
        self._request_cancel()

    def _set_progress(self, command: dict[str, Any]) -> None:
        mode = str(command.get("mode", "indeterminate"))
        if mode == "none":
            self._progress_bar.hide()
            self._detail_label.hide()
            self._total = None
            return
        self._progress_bar.show()
        if mode == "indeterminate":
            self._progress_bar.setRange(0, 0)
            self._detail_label.hide()
            self._total = None
            return
        total = command.get("total")
        if not isinstance(total, int) or total <= 0:
            self._progress_bar.setRange(0, 0)
            self._detail_label.hide()
            self._total = None
            return
        self._total = total
        self._progress_bar.setRange(0, 1000)
        completed = int(command.get("completed", 0))
        self._progress_bar.setValue(
            min(1000, max(0, completed * 1000 // total))
        )
        self._detail_label.show()
        self._set_detail(command.get("detail"), completed, total)

    def _set_detail(self, detail: object, completed: int, total: int) -> None:
        if isinstance(detail, str) and detail:
            self._detail_label.setText(detail)
            return
        percent = min(100.0, max(0.0, completed * 100 / total))
        self._detail_label.setText(
            f"{_format_bytes(completed)} / {_format_bytes(total)} ({percent:.0f}%)"
        )

    def _move_near_parent(self, position: object) -> None:
        if not isinstance(position, dict):
            screen = QApplication.primaryScreen()
            center = screen.availableGeometry().center() if screen else QPoint()
        else:
            center = QPoint(int(position.get("x", 0)), int(position.get("y", 0)))
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRect(0, 0, 1024, 768)
        x = min(
            max(center.x() - self.width() // 2, available.left()),
            available.right() - self.width() + 1,
        )
        y = min(
            max(center.y() - self.height() // 2, available.top()),
            available.bottom() - self.height() + 1,
        )
        self.move(x, y)

    def _request_cancel(self) -> None:
        if not self._cancelable:
            return
        self._cancelable = False
        self._cancel_button.setEnabled(False)
        self._cancel_button.setText(
            QCoreApplication.translate("TaskProgressDialog", "Cancelling...")
        )
        self.cancel_requested.emit(self._task_id)

    def _hide_finished_task(self) -> None:
        self.hide()
        self.task_hidden.emit(self._task_id)


# @arch mix-browser.progress-helper-controller component | en: Receives progress commands and manages task windows in the helper process | zh: 在辅助进程中接收进度命令并管理各任务窗口
class _ProgressHelper(QObject):
    def __init__(self, application: QApplication, socket: QLocalSocket) -> None:
        super().__init__(application)
        self._application = application
        self._socket = socket
        self._buffer = bytearray()
        self._windows: dict[str, _TaskProgressWindow] = {}
        socket.readyRead.connect(self._read_commands)
        socket.disconnected.connect(self._application.quit)

    def _read_commands(self) -> None:
        if self._socket.state() is not QLocalSocket.LocalSocketState.ConnectedState:
            return
        self._buffer.extend(self._socket.readAll().data())
        while b"\n" in self._buffer:
            line, _, remainder = self._buffer.partition(b"\n")
            self._buffer = bytearray(remainder)
            try:
                command = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(command, dict):
                self._handle_command(command)

    def _handle_command(self, command: dict[str, Any]) -> None:
        operation = command.get("command")
        task_id = str(command.get("task_id", ""))
        if operation == "start" and task_id:
            window = self._windows.get(task_id)
            if window is None:
                window = _TaskProgressWindow(task_id)
                window.cancel_requested.connect(self._send_cancel_event)
                window.task_hidden.connect(self._send_hidden_event)
                self._windows[task_id] = window
            display_command = dict(command)
            position = command.get("position")
            if isinstance(position, dict):
                offset = (len(self._windows) - 1) % 5 * 26
                display_command["position"] = {
                    "x": int(position.get("x", 0)) + offset,
                    "y": int(position.get("y", 0)) + offset,
                }
            window.show_task(display_command)
            QTimer.singleShot(0, lambda identifier=task_id: self._send_shown_event(identifier))
        elif operation == "update" and task_id in self._windows:
            self._windows[task_id].update_task(command)
        elif operation == "finish" and task_id in self._windows:
            self._windows[task_id].finish_task(command)
        elif operation == "shutdown":
            for window in self._windows.values():
                window.hide()
            self._windows.clear()
            self._application.quit()

    def _send(self, message: dict[str, object]) -> None:
        if self._socket.state() is QLocalSocket.LocalSocketState.ConnectedState:
            payload = (json.dumps(message, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            self._socket.write(payload)
            self._socket.flush()

    def _send_cancel_event(self, task_id: str) -> None:
        self._send({"event": "cancel", "task_id": task_id})

    def _send_shown_event(self, task_id: str) -> None:
        window = self._windows.get(task_id)
        if window is not None and window.isVisible():
            self._send({"event": "shown", "task_id": task_id})

    def _send_hidden_event(self, task_id: str) -> None:
        self._send({"event": "hidden", "task_id": task_id})
        window = self._windows.pop(task_id, None)
        if window is not None:
            window.deleteLater()


def _format_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"


def main() -> int:  # @arch mix-browser.progress-helper-entrypoint entrypoint | en: Runs the standalone progress window process | zh: 运行独立进度窗口进程
    server_name = os.environ.get("RA2AYRMB_PROGRESS_SERVER", "")
    if not server_name:
        return 2
    application = QApplication(sys.argv[:1])
    application.setApplicationName("RA2AYRMB Progress")
    application.setOrganizationName("RA2AYRMB")
    application.setQuitOnLastWindowClosed(False)
    install_translations(
        application,
        os.environ.get("RA2AYRMB_PROGRESS_LANGUAGE", "system"),
    )
    apply_application_style(application)
    socket = QLocalSocket(application)
    helper = _ProgressHelper(application, socket)
    socket.connectToServer(server_name)
    if not socket.waitForConnected(3000):
        return 3
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
