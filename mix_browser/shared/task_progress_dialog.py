from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Callable
from uuid import uuid4

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QProcess,
    QProcessEnvironment,
    Signal,
    Qt,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QRegion
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QWidget


_LOGGER = logging.getLogger(__name__)


class ProgressMode(Enum):
    NONE = "none"
    INDETERMINATE = "indeterminate"
    DETERMINATE = "determinate"


class TaskCancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class _OwnerBlocker:
    owner: QWidget
    blocker: _ProgressBlocker
    task_ids: set[str] = field(default_factory=set)


# @arch mix-browser.progress-blocker component | en: Dims and blocks an owning window during a progress task | zh: 在进度任务期间遮暗并阻止宿主窗口交互
class _ProgressBlocker(QWidget):
    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self._owner = owner
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setGeometry(owner.rect())
        owner.installEventFilter(self)
        self._sync_shape()
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._owner and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            self.setGeometry(self._owner.rect())
            self._sync_shape()
            self.raise_()
        return super().eventFilter(watched, event)

    def event(self, event) -> bool:
        if event.type() in {
            QEvent.Type.ContextMenu,
            QEvent.Type.KeyPress,
            QEvent.Type.KeyRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseMove,
            QEvent.Type.Wheel,
        }:
            event.accept()
            return True
        return super().event(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
        painter.fillPath(path, QColor(0, 0, 0, 88))

    def _sync_shape(self) -> None:
        owner_mask = self._owner.mask()
        if not owner_mask.isEmpty():
            self.setMask(owner_mask)
            return
        self.clearMask()
        rounded = QPainterPath()
        rounded.addRoundedRect(self.rect(), 8, 8)
        self.setMask(QRegion(rounded.toFillPolygon().toPolygon()))


# @arch mix-browser.task-progress-controller component | en: Runs one shared UI helper process for all application progress sessions | zh: 使用一个共享 UI 辅助进程管理应用内所有进度会话
class TaskProgressController(QObject):
    def __init__(self, parent=None, *, language: str = "system") -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )
        self._process.started.connect(self._flush_pending_commands)
        self._process.readyReadStandardError.connect(
            self._read_process_error_output
        )
        self._process.errorOccurred.connect(self._handle_process_error)
        self._process.finished.connect(self._handle_process_finished)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(
            QLocalServer.SocketOption.UserAccessOption
        )
        self._server.newConnection.connect(self._accept_helper_connection)
        self._server_name = f"ra2ayrmb-progress-{uuid4().hex}"
        if not self._server.listen(self._server_name):
            raise RuntimeError(
                f"Unable to create the progress helper IPC endpoint: {self._server.errorString()}"
            )
        self._socket: QLocalSocket | None = None
        self._language = language
        self._pending_commands: list[bytes] = []
        self._socket_output_buffer = bytearray()
        self._error_output_buffer = bytearray()
        self._sessions: dict[str, TaskProgressDialog] = {}
        self._owner_blockers: dict[int, _OwnerBlocker] = {}
        self._task_owner_keys: dict[str, int] = {}
        self._shutting_down = False

    def start_helper(self) -> None:
        if not self._shutting_down:
            self._ensure_helper_process()

    def start(self, session: TaskProgressDialog) -> None:
        if self._shutting_down:
            session._handle_helper_unavailable()
            return
        if session.task_id in self._sessions:
            return
        self._sessions[session.task_id] = session
        self._activate_owner_blocker(session)
        self._ensure_helper_process()
        self._send(
            {
                "command": "start",
                **session._payload(),
                "position": self._parent_center(session._anchor),
            }
        )

    def update(self, session: TaskProgressDialog, command: dict[str, object]) -> None:
        if session.task_id not in self._sessions or not session._active:
            return
        self._send(
            {
                "command": "update",
                "task_id": session.task_id,
                **command,
            }
        )

    def finish(self, session: TaskProgressDialog, *, message: str | None = None) -> None:
        if session.task_id not in self._sessions:
            self._delete_session_later(session)
            return
        session._active = False
        self._send(
            {
                "command": "finish",
                "task_id": session.task_id,
                "message": message or "",
            }
        )

    def abandon(self, task_id: str) -> None:
        session = self._sessions.get(task_id)
        if session is not None and session._active:
            session._active = False
            self._send(
                {
                    "command": "finish",
                    "task_id": task_id,
                    "message": "",
                    "dismiss_delay_ms": 0,
                }
            )

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        for session in tuple(self._sessions.values()):
            session._active = False
        self._sessions.clear()
        self._release_all_owner_blockers()
        if self._process.state() is QProcess.ProcessState.NotRunning:
            self._pending_commands.clear()
            self._close_helper_socket()
            self._server.close()
            QLocalServer.removeServer(self._server_name)
            return
        if (
            self._process.state() is QProcess.ProcessState.Starting
            and not self._process.waitForStarted(2000)
        ):
            self._process.kill()
            self._process.waitForFinished()
            self._pending_commands.clear()
            self._close_helper_socket()
            self._server.close()
            QLocalServer.removeServer(self._server_name)
            return
        self._send({"command": "shutdown"})
        if not self._process.waitForFinished(1500):
            _LOGGER.warning(
                "The progress helper did not stop after shutdown; terminating it."
            )
            self._process.terminate()
            if not self._process.waitForFinished(1000):
                _LOGGER.error(
                    "The progress helper did not stop after termination; killing it."
                )
                self._process.kill()
                self._process.waitForFinished()
        self._close_helper_socket()
        self._server.close()
        QLocalServer.removeServer(self._server_name)

    def _activate_owner_blocker(self, session: TaskProgressDialog) -> None:
        anchor = session._anchor
        if anchor is None:
            anchor = QApplication.activeWindow()
        if anchor is None:
            return
        owner = anchor.window()
        if not owner.isVisible():
            return
        owner_key = id(owner)
        record = self._owner_blockers.get(owner_key)
        if record is None:
            blocker = _ProgressBlocker(owner)
            self._owner_blockers[owner_key] = _OwnerBlocker(owner, blocker)
            owner.destroyed.connect(
                lambda _object=None, key=owner_key: self._forget_owner_blocker(key)
            )
            record = self._owner_blockers[owner_key]
        record.task_ids.add(session.task_id)
        self._task_owner_keys[session.task_id] = owner_key

    def _release_owner_blocker(self, task_id: str) -> None:
        owner_key = self._task_owner_keys.pop(task_id, None)
        if owner_key is None:
            return
        record = self._owner_blockers.get(owner_key)
        if record is None:
            return
        record.task_ids.discard(task_id)
        if not record.task_ids:
            self._remove_owner_blocker(owner_key)

    def _remove_owner_blocker(self, owner_key: int) -> None:
        record = self._owner_blockers.pop(owner_key, None)
        if record is None:
            return
        try:
            record.owner.removeEventFilter(record.blocker)
            record.blocker.hide()
            record.blocker.deleteLater()
        except RuntimeError:
            pass
        for task_id in record.task_ids:
            self._task_owner_keys.pop(task_id, None)

    def _forget_owner_blocker(self, owner_key: int) -> None:
        record = self._owner_blockers.pop(owner_key, None)
        if record is None:
            return
        for task_id in record.task_ids:
            self._task_owner_keys.pop(task_id, None)

    def _release_all_owner_blockers(self) -> None:
        for owner_key in tuple(self._owner_blockers):
            self._remove_owner_blocker(owner_key)
        self._task_owner_keys.clear()

    @staticmethod
    def _delete_session_later(session: TaskProgressDialog) -> None:
        try:
            session.deleteLater()
        except RuntimeError:
            pass

    @staticmethod
    def _parent_center(anchor: QWidget | None) -> dict[str, int] | None:
        if anchor is None or not anchor.isVisible():
            return None
        center = anchor.mapToGlobal(anchor.rect().center())
        return {"x": center.x(), "y": center.y()}

    def _ensure_helper_process(self) -> None:
        if self._process.state() is not QProcess.ProcessState.NotRunning:
            return
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("RA2AYRMB_PROGRESS_LANGUAGE", self._language)
        environment.insert("RA2AYRMB_PROGRESS_SERVER", self._server_name)
        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = ["--progress-helper"]
        else:
            program = sys.executable
            package_root = Path(__file__).resolve().parents[2]
            current_python_path = environment.value("PYTHONPATH")
            python_path = str(package_root)
            if current_python_path:
                python_path = os.pathsep.join((python_path, current_python_path))
            environment.insert("PYTHONPATH", python_path)
            arguments = ["-m", "mix_browser.shared.progress_helper"]
        environment.insert("PYTHONUNBUFFERED", "1")
        self._process.setProcessEnvironment(environment)
        self._process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        process_argument_modifier = getattr(
            self._process,
            "setCreateProcessArgumentsModifier",
            None,
        )
        if os.name == "nt" and callable(process_argument_modifier):
            def hide_console(arguments) -> None:
                arguments.flags |= 0x08000000

            process_argument_modifier(hide_console)
        self._process.start(program, arguments)

    def _send(self, command: dict[str, object]) -> None:
        encoded = (json.dumps(command, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        if (
            self._socket is not None
            and self._socket.state() is QLocalSocket.LocalSocketState.ConnectedState
        ):
            if self._socket.write(encoded) < 0:
                _LOGGER.warning("Unable to send progress command to helper process.")
            else:
                self._socket.flush()
            return
        self._pending_commands.append(encoded)

    def _flush_pending_commands(self) -> None:
        while (
            self._pending_commands
            and self._socket is not None
            and self._socket.state() is QLocalSocket.LocalSocketState.ConnectedState
        ):
            command = self._pending_commands.pop(0)
            if self._socket.write(command) < 0:
                _LOGGER.warning("Unable to send progress command to helper process.")
                break
            self._socket.flush()

    def _accept_helper_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            if self._socket is not None:
                self._close_helper_socket()
            self._socket_output_buffer.clear()
            socket.setParent(self._server)
            socket.readyRead.connect(self._read_process_output)
            socket.disconnected.connect(self._handle_helper_disconnected)
            self._socket = socket
            self._flush_pending_commands()

    def _close_helper_socket(self) -> None:
        socket = self._socket
        self._socket = None
        if socket is None:
            return
        self._socket_output_buffer.clear()
        socket.disconnectFromServer()
        socket.deleteLater()

    def _handle_helper_disconnected(self) -> None:
        socket = self._socket
        if socket is not None and socket.state() is QLocalSocket.LocalSocketState.UnconnectedState:
            self._socket = None
        if not self._shutting_down and self._sessions:
            _LOGGER.warning("The progress helper IPC connection was lost.")
            self._fail_active_sessions()
            self._pending_commands.clear()
            if self._process.state() is not QProcess.ProcessState.NotRunning:
                self._process.terminate()

    def _read_process_error_output(self, *, final: bool = False) -> None:
        self._error_output_buffer.extend(
            self._process.readAllStandardError().data()
        )
        while b"\n" in self._error_output_buffer:
            line, _, remainder = self._error_output_buffer.partition(b"\n")
            self._error_output_buffer = bytearray(remainder)
            message = line.decode("utf-8", errors="replace").rstrip()
            if message:
                _LOGGER.warning("Progress helper stderr: %s", message)
        if final and self._error_output_buffer:
            message = self._error_output_buffer.decode(
                "utf-8", errors="replace"
            ).rstrip()
            self._error_output_buffer.clear()
            if message:
                _LOGGER.warning("Progress helper stderr: %s", message)

    def _read_process_output(self) -> None:
        socket = self._socket
        if socket is None:
            return
        self._socket_output_buffer.extend(socket.readAll().data())
        while b"\n" in self._socket_output_buffer:
            line, _, remainder = self._socket_output_buffer.partition(b"\n")
            self._socket_output_buffer = bytearray(remainder)
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                _LOGGER.warning("The progress helper sent an invalid message.")
                continue
            if not isinstance(message, dict):
                continue
            task_id = str(message.get("task_id", ""))
            session = self._sessions.get(task_id)
            event = message.get("event")
            if event == "cancel" and session is not None:
                session._request_cancel()
            elif event == "shown" and session is not None:
                session._handle_helper_shown()
            elif event == "hidden":
                self._release_owner_blocker(task_id)
                self._sessions.pop(task_id, None)
                if session is not None:
                    self._delete_session_later(session)

    def _handle_process_error(self, error: QProcess.ProcessError) -> None:
        _LOGGER.warning(
            "The progress helper process failed (%s): %s",
            error.name,
            self._process.errorString(),
        )
        if error is QProcess.ProcessError.FailedToStart:
            self._fail_active_sessions()
            self._pending_commands.clear()

    def _handle_process_finished(self, exit_code: int, _exit_status) -> None:
        self._read_process_error_output(final=True)
        if exit_code != 0:
            _LOGGER.warning(
                "The progress helper process exited with code %s.", exit_code
            )
        self._fail_active_sessions()
        self._pending_commands.clear()
        self._close_helper_socket()

    def _fail_active_sessions(self) -> None:
        for task_id, session in tuple(self._sessions.items()):
            self._release_owner_blocker(task_id)
            session._handle_helper_unavailable()
            self._sessions.pop(task_id, None)


# @arch mix-browser.task-progress-dialog component | en: Sends a task's progress and cancellation state to the shared UI helper process | zh: 将单项任务的进度与取消状态发送到共享 UI 辅助进程
class TaskProgressDialog(QObject):
    shown = Signal()
    helper_unavailable = Signal()

    def __init__(
        self,
        controller: TaskProgressController,
        title: str,
        message: str,
        *,
        mode: ProgressMode,
        cancel_callback: Callable[[], None],
        cancelable: bool = True,
        total: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent if isinstance(parent, QObject) else None)
        if mode is ProgressMode.DETERMINATE:
            if total is None or total <= 0:
                raise ValueError("Determinate progress requires a positive total.")
        elif total is not None:
            raise ValueError("Only determinate progress may declare a total.")
        self._controller = controller
        self._anchor = parent if isinstance(parent, QWidget) else None
        self._title = title
        self._message = message
        self._mode = mode
        self._total = total
        self._cancel_callback = cancel_callback
        self._cancelable = cancelable
        self._active = False
        self._finished = False
        self._cancellation_requested = False
        self.task_id = uuid4().hex
        self.destroyed.connect(
            lambda _object=None, task_id=self.task_id: controller.abandon(task_id)
        )

    @property
    def mode(self) -> ProgressMode:
        return self._mode

    @property
    def total(self) -> int | None:
        return self._total

    def open(self) -> None:
        self.show()

    def show(self) -> None:
        if self._active or self._finished:
            return
        self._active = True
        self._controller.start(self)

    def set_mode(self, mode: ProgressMode, total: int | None = None) -> None:
        if mode is ProgressMode.DETERMINATE:
            if total is None or total <= 0:
                raise ValueError("Determinate progress requires a positive total.")
        elif total is not None:
            raise ValueError("Only determinate progress may declare a total.")
        self._mode = mode
        self._total = total
        self._controller.update(
            self,
            {
                "mode": mode.value,
                "total": total,
                "completed": 0,
            },
        )

    def set_progress(self, completed: int, total: int, detail: str | None = None) -> None:
        if self._mode is not ProgressMode.DETERMINATE:
            raise ValueError("Only determinate tasks accept numeric updates.")
        if self._total != total:
            raise ValueError("Progress total must match the declared total.")
        if not 0 <= completed <= total:
            raise ValueError("Progress must be within the declared total.")
        command: dict[str, object] = {"completed": completed}
        if detail is not None:
            command["detail"] = detail
        self._controller.update(self, command)

    def set_message(self, message: str) -> None:
        self._message = message
        self._controller.update(self, {"message": message})

    def finish(self, message: str | None = None) -> None:
        if self._finished:
            return
        self._finished = True
        if message is not None:
            self._message = message
        self._controller.finish(self, message=message)

    def _payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "title": self._title,
            "message": self._message,
            "mode": self._mode.value,
            "total": self._total,
            "completed": 0,
            "cancelable": self._cancelable,
        }

    def _request_cancel(self) -> None:
        if not self._cancelable or self._finished or self._cancellation_requested:
            return
        self._cancellation_requested = True
        self._cancelable = False
        self._message = QCoreApplication.translate(
            "TaskProgressDialog",
            "Cancellation requested. Waiting for the current operation to stop safely...",
        )
        self._controller.update(
            self,
            {
                "cancelable": False,
                "message": self._message,
                "cancelling": True,
            },
        )
        try:
            self._cancel_callback()
        except Exception:
            _LOGGER.exception("The progress cancellation callback failed.")

    def _handle_helper_unavailable(self) -> None:
        if not self._active:
            return
        self._active = False
        if self._cancelable and not self._cancellation_requested:
            self._cancellation_requested = True
            try:
                self._cancel_callback()
            except Exception:
                _LOGGER.exception("The progress cancellation callback failed.")
        self._finished = True
        self.helper_unavailable.emit()

    def _handle_helper_shown(self) -> None:
        if self._active and not self._finished:
            self.shown.emit()


def _format_bytes(value: int) -> str:
    amount = float(max(0, value))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TiB"
