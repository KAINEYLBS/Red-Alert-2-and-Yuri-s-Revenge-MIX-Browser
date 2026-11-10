from __future__ import annotations

import ctypes
import importlib
import logging
import os
import sys
import time
import uuid
import weakref
from pathlib import Path
from threading import RLock
from types import ModuleType

from PySide6.QtCore import QCoreApplication, QTimer, Qt, Signal
from PySide6.QtWidgets import QWidget

from mix_browser.shared.application_settings import application_directory

logger = logging.getLogger(__name__)
_RUNTIME_LOCK = RLock()
_VLC_MODULE: ModuleType | None = None
_VLC_INSTANCE = None
_VLC_DLL_DIRECTORY = None
_VLC_RUNTIME_ERROR = ""
_VLC_SHUTDOWN_CONNECTED = False
_AUDIO_COM_INITIALIZED = False
_AUDIO_DEVICE_CACHE_VALID = False
_AUDIO_DEVICE_CACHE_VALUE: str | None = None
_AUDIO_DEVICE_CACHE_CHECKED_AT = 0.0
_AUDIO_DEVICE_QUERY_ERROR_REPORTED = False
_AUDIO_DEVICE_POLL_INTERVAL_SECONDS = 0.5
_ACTIVE_PLAYERS: weakref.WeakValueDictionary[int, VlcMediaPlayer] = (
    weakref.WeakValueDictionary()
)


def _shutdown_vlc_runtime() -> None:
    global _VLC_INSTANCE, _VLC_DLL_DIRECTORY, _AUDIO_COM_INITIALIZED

    for player in tuple(_ACTIVE_PLAYERS.values()):
        player.shutdown()
    if _VLC_INSTANCE is not None:
        _VLC_INSTANCE.release()
        _VLC_INSTANCE = None
    if _VLC_DLL_DIRECTORY is not None:
        _VLC_DLL_DIRECTORY.close()
        _VLC_DLL_DIRECTORY = None
    if _AUDIO_COM_INITIALIZED:
        try:
            ctypes.WinDLL("ole32").CoUninitialize()
        except Exception:
            logger.exception("Could not uninitialize Windows audio endpoint access")
        _AUDIO_COM_INITIALIZED = False


class _WindowsGuid(ctypes.Structure):
    _fields_ = (
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    )


def _windows_guid(value: str) -> _WindowsGuid:
    return _WindowsGuid.from_buffer_copy(uuid.UUID(value).bytes_le)


# @arch mix-browser.default-audio-output-id utility | en: Reads the current Windows default playback endpoint through Core Audio | zh: 通过 Core Audio 读取 Windows 当前默认播放端点
def _query_windows_default_audio_output_id() -> str:
    global _AUDIO_COM_INITIALIZED

    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    ole32.CoInitializeEx.restype = ctypes.c_long
    initialize_result = ole32.CoInitializeEx(None, 0x0)
    changed_mode = ctypes.c_long(0x80010106).value
    if initialize_result in (0, 1):
        _AUDIO_COM_INITIALIZED = True
    elif initialize_result != changed_mode:
        raise OSError(initialize_result, "Core Audio COM initialization failed")

    clsid_enumerator = _windows_guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
    iid_enumerator = _windows_guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
    ole32.CoCreateInstance.argtypes = (
        ctypes.POINTER(_WindowsGuid),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_WindowsGuid),
        ctypes.POINTER(ctypes.c_void_p),
    )
    ole32.CoCreateInstance.restype = ctypes.c_long
    enumerator = ctypes.c_void_p()
    result = ole32.CoCreateInstance(
        ctypes.byref(clsid_enumerator),
        None,
        1,
        ctypes.byref(iid_enumerator),
        ctypes.byref(enumerator),
    )
    if result < 0 or not enumerator.value:
        raise OSError(result, "Core Audio device enumeration could not start")

    device = ctypes.c_void_p()
    device_id = ctypes.c_void_p()
    try:
        enumerator_vtable = ctypes.cast(
            enumerator,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ).contents
        get_default_endpoint = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )(enumerator_vtable[4])
        result = get_default_endpoint(enumerator, 0, 1, ctypes.byref(device))
        if result < 0 or not device.value:
            raise OSError(result, "Windows has no default playback endpoint")

        device_vtable = ctypes.cast(
            device,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ).contents
        get_device_id = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )(device_vtable[5])
        result = get_device_id(device, ctypes.byref(device_id))
        if result < 0 or not device_id.value:
            raise OSError(result, "The default playback endpoint has no device ID")
        return ctypes.wstring_at(device_id.value)
    finally:
        if device_id.value:
            ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
            ole32.CoTaskMemFree(device_id)
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
        if device.value:
            device_vtable = ctypes.cast(
                device,
                ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
            ).contents
            release(device_vtable[2])(device)
        enumerator_vtable = ctypes.cast(
            enumerator,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ).contents
        release(enumerator_vtable[2])(enumerator)


