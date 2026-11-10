from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from mix_browser.shared.file_operations import replace_path_with_staged_sibling


ProgressCallback = Callable[[int, int], None]
CancellationCheck = Callable[[], bool]


# @arch mix-browser.directory-file-create service | en: Creates an empty file in a directory, optionally replacing an existing item | zh: 在目录中创建空文件，并可选替换已有对象
def create_file(
    directory: Path,
    name: str,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    parent = directory.expanduser()
    if not is_valid_leaf_name(name):
        raise ValueError("The file name is invalid.")
    if not parent.is_dir():
        raise NotADirectoryError(f"The destination is not a directory: {parent}")
    created = parent / name
    if not overwrite:
        with created.open("xb"):
            pass
    else:
        staged = parent / f".mix-browser-new-{uuid.uuid4().hex}"
        try:
            with staged.open("xb"):
                pass
            replace_path_with_staged_sibling(staged, created, overwrite=True)
        finally:
            staged.unlink(missing_ok=True)
    return {"directory": str(parent.resolve()), "created_path": str(created.resolve())}


# @arch mix-browser.directory-create-operation service | en: Creates an empty child directory, optionally replacing an existing item | zh: 创建空子目录，并可选替换已有对象
def create_directory(
    directory: Path,
    name: str,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    parent = directory.expanduser()
    if not is_valid_leaf_name(name):
        raise ValueError("The directory name is invalid.")
    if not parent.is_dir():
        raise NotADirectoryError(f"The destination is not a directory: {parent}")
    created = parent / name
    if not overwrite:
        created.mkdir()
    else:
        staged = parent / f".mix-browser-new-{uuid.uuid4().hex}"
        try:
            staged.mkdir()
            replace_path_with_staged_sibling(staged, created, overwrite=True)
        finally:
            if _present(staged):
                _remove(staged)
    return {"directory": str(parent.resolve()), "created_path": str(created.resolve())}


# @arch mix-browser.directory-entry-rename service | en: Renames one filesystem entry and optionally replaces an existing destination | zh: 重命名单个文件系统对象，并可选替换已存在的目标对象
def rename_entry(
    path: Path,
    new_name: str,
    *,
    overwrite: bool = False,
) -> dict[str, object]:
    source = _absolute_path(path)
    if not _present(source):
        raise FileNotFoundError(f"The item does not exist: {source}")
    if not is_valid_leaf_name(new_name):
        raise ValueError("The new name is invalid.")
    if source.parent == source:
        raise ValueError("A filesystem root cannot be renamed.")
    destination = source.with_name(new_name)
    if source.name == new_name:
        return {"source_path": str(source), "renamed_path": str(source), "renamed": False}
    same_name = os.path.normcase(source.name) == os.path.normcase(new_name)
    if _present(destination) and not same_name:
        if not overwrite:
            raise FileExistsError(f"The destination already exists: {destination}")
        replace_path_with_staged_sibling(source, destination, overwrite=True)
        return {"source_path": str(source), "renamed_path": str(destination), "renamed": True}

    if same_name:
        temporary = source.with_name(f".mix-browser-rename-{uuid.uuid4().hex}")
        source.rename(temporary)
        try:
            temporary.rename(destination)
        except OSError:
            temporary.rename(source)
            raise
    else:
        source.rename(destination)
    return {"source_path": str(source), "renamed_path": str(destination), "renamed": True}


# @arch mix-browser.directory-entry-delete service | en: Deletes selected filesystem entries | zh: 删除选中的文件系统对象
def delete_entries(
    paths: Sequence[Path],
    *,
    progress: ProgressCallback | None = None,
    cancellation_requested: CancellationCheck | None = None,
) -> dict[str, object]:
    sources = _validated_sources(paths)
    if not sources:
        raise ValueError("At least one item is required.")
    if progress:
        progress(0, len(sources) * 2)
    staged: list[tuple[Path, Path, Path]] = []
    try:
        for index, source in enumerate(sources, start=1):
            _check_cancelled(cancellation_requested)
            quarantine = Path(tempfile.mkdtemp(prefix=".mix-browser-delete-", dir=source.parent))
            staged_path = quarantine / "item"
            try:
                os.replace(source, staged_path)
            except OSError:
                shutil.rmtree(quarantine, ignore_errors=True)
                raise
            staged.append((source, staged_path, quarantine))
            if progress:
                progress(index, len(sources) * 2)
        _check_cancelled(cancellation_requested)
    except Exception as operation_error:
        rollback_errors = _restore_staged_entries(staged)
        if rollback_errors:
            raise OSError(
                "The deletion was cancelled or failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from operation_error
        raise

    deleted: list[str] = []
    failures: list[str] = []
    cancelled = False
    preserved_quarantines: set[Path] = set()
    for index, (source, staged_path, _quarantine) in enumerate(staged, start=1):
        if cancellation_requested and cancellation_requested():
            cancelled = True
            for restore_source, restore_path, restore_quarantine in staged[index - 1 :]:
                if _present(restore_path):
                    try:
                        os.replace(restore_path, restore_source)
                    except OSError as exc:
                        failures.append(
                            f"{restore_source}: restore failed: {exc}; staged data remains at {restore_path}"
                        )
                        preserved_quarantines.add(restore_quarantine)
            break
        try:
            _remove(staged_path)
        except OSError as exc:
            failures.append(f"{source}: {exc}")
            if _present(staged_path):
                try:
                    os.replace(staged_path, source)
                except OSError as restore_error:
                    failures[-1] += f"; restore failed: {restore_error}"
                    preserved_quarantines.add(_quarantine)
        else:
            deleted.append(str(source))
        if progress:
            progress(len(sources) + index, len(sources) * 2)
    for _source, _staged_path, quarantine in staged:
        if quarantine not in preserved_quarantines:
            shutil.rmtree(quarantine, ignore_errors=True)
    return {
        "deleted_paths": deleted,
        "delete_failures": failures,
        "cancelled": cancelled,
        "recovery_paths": [str(path) for path in preserved_quarantines],
    }


# @arch mix-browser.directory-entry-transfer service | en: Copies or moves filesystem entries into a directory | zh: 将文件系统对象复制或移动到目标目录
def transfer_entries(
    destination: Path,
    source_paths: Sequence[Path],
    *,
    move: bool = False,
    overwrite: bool = False,
    progress: ProgressCallback | None = None,
    cancellation_requested: CancellationCheck | None = None,
) -> dict[str, object]:
    target_directory = destination.expanduser().resolve()
    if not target_directory.is_dir():
        raise NotADirectoryError(f"The destination is not a directory: {target_directory}")
    sources = _validated_sources(source_paths)
    if not sources:
        raise ValueError("At least one source item is required.")

    transfers: list[tuple[Path, Path]] = []
    skipped: list[str] = []
    target_names: set[str] = set()
    for source in sources:
        target = target_directory / source.name
        name_key = source.name.casefold()
        if name_key in target_names:
            raise ValueError(f"More than one source has the same name: {source.name}")
        target_names.add(name_key)
        if _same_path(source, target):
            skipped.append(source.name)
            continue
        if source.is_dir() and not source.is_symlink():
            source_resolved = source.resolve()
            if target_directory == source_resolved or source_resolved in target_directory.parents:
                raise ValueError(f"A directory cannot be copied into itself: {source}")
        if _present(target):
            if not overwrite:
                raise FileExistsError(f"The destination already exists: {target}")
            source_is_directory = source.is_dir() and not source.is_symlink()
            target_is_directory = target.is_dir() and not target.is_symlink()
            if source_is_directory != target_is_directory:
                raise ValueError(f"The source and destination have incompatible types: {target}")
        transfers.append((source, target))

    if not transfers:
        return {"destination": str(target_directory), "transferred_names": [], "skipped_names": skipped}
    operation_units = len(transfers) * (3 if move else 2)
    if progress:
        progress(0, operation_units)

    stage_root = Path(tempfile.mkdtemp(prefix=".mix-browser-transfer-", dir=target_directory))
    staged_root = stage_root / "new"
    backup_root = stage_root / "old"
    staged: list[tuple[Path, Path, Path]] = []
    committed: list[tuple[Path, Path | None]] = []
    replaced_names: list[str] = []
    preserve_stage = False
    try:
        staged_root.mkdir()
        backup_root.mkdir()
        for index, (source, target) in enumerate(transfers):
            _check_cancelled(cancellation_requested)
            staged_path = staged_root / f"{index:08d}"
            _copy_entry(source, staged_path)
            staged.append((staged_path, target, source))
            if progress:
                progress(index + 1, operation_units)

        _check_cancelled(cancellation_requested)
        try:
            for index, (staged_path, target, _source) in enumerate(staged):
                backup_path = backup_root / f"{index:08d}"
                existing_backup = None
                if _present(target):
                    if not overwrite:
                        raise FileExistsError(f"The destination already exists: {target}")
                    os.replace(target, backup_path)
                    existing_backup = backup_path
                    replaced_names.append(target.name)
                committed.append((target, existing_backup))
                os.replace(staged_path, target)
                if progress:
                    progress(len(transfers) + index + 1, operation_units)
        except Exception as operation_error:
            rollback_errors: list[str] = []
            for target, backup_path in reversed(committed):
                try:
                    if _present(target):
                        _remove(target)
                    if backup_path is not None:
                        os.replace(backup_path, target)
                except OSError as rollback_error:
                    rollback_errors.append(str(rollback_error))
            if rollback_errors:
                preserve_stage = True
                raise OSError(
                    f"The transfer failed and rollback was incomplete. Recovery files remain in {stage_root}: "
                    + "; ".join(rollback_errors)
                ) from operation_error
            raise

        removed_sources: list[str] = []
        source_removal_failures: list[str] = []
        if move:
            for _staged_path, _target, source in staged:
                try:
                    _remove(source)
                except OSError as exc:
                    source_removal_failures.append(f"{source}: {exc}")
                else:
                    removed_sources.append(str(source))
                if progress:
                    progress(2 * len(transfers) + len(removed_sources) + len(source_removal_failures), operation_units)
        return {
            "destination": str(target_directory),
            "transferred_names": [target.name for _source, target in transfers],
            "moved_paths": removed_sources,
            "skipped_names": skipped,
            "source_removal_failures": source_removal_failures,
            "replaced_names": replaced_names,
        }
    finally:
        if not preserve_stage:
            shutil.rmtree(stage_root, ignore_errors=True)


def _validated_sources(paths: Sequence[Path]) -> tuple[Path, ...]:
    if not paths:
        return ()
    sources = tuple(_absolute_path(path) for path in paths)
    keys: set[str] = set()
    for source in sources:
        key = os.path.normcase(str(source))
        if key in keys:
            raise ValueError(f"The same item was specified more than once: {source}")
        keys.add(key)
        if source.parent == source:
            raise ValueError("A filesystem root cannot be modified.")
        if not _present(source):
            raise FileNotFoundError(f"The item does not exist: {source}")
        if not (source.is_file() or source.is_dir() or source.is_symlink()):
            raise ValueError(f"The item type is not supported: {source}")
    return sources


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left)) == os.path.normcase(str(right))


# @arch mix-browser.directory-leaf-name-validation utility | en: Validates a single filesystem entry name | zh: 验证单个文件系统对象名称
def is_valid_leaf_name(name: str) -> bool:
    if (
        not name
        or name != name.strip()
        or name in {".", ".."}
        or Path(name).name != name
        or any(character in '<>:/\\|?*"' or ord(character) < 32 for character in name)
        or name.endswith((".", " "))
    ):
        return False
    device_name = name.split(".", 1)[0].casefold()
    return device_name not in {
        "con",
        "prn",
        "aux",
        "nul",
        "conin$",
        "conout$",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }


def _copy_entry(source: Path, destination: Path) -> None:
    if source.is_symlink():
        os.symlink(os.readlink(source), destination, target_is_directory=source.is_dir())
    elif source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    elif source.is_file():
        shutil.copy2(source, destination)
    else:
        raise ValueError(f"The item type is not supported: {source}")


def _remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _check_cancelled(cancellation_requested: CancellationCheck | None) -> None:
    if cancellation_requested and cancellation_requested():
        raise InterruptedError("The filesystem operation was cancelled.")


def _restore_staged_entries(staged: Sequence[tuple[Path, Path, Path]]) -> list[str]:
    errors = []
    for source, staged_path, quarantine in reversed(staged):
        try:
            if _present(staged_path):
                os.replace(staged_path, source)
        except OSError as exc:
            errors.append(f"{source}: {exc}; staged data remains at {staged_path}")
        else:
            shutil.rmtree(quarantine, ignore_errors=True)
    return errors
