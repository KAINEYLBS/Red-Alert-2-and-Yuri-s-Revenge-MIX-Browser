from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


class ExplorerSelectionError(RuntimeError):
    pass


# @arch mix-browser.explorer-selection adapter | en: Reads selected file paths from the matching Windows Explorer window | zh: 从匹配的 Windows 资源管理器窗口读取选中的文件路径
def resolve_explorer_selection(anchor_paths: tuple[Path, ...]) -> tuple[Path, ...]:
    if sys.platform != "win32":
        raise ExplorerSelectionError("Explorer selection is only available on Windows.")
    if not anchor_paths:
        raise ExplorerSelectionError("Windows did not pass a selected file path.")

    try:
        from PySide6.QtAxContainer import QAxObject

        anchor_keys = {_path_key(path) for path in anchor_paths}
        foreground = int(ctypes.windll.user32.GetForegroundWindow())
        shell = QAxObject("Shell.Application")
        if shell.isNull():
            raise ExplorerSelectionError("Windows Explorer could not be queried.")

        windows = shell.querySubObject("Windows()")
        if windows is None or windows.isNull():
            raise ExplorerSelectionError("Windows Explorer could not be queried.")

        keepalive = [shell, windows]
        candidates: list[tuple[int, tuple[Path, ...]]] = []
        window_count = int(windows.property("Count") or 0)
        for index in range(window_count):
            window = windows.querySubObject("Item(int)", index)
            if window is None or window.isNull():
                continue
            keepalive.append(window)
            document = window.querySubObject("Document")
            if document is None or document.isNull():
                continue
            keepalive.append(document)
            selected = document.querySubObject("SelectedItems()")
            if selected is None or selected.isNull():
                continue
            keepalive.append(selected)
            selected_count = int(selected.property("Count") or 0)

            selected_paths: list[Path] = []
            for item_index in range(selected_count):
                item = selected.querySubObject("Item(int)", item_index)
                if item is None or item.isNull():
                    continue
                keepalive.append(item)
                item_path = item.property("Path")
                if isinstance(item_path, str) and item_path:
                    selected_paths.append(Path(item_path))

            selected_keys = {_path_key(path) for path in selected_paths}
            if anchor_keys.issubset(selected_keys):
                candidates.append(
                    (int(window.property("HWND") or 0), tuple(selected_paths))
                )
    except ExplorerSelectionError:
        raise
    except Exception as exc:
        raise ExplorerSelectionError(
            "Windows Explorer could not provide the selected files."
        ) from exc

    if not candidates:
        raise ExplorerSelectionError(
            "The current File Explorer selection could not be read, so no files were changed."
        )

    foreground_candidates = [
        paths for hwnd, paths in candidates if hwnd and hwnd == foreground
    ]
    if len(foreground_candidates) == 1:
        return foreground_candidates[0]

    distinct_candidates = {
        tuple(_path_key(path) for path in paths): paths
        for _, paths in candidates
    }
    if len(distinct_candidates) == 1:
        return next(iter(distinct_candidates.values()))
    if len(candidates) == 1:
        return candidates[0][1]

    raise ExplorerSelectionError(
        "More than one File Explorer window has the selected file. Close the duplicate window and try again."
    )


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(os.fspath(path))))