def _current_windows_default_audio_output_id() -> str | None:
    global _AUDIO_DEVICE_CACHE_VALID, _AUDIO_DEVICE_CACHE_VALUE
    global _AUDIO_DEVICE_CACHE_CHECKED_AT, _AUDIO_DEVICE_QUERY_ERROR_REPORTED

    if sys.platform != "win32":
        return None
    now = time.monotonic()
    if (
        _AUDIO_DEVICE_CACHE_VALID
        and now - _AUDIO_DEVICE_CACHE_CHECKED_AT
        < _AUDIO_DEVICE_POLL_INTERVAL_SECONDS
    ):
        return _AUDIO_DEVICE_CACHE_VALUE

    _AUDIO_DEVICE_CACHE_CHECKED_AT = now
    try:
        _AUDIO_DEVICE_CACHE_VALUE = _query_windows_default_audio_output_id()
        _AUDIO_DEVICE_CACHE_VALID = True
        _AUDIO_DEVICE_QUERY_ERROR_REPORTED = False
    except Exception:
        if not _AUDIO_DEVICE_QUERY_ERROR_REPORTED:
            logger.exception("Could not query the Windows default playback endpoint")
            _AUDIO_DEVICE_QUERY_ERROR_REPORTED = True
        _AUDIO_DEVICE_CACHE_VALID = False
        return None
    return _AUDIO_DEVICE_CACHE_VALUE


