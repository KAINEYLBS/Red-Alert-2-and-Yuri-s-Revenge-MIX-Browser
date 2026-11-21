from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from mix_browser.features.archive.domain import (
    LOCAL_MIX_DATABASE_NAME,
    MixArchiveIndex,
    MixEntry,
)
from mix_browser.features.archive.loader import MixArchiveLoader
from mix_browser.features.archive.type_detection import MIX_CONTAINER_SUFFIXES
from mix_browser.features.browser.directory_operations import is_valid_leaf_name
from mix_browser.features.browser.external_open import extract_entries_for_drag


ProgressCallback = Callable[[int, int], None]
CancellationCheck = Callable[[], bool]
_LoadedArchiveTarget = tuple[str, Path, MixArchiveIndex]


# @arch mix-browser.extract-container-files-to-folders service | en: Extracts selected container files into sibling folders without changing their sources | zh: 将选中的容器文件解包到同级文件夹且不修改源归档
def extract_mix_archives_to_folders(
    loader: MixArchiveLoader,
    archive_paths: Sequence[Path],
    destination_directory: Path,
    *,
    progress: ProgressCallback | None = None,
    cancellation_requested: CancellationCheck | None = None,
) -> dict[str, object]:
    destination = destination_directory.expanduser().resolve()
    if not destination.is_dir():
        raise NotADirectoryError(f"The destination is not a directory: {destination}")
    if not archive_paths:
        raise ValueError("At least one container archive is required.")

    sources: list[_LoadedArchiveTarget] = []
    source_keys: set[str] = set()
    folder_keys: set[str] = set()
    for raw_path in archive_paths:
        visible_source = raw_path.expanduser()
        source = visible_source.resolve()
        source_key = os.path.normcase(str(source))
        if source_key in source_keys:
            raise ValueError(f"The same container archive was selected more than once: {source}")
        source_keys.add(source_key)
        if not source.is_file():
            raise ValueError(f"The source is not a container archive: {source}")

        folder_name = visible_source.stem
        _validate_target_folder(folder_name, folder_keys)
        target = destination / folder_name
        if os.path.lexists(target):
            raise FileExistsError(f"The output folder already exists: {target}")
        sources.append((str(source), target, loader.load(source)))

    return _extract_loaded_archives(
        sources,
        destination,
        progress=progress,
        cancellation_requested=cancellation_requested,
    )


# @arch mix-browser.extract-nested-containers-to-folders service | en: Extracts selected nested containers beside their physical parent archive | zh: 将选中的内嵌容器解包到其物理父归档旁
def extract_nested_mix_entries_to_folders(
    loader: MixArchiveLoader,
    parent_archive: MixArchiveIndex,
    entry_ids: Sequence[int],
    destination_directory: Path,
    *,
    progress: ProgressCallback | None = None,
    cancellation_requested: CancellationCheck | None = None,
) -> dict[str, object]:
    destination = destination_directory.expanduser().resolve()
    if not destination.is_dir():
        raise NotADirectoryError(f"The destination is not a directory: {destination}")
    if not entry_ids:
        raise ValueError("At least one nested container entry is required.")
    if len(entry_ids) != len(set(entry_ids)):
        raise ValueError("Nested container entry IDs must be unique.")

    sources: list[_LoadedArchiveTarget] = []
    folder_keys: set[str] = set()
    parent_stat = parent_archive.path.stat()
    if (parent_stat.st_size, parent_stat.st_mtime_ns) != parent_archive.file_signature:
        raise OSError("The parent MIX archive changed after it was opened.")

    for entry_id in entry_ids:
        entry = next((candidate for candidate in parent_archive.entries if candidate.file_id == entry_id), None)
        if entry is None:
            raise FileNotFoundError(f"Nested container entry 0x{entry_id:08X} no longer exists.")
        suffix = Path(entry.name or "").suffix.casefold()
        if suffix not in MIX_CONTAINER_SUFFIXES and (entry.file_type or "").casefold() != "mix":
            raise ValueError(f"The selected entry is not a recognized container: {entry.name or entry_id}")
        visible_name = entry.name or f"Unknown-{entry.file_id:08X}.mix"
        folder_name = Path(visible_name).stem
        _validate_target_folder(folder_name, folder_keys)
        target = destination / folder_name
        if os.path.lexists(target):
            raise FileExistsError(f"The output folder already exists: {target}")
        nested_archive = loader.load_nested(parent_archive, entry)
        source_key = f"{parent_archive.path.resolve()}!{entry.file_id:08x}"
        sources.append((source_key, target, nested_archive))

    return _extract_loaded_archives(
        sources,
        destination,
        progress=progress,
        cancellation_requested=cancellation_requested,
    )


