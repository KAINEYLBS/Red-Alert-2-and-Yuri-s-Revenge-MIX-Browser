from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


# @arch shared.replace-staged-path utility | en: Replaces a path with a staged sibling and restores the original if replacement fails | zh: 用同目录暂存对象替换路径，并在失败时恢复原对象
def replace_path_with_staged_sibling(
    staged_path: Path,
    destination: Path,
    *,
    overwrite: bool,
) -> None:
    staged = Path(os.path.abspath(staged_path.expanduser()))
    target = Path(os.path.abspath(destination.expanduser()))
    if staged.parent != target.parent:
        raise ValueError("A staged replacement must be beside its destination.")
    if not _present(staged):
        raise FileNotFoundError(f"The staged replacement does not exist: {staged}")

    backup: Path | None = None
    if _present(target):
        if not overwrite:
            raise FileExistsError(f"The destination already exists: {target}")
        backup = target.with_name(f".mix-browser-replaced-{uuid.uuid4().hex}")
        os.replace(target, backup)
    try:
        if backup is None:
            os.rename(staged, target)
        else:
            os.replace(staged, target)
    except OSError as operation_error:
        if backup is not None and _present(backup):
            try:
                os.replace(backup, target)
            except OSError as restore_error:
                raise OSError(
                    f"Replacement failed and the original item remains at {backup}: {restore_error}"
                ) from operation_error
        raise

    if backup is None:
        return
    try:
        _remove(backup)
    except OSError as cleanup_error:
        try:
            os.replace(target, staged)
            os.replace(backup, target)
        except OSError as restore_error:
            raise OSError(
                f"Replacement succeeded but rollback failed; the original item remains at {backup}: {restore_error}"
            ) from cleanup_error
        raise cleanup_error


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)
