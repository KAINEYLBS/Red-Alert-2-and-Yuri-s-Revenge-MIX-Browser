from __future__ import annotations

import ctypes
import importlib
import logging
import os
import subprocess
import sys
import weakref
from pathlib import Path
from threading import RLock
from types import ModuleType

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QWidget

from mix_browser.shared.application_settings import application_directory

logger = logging.getLogger(__name__)
_RUNTIME_LOCK = RLock()
_VLC_MODULE: ModuleType | None = None
_VLC_INSTANCE = None
_VLC_DLL_DIRECTORY = None
_VLC_RUNTIME_ERROR = ""
_VLC_RUNTIME_LOADING = False
_ACTIVE_PLAYERS: weakref.WeakValueDictionary[int, VlcMediaPlayer] = (
    weakref.WeakValueDictionary()
)


# @arch mix-browser.vlc-runtime-preparation service | en: Loads the embedded libVLC runtime before a media preview needs it | zh: 在媒体预览需要运行时之前加载嵌入式 libVLC
def prepare_vlc_runtime() -> bool:
    global _VLC_MODULE, _VLC_INSTANCE, _VLC_DLL_DIRECTORY
    global _VLC_RUNTIME_ERROR, _VLC_RUNTIME_LOADING

    if sys.platform != "win32":
        _VLC_RUNTIME_ERROR = (
            "Embedded VLC media playback is currently available on Windows only."
        )
        return False

    with _RUNTIME_LOCK:
        if _VLC_INSTANCE is not None:
            return True
        if _VLC_RUNTIME_ERROR:
            return False
        if _VLC_RUNTIME_LOADING:
            return False
        _VLC_RUNTIME_LOADING = True

    dll_directory = None
    try:
        runtime = VlcMediaPlayer._find_runtime()
        if runtime is None:
            _VLC_RUNTIME_ERROR = (
                "The VLC runtime is missing. Run tools/prepare_vlc_runtime.bat, then restart the application."
            )
            return False
        _ensure_plugin_cache(runtime)

        old_library_path = os.environ.get("PYTHON_VLC_LIB_PATH")
        old_module_path = os.environ.get("PYTHON_VLC_MODULE_PATH")
        try:
            binding_directory = Path(sys.executable).resolve().parent / "python-vlc"
            if (binding_directory / "vlc.py").is_file():
                binding_path = str(binding_directory)
                if binding_path not in sys.path:
                    sys.path.insert(0, binding_path)
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
        finally:
            VlcMediaPlayer._restore_environment(
                "PYTHON_VLC_LIB_PATH",
                old_library_path,
            )
            VlcMediaPlayer._restore_environment(
                "PYTHON_VLC_MODULE_PATH",
                old_module_path,
            )

        with _RUNTIME_LOCK:
            _VLC_MODULE = module
            _VLC_DLL_DIRECTORY = dll_directory
            _VLC_INSTANCE = instance
            dll_directory = None
        return True
    except (Exception, SystemExit):
        logger.exception("Could not load the bundled libVLC runtime")
        _VLC_RUNTIME_ERROR = "The bundled VLC runtime could not be loaded."
        return False
    finally:
        if dll_directory is not None:
            dll_directory.close()
        with _RUNTIME_LOCK:
            _VLC_RUNTIME_LOADING = False


