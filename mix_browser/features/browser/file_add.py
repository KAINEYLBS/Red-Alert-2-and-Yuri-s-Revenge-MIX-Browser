from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path


ProgressCallback = Callable[[int, int], None]
CancellationCheck = Callable[[], bool]


# @arch mix-browser.directory-file-add service | en: Copies files into a directory with staged replacement and rollback | zh: 通过暂存和回滚将文件复制到目录
def add_files_to_directory(
    directory: Path,
    source_paths: Sequence[Path],
    *,
    overwrite: bool = False,
    approved_overwrites: frozenset[str] | None = None,
    progress: ProgressCallback | None = None,
    cancellation_requested: CancellationCheck | None = None,
) -> dict[str, object]:
    target_directory = directory.expanduser().resolve()
    if not target_directory.is_dir():
        raise NotADirectoryError(f"The destination is not a directory: {target_directory}")
    if not source_paths:
        raise ValueError("At least one source file is required.")

    sources: list[tuple[Path, Path, tuple[int, int]]] = []
    names: set[str] = set()
    overwritten_names: list[str] = []
    approved_names = (
        {name.casefold() for name in approved_overwrites}
        if approved_overwrites is not None
        else None
    )
    total = 0
    for raw_source in source_paths:
        source = raw_source.expanduser().resolve()
        if source == target_directory or not source.is_file():
            raise ValueError(f"The source must be a regular file: {source}")
        name = source.name
        name_key = name.casefold()
        if name_key in names:
            raise ValueError(f"More than one dropped file has the same name: {name}")
        names.add(name_key)
        destination = target_directory / name
        if source == destination.resolve(strict=False):
            raise ValueError(f"The file is already in the destination directory: {source}")
        try:
            metadata = source.stat()
        except OSError:
            raise
        if destination.exists() and not destination.is_file():
            raise IsADirectoryError(f"The destination is not a regular file: {destination}")
        if destination.exists() and (
            not overwrite or (approved_names is not None and name_key not in approved_names)
        ):
            raise FileExistsError(f"The destination file already exists: {destination}")
        if destination.exists():
            overwritten_names.append(name)
        size = max(1, metadata.st_size)
        total += size
        sources.append((source, destination, (metadata.st_size, metadata.st_mtime_ns)))

    if progress:
        progress(0, total)

    stage_root = Path(tempfile.mkdtemp(prefix=".mix-browser-add-", dir=target_directory))
    staged_root = stage_root / "new"
    backup_root = stage_root / "old"
    copied = 0
    staged: list[tuple[Path, Path]] = []
    committed: list[tuple[Path, Path | None]] = []
    preserve_stage = False
    try:
        staged_root.mkdir()
        backup_root.mkdir()
        for index, (source, destination, expected_signature) in enumerate(sources):
            _check_cancelled(cancellation_requested)
            staged_path = staged_root / f"{index:08d}"
            before = source.stat()
            if (before.st_size, before.st_mtime_ns) != expected_signature:
                raise OSError(f"The source file changed before copying: {source}")
            with source.open("rb") as input_file, staged_path.open("xb") as output_file:
                while block := input_file.read(1024 * 1024):
                    _check_cancelled(cancellation_requested)
                    output_file.write(block)
                    copied += len(block)
                    if progress:
                        progress(copied, total)
            after = source.stat()
            if (after.st_size, after.st_mtime_ns) != expected_signature:
                raise OSError(f"The source file changed while copying: {source}")
            if expected_signature[0] == 0:
                copied += 1
                if progress:
                    progress(copied, total)
            shutil.copystat(source, staged_path)
            staged.append((staged_path, destination))

        _check_cancelled(cancellation_requested)
        try:
            for index, (staged_path, destination) in enumerate(staged):
                backup_path = backup_root / f"{index:08d}"
                existing_backup = None
                if destination.exists():
                    if not destination.is_file():
                        raise IsADirectoryError(f"The destination is not a regular file: {destination}")
                    name_key = destination.name.casefold()
                    if not overwrite or (approved_names is not None and name_key not in approved_names):
                        raise FileExistsError(f"The destination file already exists: {destination}")
                    os.replace(destination, backup_path)
                    existing_backup = backup_path
                committed.append((destination, existing_backup))
                os.replace(staged_path, destination)
        except Exception as operation_error:
            rollback_errors: list[str] = []
            for destination, backup_path in reversed(committed):
                try:
                    destination.unlink(missing_ok=True)
                    if backup_path is not None:
                        os.replace(backup_path, destination)
                except OSError as rollback_error:
                    rollback_errors.append(str(rollback_error))
            if rollback_errors:
                preserve_stage = True
                raise OSError(
                    f"File addition failed and rollback was incomplete. Backups remain in {backup_root}: "
                    + "; ".join(rollback_errors)
                ) from operation_error
            raise
        if progress:
            progress(total, total)
    finally:
        if not preserve_stage:
            shutil.rmtree(stage_root, ignore_errors=True)

    return {
        "directory": str(target_directory),
        "added_names": [destination.name for _source, destination, _signature in sources],
        "overwritten_names": overwritten_names,
    }


def _check_cancelled(cancellation_requested: CancellationCheck | None) -> None:
    if cancellation_requested and cancellation_requested():
        raise InterruptedError("The file copy was cancelled.")