def _validate_target_folder(folder_name: str, folder_keys: set[str]) -> None:
    if not is_valid_leaf_name(folder_name):
        raise ValueError(f"The container name cannot be used as a folder name: {folder_name}")
    folder_key = folder_name.casefold()
    if folder_key in folder_keys:
        raise ValueError(f"Selected containers produce the same folder name: {folder_name}")
    folder_keys.add(folder_key)


def _extract_loaded_archives(
    sources: Sequence[_LoadedArchiveTarget],
    destination: Path,
    *,
    progress: ProgressCallback | None,
    cancellation_requested: CancellationCheck | None,
) -> dict[str, object]:
    if not sources:
        raise ValueError("At least one container archive is required.")

    archive_entries: list[tuple[str, Path, MixArchiveIndex, tuple[MixEntry, ...]]] = []
    source_keys: set[str] = set()
    for source_key, target, archive in sources:
        normalized_source_key = os.path.normcase(source_key)
        if normalized_source_key in source_keys:
            raise ValueError(f"The same container archive was selected more than once: {source_key}")
        source_keys.add(normalized_source_key)
        if os.path.lexists(target):
            raise FileExistsError(f"The output folder already exists: {target}")
        entries = tuple(
            entry
            for entry in archive.entries
            if (entry.name or "").casefold() != LOCAL_MIX_DATABASE_NAME.casefold()
        )
        archive_entries.append((source_key, target, archive, entries))

    total = sum(
        max(1, entry.size)
        for _source, _target, _archive, entries in archive_entries
        for entry in entries
    )
    if progress:
        progress(0, max(1, total))

    stage_root = Path(tempfile.mkdtemp(prefix=".mix-browser-extract-", dir=destination))
    staged: list[tuple[Path, Path]] = []
    committed: list[tuple[Path, Path]] = []
    preserve_stage = False
    completed = 0
    try:
        for index, (_source, target, archive, entries) in enumerate(archive_entries):
            _check_cancelled(cancellation_requested)
            staged_folder = stage_root / f"{index:08d}"
            archive_total = sum(max(1, entry.size) for entry in entries)

            def report_archive_progress(
                amount: int,
                _archive_total: int,
                *,
                base: int = completed,
            ) -> None:
                if progress:
                    progress(base + amount, max(1, total))

            extract_entries_for_drag(
                archive,
                entries,
                staged_folder,
                cancellation_requested=cancellation_requested,
                progress=report_archive_progress if progress else None,
            )
            completed += archive_total
            staged.append((staged_folder, target))

        _check_cancelled(cancellation_requested)
        for _staged_folder, target in staged:
            if os.path.lexists(target):
                raise FileExistsError(f"The output folder already exists: {target}")

        for staged_folder, target in staged:
            os.rename(staged_folder, target)
            committed.append((target, staged_folder))
    except Exception as operation_error:
        rollback_errors: list[str] = []
        for target, staged_folder in reversed(committed):
            try:
                os.rename(target, staged_folder)
            except OSError as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        if rollback_errors:
            preserve_stage = True
            raise OSError(
                f"Extraction failed and rollback was incomplete. Recovery files remain in {stage_root}: "
                + "; ".join(rollback_errors)
            ) from operation_error
        raise
    finally:
        if not preserve_stage:
            shutil.rmtree(stage_root, ignore_errors=True)

    return {
        "created_paths": tuple(str(target) for _staged_folder, target in staged),
        "extracted_file_count": sum(len(entries) for _source, _target, _archive, entries in archive_entries),
    }


def _check_cancelled(cancellation_requested: CancellationCheck | None) -> None:
    if cancellation_requested and cancellation_requested():
        raise InterruptedError("Container extraction was cancelled.")
