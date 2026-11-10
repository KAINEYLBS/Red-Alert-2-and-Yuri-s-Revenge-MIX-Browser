from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TemporaryFileCleanupResult:
    removed_files: int
    remaining_files: int
    failed_entries: int


def _managed_temporary_root(path: Path) -> Path:
    root = Path(path).resolve(strict=True)
    temporary_directory = Path(tempfile.gettempdir()).resolve(strict=True)
    if root.parent != temporary_directory or not root.name.startswith("mix-browser-"):
        raise ValueError("The path is not a MIX Browser runtime temporary directory.")
    if not root.is_dir():
        raise NotADirectoryError(root)
    return root


def count_temporary_files(path: Path) -> int:
    """Counts files in the current desktop process's temporary directory."""
    root = _managed_temporary_root(path)
    count = 0

    def raise_walk_error(error: OSError) -> None:
        raise error

    for directory, subdirectories, filenames in os.walk(
        root,
        followlinks=False,
        onerror=raise_walk_error,
    ):
        count += len(filenames)
        linked_directories = [
            name
            for name in subdirectories
            if (Path(directory) / name).is_symlink()
        ]
        count += len(linked_directories)
        if linked_directories:
            linked_names = set(linked_directories)
            subdirectories[:] = [
                name for name in subdirectories if name not in linked_names
            ]
    return count


# @arch mix-browser.clean-runtime-temporary-files service | en: Counts and removes files in the active desktop process's temporary directory | zh: 统计并清理当前桌面进程临时目录中的文件
def clean_temporary_files(path: Path) -> TemporaryFileCleanupResult:
    root = _managed_temporary_root(path)
    initial_count = count_temporary_files(root)
    failed_entries = 0

    for child in root.iterdir():
        try:
            if child.is_symlink() or not child.is_dir():
                child.unlink(missing_ok=True)
            else:
                shutil.rmtree(child)
        except FileNotFoundError:
            continue
        except OSError:
            failed_entries += 1

    remaining_count = count_temporary_files(root)
    return TemporaryFileCleanupResult(
        removed_files=max(0, initial_count - remaining_count),
        remaining_files=remaining_count,
        failed_entries=failed_entries,
    )
