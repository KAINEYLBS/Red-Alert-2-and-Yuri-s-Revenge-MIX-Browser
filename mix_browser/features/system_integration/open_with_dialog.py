from __future__ import annotations

import os
import sys
from pathlib import Path

from mix_browser.features.archive.type_detection import MIX_CONTAINER_SUFFIXES
from mix_browser.shared.application_settings import application_directory

_CONTAINER_PROBE_NAME = "ra2ayrmb-association-probe"


# @arch mix-browser.container-association-probe utility | en: Creates and recognizes a persistent per-extension sample used by Windows association prompts | zh: 创建并识别供 Windows 文件关联提示使用的常驻扩展名样例
def create_container_association_probe(extension: str) -> Path:
    normalized = extension.casefold()
    if normalized not in MIX_CONTAINER_SUFFIXES:
        raise ValueError(f"Unsupported container extension: {extension}")
    directory = _container_association_probe_directory()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_CONTAINER_PROBE_NAME}{normalized}"
    with path.open("ab"):
        pass
    return path


def is_container_association_probe(path: Path) -> bool:
    candidate = Path(path).expanduser()
    if candidate.name.casefold() not in {
        f"{_CONTAINER_PROBE_NAME}{extension}".casefold()
        for extension in MIX_CONTAINER_SUFFIXES
    }:
        return False
    try:
        resolved = candidate.resolve()
        return (
            resolved.parent.name.casefold() == "default-app-samples"
            and resolved.parent.parent.name.casefold() == "system-integration"
        )
    except (OSError, RuntimeError):
        return False


def cleanup_container_association_probe(path: Path) -> None:
    if not is_container_association_probe(path):
        return
    cleanup_container_association_probe_result(path)


def _container_association_probe_directory() -> Path:
    return application_directory() / "system-integration" / "default-app-samples"


def _container_association_probe_result_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.result")


def write_container_association_probe_result(
    path: Path,
    is_default: bool | None,
) -> None:
    if not is_container_association_probe(path):
        raise ValueError(f"Not a container association probe: {path}")
    result = (
        "default"
        if is_default is True
        else "received"
        if is_default is False
        else "unknown"
    )
    _container_association_probe_result_path(path).write_text(result, encoding="ascii")


def consume_container_association_probe_result(path: Path) -> str | None:
    if not is_container_association_probe(path):
        return None
    result_path = _container_association_probe_result_path(path)
    try:
        result = result_path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return "error"
    try:
        result_path.unlink(missing_ok=True)
    except OSError:
        pass
    return result if result in {"default", "received", "unknown"} else "unknown"


def cleanup_container_association_probe_result(path: Path) -> None:
    if not is_container_association_probe(path):
        return
    try:
        _container_association_probe_result_path(path).unlink(missing_ok=True)
    except OSError:
        pass


def create_mix_association_probe() -> Path:
    return create_container_association_probe(".mix")


def is_mix_association_probe(path: Path) -> bool:
    return is_container_association_probe(path) and Path(path).suffix.casefold() == ".mix"


def cleanup_mix_association_probe(path: Path) -> None:
    cleanup_container_association_probe(path)


# @arch mix-browser.windows-default-file-opener adapter | en: Opens one file through its normal Windows shell association | zh: 通过 Windows Shell 的常规文件关联打开单个文件
def open_file_with_windows_default(path: Path) -> None:
    if sys.platform != "win32":
        raise OSError("Windows shell file opening is only available on Windows.")
    if not path.is_file():
        raise OSError(f"The container sample is unavailable: {path}")
    os.startfile(str(path))