# @arch mix-browser.vlc-media-player component | en: Plays in-memory audio and video through an embedded libVLC player | zh: 通过嵌入式 libVLC 播放内存中的音频和视频
class VlcMediaPlayer(QWidget):
    playback_state_changed = Signal(bool)
    position_changed = Signal(int)
    duration_changed = Signal(int)
    error_occurred = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setStyleSheet("background-color: black;")
        self.setMinimumHeight(160)

        self._vlc: ModuleType | None = None
        self._instance = None
        self._player = None
        self._media = None
        self._media_data: bytes | None = None
        self._callbacks: tuple[object, ...] = ()
        self._runtime_error = ""
        self._is_playing = False
        self._position_ms = 0
        self._duration_ms = 0
        self._error_reported = False
        self._audio_initialized = False
        self._shutting_down = False
        self._audio_output_device_id: str | None = None

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_player)

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def position_ms(self) -> int:
        return self._position_ms

    @property
    def duration_ms(self) -> int:
        return self._duration_ms

    def prepare_runtime(self) -> bool:
        return self._ensure_vlc()

    def set_media_data(self, data: bytes, media_suffix: str) -> bool:
        self.stop()
        if not self._ensure_vlc():
            self._report_error(self._runtime_error)
            return False

        media_data = bytes(data)
        if not media_data:
            self._report_error(self.tr("The media stream is empty."))
            return False
        suffix = media_suffix.casefold()
        if suffix not in {".wav", ".bik", ".bk2"}:
            self._report_error(self.tr("VLC cannot preview this media format."))
            return False

        cursor = [0]
        cursor_lock = RLock()
        vlc = self._vlc
        assert vlc is not None

        @vlc.cb.MediaOpenCb
        def open_stream(_opaque, data_pointer, size_pointer):
            with cursor_lock:
                cursor[0] = 0
            data_pointer[0] = None
            size_pointer[0] = len(media_data)
            return 0

        @vlc.cb.MediaReadCb
        def read_stream(_opaque, buffer, requested_size):
            try:
                with cursor_lock:
                    remaining = len(media_data) - cursor[0]
                    count = min(int(requested_size), remaining)
                    if count <= 0:
                        return 0
                    start = cursor[0]
                    ctypes.memmove(buffer, media_data[start : start + count], count)
                    cursor[0] += count
                    return count
            except Exception:
                logger.exception("libVLC failed while reading an in-memory media stream")
                return -1

        @vlc.cb.MediaSeekCb
        def seek_stream(_opaque, offset):
            try:
                offset = int(offset)
                with cursor_lock:
                    if offset > len(media_data):
                        return -1
                    cursor[0] = offset
                return 0
            except Exception:
                logger.exception("libVLC failed while seeking an in-memory media stream")
                return -1

        @vlc.cb.MediaCloseCb
        def close_stream(_opaque):
            return None

        callbacks = (open_stream, read_stream, seek_stream, close_stream)
        try:
            media = self._instance.media_new_callbacks(
                open_stream,
                read_stream,
                seek_stream,
                close_stream,
                None,
            )
            if media is None:
                raise RuntimeError("libVLC could not create a media stream")
            media.add_option(":demux=wav" if suffix == ".wav" else ":demux=avformat")
            self._player.set_media(media)
        except Exception:
            logger.exception("libVLC could not prepare the in-memory media stream")
            self._report_error(self.tr("VLC could not prepare this media."))
            return False

        self._media_data = media_data
        self._callbacks = callbacks
        self._media = media
        self._error_reported = False
        self._audio_initialized = False
        self._audio_output_device_id = None
        self._position_ms = 0
        self._duration_ms = 0
        self.position_changed.emit(0)
        self.duration_changed.emit(0)
        return True

    def play(self) -> None:
        if self._player is None or self._media is None:
            return
        try:
            if self._player.play() < 0:
                self._report_error(self.tr("VLC could not play this media."))
                return
            self._poll_timer.start()
            self._poll_player()
        except Exception:
            logger.exception("libVLC failed to start media playback")
            self._report_error(self.tr("VLC could not play this media."))

    def pause(self) -> None:
        if self._player is None or self._media is None:
            return
        try:
            self._player.set_pause(1)
            self._poll_timer.stop()
            self._set_playing(False)
        except Exception:
            logger.exception("libVLC failed to pause Bink playback")

    def seek(self, position_ms: int) -> None:
        if self._player is None or self._media is None:
            return
        try:
            self._player.set_time(max(0, int(position_ms)))
            self._poll_player()
        except Exception:
            logger.exception("libVLC failed to seek Bink playback")

    def stop(self) -> None:
        self._poll_timer.stop()
        player = self._player
        media = self._media
        if player is not None and media is not None:
            try:
                player.stop()
                player.set_media(None)
            except Exception:
                logger.exception("libVLC failed to stop Bink playback")
        if media is not None:
            try:
                media.release()
            except Exception:
                logger.exception("libVLC failed to release Bink media")
        self._media = None
        self._callbacks = ()
        self._media_data = None
        self._set_playing(False)
        if self._position_ms:
            self._position_ms = 0
            self.position_changed.emit(0)
        if self._duration_ms:
            self._duration_ms = 0
            self.duration_changed.emit(0)

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self.stop()
        player = self._player
        self._player = None
        self._instance = None
        if player is not None:
            try:
                player.release()
            except Exception:
                logger.exception("libVLC failed to release the Bink player")
        self._audio_output_device_id = None
        _ACTIVE_PLAYERS.pop(id(self), None)

    def _ensure_vlc(self) -> bool:
        if self._player is not None:
            return True
        if self._shutting_down:
            return False
        if self._runtime_error:
            return False
        if sys.platform != "win32":
            self._runtime_error = self.tr(
                "Embedded VLC media playback is currently available on Windows only."
            )
            return False

        global _VLC_MODULE, _VLC_INSTANCE, _VLC_DLL_DIRECTORY
        global _VLC_RUNTIME_ERROR, _VLC_SHUTDOWN_CONNECTED
        with _RUNTIME_LOCK:
            if _VLC_RUNTIME_ERROR:
                self._runtime_error = self.tr(_VLC_RUNTIME_ERROR)
                return False
            if _VLC_INSTANCE is None:
                runtime = self._find_runtime()
                if runtime is None:
                    _VLC_RUNTIME_ERROR = (
                        "The VLC runtime is missing. Run tools/prepare_vlc_runtime.bat, then restart the application."
                    )
                    self._runtime_error = self.tr(_VLC_RUNTIME_ERROR)
                    return False

                old_library_path = os.environ.get("PYTHON_VLC_LIB_PATH")
                old_module_path = os.environ.get("PYTHON_VLC_MODULE_PATH")
                dll_directory = None
                try:
                    dll_directory = os.add_dll_directory(str(runtime))
                    os.environ["PYTHON_VLC_LIB_PATH"] = str(runtime / "libvlc.dll")
                    os.environ["PYTHON_VLC_MODULE_PATH"] = str(runtime / "plugins")
                    module = importlib.import_module("vlc")
                    instance = module.Instance(
                        "--quiet",
                        "--ignore-config",
                        "--no-video-title-show",
                    )
                    if instance is None:
                        raise RuntimeError("libVLC could not create a player instance")
                except (Exception, SystemExit):
                    logger.exception("Could not load the bundled libVLC runtime")
                    if dll_directory is not None:
                        dll_directory.close()
                    _VLC_RUNTIME_ERROR = "The bundled VLC runtime could not be loaded."
                    self._runtime_error = self.tr(_VLC_RUNTIME_ERROR)
                    return False
                finally:
                    self._restore_environment("PYTHON_VLC_LIB_PATH", old_library_path)
                    self._restore_environment("PYTHON_VLC_MODULE_PATH", old_module_path)

                _VLC_MODULE = module
                _VLC_INSTANCE = instance
                _VLC_DLL_DIRECTORY = dll_directory

            try:
                self._vlc = _VLC_MODULE
                self._instance = _VLC_INSTANCE
                self._player = self._instance.media_player_new()
                self._player.set_hwnd(int(self.winId()))
            except Exception:
                logger.exception("Could not initialize the embedded libVLC player")
                self._runtime_error = self.tr(
                    "The bundled VLC runtime could not initialize media playback."
                )
                if self._player is not None:
                    self._player.release()
                self._player = None
                self._instance = None
                return False

            _ACTIVE_PLAYERS[id(self)] = self
            if not _VLC_SHUTDOWN_CONNECTED:
                application = QCoreApplication.instance()
                if application is not None:
                    application.aboutToQuit.connect(_shutdown_vlc_runtime)
                    _VLC_SHUTDOWN_CONNECTED = True
        return True

    @staticmethod
    def _restore_environment(name: str, value: str | None) -> None:
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    @staticmethod
    def _find_runtime() -> Path | None:
        configured = os.environ.get("RA2AYRMB_VLC_DIR")
        candidates = [Path(configured)] if configured else []
        application_root = application_directory()
        if getattr(sys, "frozen", False):
            candidates.extend(
                (
                    application_root / "vlc",
                    Path(getattr(sys, "_MEIPASS", application_root)) / "vlc",
                )
            )
        else:
            candidates.extend(
                (
                    application_root / ".runtime" / "vlc",
                    application_root / "vlc",
                )
            )
        for candidate in candidates:
            if (candidate / "libvlc.dll").is_file() and (
                candidate / "plugins"
            ).is_dir():
                return candidate.resolve()
        return None

    def _poll_player(self) -> None:
        if self._player is None or self._media is None or self._vlc is None:
            return
        try:
            state = self._player.get_state()
            playing = state == self._vlc.State.Playing
            self._set_playing(playing)
            if playing:
                self._initialize_audio_track()
                self._follow_system_default_audio_output()

            duration = max(0, int(self._player.get_length()))
            if duration != self._duration_ms:
                self._duration_ms = duration
                self.duration_changed.emit(duration)

            position = max(0, int(self._player.get_time()))
            if position != self._position_ms:
                self._position_ms = position
                self.position_changed.emit(position)

            if state == self._vlc.State.Error and not self._error_reported:
                self._error_reported = True
                self._poll_timer.stop()
                self._report_error(self.tr("VLC could not play this media."))
            elif state == self._vlc.State.Ended:
                self._poll_timer.stop()
        except Exception:
            logger.exception("Could not update libVLC playback state")
            self._poll_timer.stop()

    def _initialize_audio_track(self) -> None:
        if self._player is None or self._audio_initialized:
            return
        try:
            tracks = self._player.audio_get_track_description() or ()
            available_track_ids = [
                track_id for track_id, _name in tracks if track_id != -1
            ]
            if not available_track_ids:
                return
            if self._player.audio_get_track() < 0:
                self._player.audio_set_track(available_track_ids[0])
            self._follow_system_default_audio_output()
            self._player.audio_set_mute(False)
            self._player.audio_set_volume(100)
            self._audio_initialized = True
        except Exception:
            logger.exception("Could not initialize media audio playback")

    def _follow_system_default_audio_output(self) -> None:
        if self._player is None:
            return
        device_id = _current_windows_default_audio_output_id()
        if not device_id or device_id == self._audio_output_device_id:
            return
        try:
            self._player.audio_output_device_set(None, device_id)
            self._audio_output_device_id = device_id
        except Exception:
            logger.exception("Could not switch VLC to the Windows default playback endpoint")

    def _set_playing(self, playing: bool) -> None:
        playing = bool(playing)
        if playing == self._is_playing:
            return
        self._is_playing = playing
        self.playback_state_changed.emit(playing)

    def _report_error(self, message: str) -> None:
        self._error_reported = True
        self.error_occurred.emit(message)