# @arch mix-browser.vlc-plugin-cache utility | en: Creates a missing or empty cache for the selected VLC plugin directory | zh: 为指定的 VLC 插件目录生成缺失或空白缓存
def _ensure_plugin_cache(runtime: Path) -> None:
    plugin_directory = runtime / "plugins"
    plugin_cache = plugin_directory / "plugins.dat"
    try:
        if plugin_cache.stat().st_size > 24:
            return
    except OSError:
        pass

    cache_generator = runtime / "vlc-cache-gen.exe"
    if not cache_generator.is_file():
        logger.warning(
            "The VLC plugin cache is empty and its cache generator is unavailable."
        )
        return

    result = subprocess.run(
        [str(cache_generator), str(plugin_directory)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError(
            "VLC plugin cache generation failed: "
            + (result.stderr.strip() or result.stdout.strip() or str(result.returncode))
        )
    try:
        cache_size = plugin_cache.stat().st_size
    except OSError as exc:
        raise RuntimeError("VLC plugin cache was not created.") from exc
    if cache_size <= 24:
        raise RuntimeError("VLC plugin cache generation produced an empty cache.")


# @arch mix-browser.vlc-runtime-shutdown utility | en: Releases active players and the shared libVLC instance | zh: 释放活动播放器和共享 libVLC 实例
def shutdown_vlc_runtime() -> None:
    global _VLC_INSTANCE, _VLC_DLL_DIRECTORY

    for player in tuple(_ACTIVE_PLAYERS.values()):
        player.shutdown()
    if _VLC_INSTANCE is not None:
        _VLC_INSTANCE.release()
        _VLC_INSTANCE = None
    if _VLC_DLL_DIRECTORY is not None:
        _VLC_DLL_DIRECTORY.close()
        _VLC_DLL_DIRECTORY = None

# @arch mix-browser.vlc-media-player component | en: Plays in-memory audio and video through an embedded libVLC player | zh: 通过嵌入式 libVLC 播放内存中的音频和视频
class VlcMediaPlayer(QWidget):
    playback_state_changed = Signal(bool)
    position_changed = Signal(int)
    duration_changed = Signal(int)
    video_size_changed = Signal(int, int)
    media_ready_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setStyleSheet("background-color: black;")
        self.setMinimumHeight(160)

        self._vlc: ModuleType | None = None
        self._instance = None
        self._player = None
        self._media = None
        self._media_data: bytes | None = None
        self._media_has_video = False
        self._video_size: tuple[int, int] | None = None
        self._pending_media_data: bytes | None = None
        self._pending_media_suffix = ""
        self._callbacks: tuple[object, ...] = ()
        self._runtime_error = ""
        self._is_playing = False
        self._position_ms = 0
        self._duration_ms = 0
        self._pending_seek_position: int | None = None
        self._error_reported = False
        self._audio_initialized = False
        self._shutting_down = False

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_player)
        self._runtime_wait_timer = QTimer(self)
        self._runtime_wait_timer.setInterval(100)
        self._runtime_wait_timer.timeout.connect(self._finish_pending_media_setup)

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def position_ms(self) -> int:
        return self._position_ms

    @property
    def duration_ms(self) -> int:
        return self._duration_ms

    @property
    def has_pending_media(self) -> bool:
        return self._pending_media_data is not None

    def prepare_video_surface(self) -> None:
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.winId()

    def set_media_data(self, data: bytes, media_suffix: str) -> bool:
        self.stop()
        media_data = bytes(data)
        if not media_data:
            self._report_error(self.tr("The media stream is empty."))
            return False
        suffix = media_suffix.casefold()
        if suffix not in {".wav", ".bik", ".bk2"}:
            self._report_error(self.tr("VLC cannot preview this media format."))
            return False

        if self._ensure_vlc():
            return self._install_media_data(media_data, suffix)
        if self._runtime_error:
            self._report_error(self._runtime_error)
            return False

        self._pending_media_data = media_data
        self._pending_media_suffix = suffix
        self._runtime_wait_timer.start()
        return False

    def _install_media_data(self, media_data: bytes, suffix: str) -> bool:
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
        self._media_has_video = suffix in {".bik", ".bk2"}
        self._callbacks = callbacks
        self._media = media
        self._error_reported = False
        self._audio_initialized = False
        self._position_ms = 0
        self._duration_ms = 0
        self._pending_seek_position = None
        self.position_changed.emit(0)
        self.duration_changed.emit(0)
        return True

    def _finish_pending_media_setup(self) -> None:
        media_data = self._pending_media_data
        if media_data is None:
            self._runtime_wait_timer.stop()
            return
        if not self._ensure_vlc():
            if self._runtime_error:
                self._runtime_wait_timer.stop()
                self._pending_media_data = None
                self._pending_media_suffix = ""
                self._report_error(self._runtime_error)
            return

        suffix = self._pending_media_suffix
        self._runtime_wait_timer.stop()
        self._pending_media_data = None
        self._pending_media_suffix = ""
        if self._install_media_data(media_data, suffix):
            self.media_ready_changed.emit(True)

    def play(self) -> None:
        if self._player is None or self._media is None:
            return
        try:
            pending_seek = self._pending_seek_position
            restart = pending_seek is not None or (
                self._vlc is not None
                and self._player.get_state() == self._vlc.State.Ended
            )
            if restart:
                self._player.stop()
            self._prepare_audio_levels_for_playback()
            if self._player.play() < 0:
                self._report_error(self.tr("VLC could not play this media."))
                return
            self._pending_seek_position = None
            if pending_seek is not None:
                self._player.set_time(pending_seek)
                self._position_ms = pending_seek
                self.position_changed.emit(pending_seek)
            self._poll_timer.start()
            if pending_seek is None:
                self._poll_player()
        except Exception:
            logger.exception("libVLC failed to start media playback")
            self._report_error(self.tr("VLC could not play this media."))

    def pause(self) -> None:
        if self._player is None or self._media is None:
            return
        try:
            self._sync_video_size()
            self._player.set_pause(1)
            self._poll_timer.stop()
            self._set_playing(False)
        except Exception:
            logger.exception("libVLC failed to pause Bink playback")

    def seek(self, position_ms: int) -> None:
        if self._player is None or self._media is None:
            return
        try:
            position_ms = max(0, int(position_ms))
            if (
                self._vlc is not None
                and self._player.get_state() == self._vlc.State.Ended
            ):
                # VLC no longer has an active input thread to receive this seek.
                self._pending_seek_position = position_ms
                self._position_ms = position_ms
                self.position_changed.emit(position_ms)
                return
            self._pending_seek_position = None
            self._player.set_time(position_ms)
            self._poll_player()
        except Exception:
            logger.exception("libVLC failed to seek Bink playback")

    def stop(self) -> None:
        self._runtime_wait_timer.stop()
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
        self._media_has_video = False
        self._pending_media_data = None
        self._pending_media_suffix = ""
        self._pending_seek_position = None
        if self._video_size is not None:
            self._video_size = None
            self.video_size_changed.emit(0, 0)
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
        _ACTIVE_PLAYERS.pop(id(self), None)

    def _ensure_vlc(self) -> bool:
        if self._player is not None:
            return True
        if self._shutting_down:
            return False
        if self._runtime_error:
            return False
        if _VLC_RUNTIME_ERROR:
            self._runtime_error = self.tr(_VLC_RUNTIME_ERROR)
            return False
        if _VLC_INSTANCE is None or _VLC_MODULE is None:
            return False

        try:
            self._vlc = _VLC_MODULE
            self._instance = _VLC_INSTANCE
            self._player = self._instance.media_player_new()
            self.prepare_video_surface()
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
            self._sync_video_size()
            if playing:
                self._initialize_audio_track()

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

    def _sync_video_size(self) -> None:
        if not self._media_has_video or self._player is None:
            return
        try:
            size = self._player.video_get_size(0)
            if not size or len(size) != 2:
                return
            width, height = int(size[0]), int(size[1])
        except Exception:
            return
        if width <= 0 or height <= 0 or (width, height) == self._video_size:
            return
        self._video_size = (width, height)
        self.video_size_changed.emit(width, height)

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
            self._audio_initialized = True
        except Exception:
            logger.exception("Could not initialize media audio playback")

    def _prepare_audio_levels_for_playback(self) -> None:
        if self._player is None:
            return
        try:
            self._player.audio_set_mute(False)
            self._player.audio_set_volume(100)
        except Exception:
            logger.exception("Could not prepare VLC audio levels for playback")

    def _set_playing(self, playing: bool) -> None:
        playing = bool(playing)
        if playing == self._is_playing:
            return
        self._is_playing = playing
        self.playback_state_changed.emit(playing)

    def _report_error(self, message: str) -> None:
        self._error_reported = True
        self.error_occurred.emit(message)
