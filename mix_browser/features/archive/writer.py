from __future__ import annotations

import hashlib
import os
import shutil
import struct
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mix_browser.features.archive.domain import (
    Blowfish,
    EMPTY_MIX_ARCHIVE_HEADER,
    MixArchiveIndex,
    MixEntry,
    MixFormatError,
    LOCAL_MIX_DATABASE_NAME,
    LOCAL_MIX_DATABASE_SIGNATURE,
    _decrypt_mix_blowfish_key,
    _mix_file_hashes,
    _names_from_local_database,
    is_readable_mix_name,
    open_mix_archive,
    read_mix_entry_bytes,
)
from mix_browser.shared.file_operations import replace_path_with_staged_sibling


ProgressCallback = Callable[[int, int], None]
CancellationCheck = Callable[[], bool]
_COPY_CHUNK_SIZE = 1024 * 1024
_MAX_MIX_DATA_SIZE = 0xFFFFFFFF


class ExternalFileChangedError(RuntimeError):
    pass


class NoExternalChangesError(RuntimeError):
    pass


# @arch mix-browser.empty-mix-writer adapter | en: Creates an empty standard MIX archive and optionally replaces an existing path | zh: 创建标准空 MIX 归档并可选择替换现有路径
def create_empty_mix_archive(destination: Path, *, overwrite: bool = False) -> Path:
    requested_path = destination.expanduser()
    if requested_path.name in {"", ".", ".."}:
        raise ValueError("The output path must include a file name.")
    path = requested_path.parent.resolve() / requested_path.name
    header = EMPTY_MIX_ARCHIVE_HEADER
    if overwrite:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".mix-browser-create-",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                output.write(header)
            replace_path_with_staged_sibling(
                temporary_path,
                path,
                overwrite=True,
            )
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return path

    created = False
    try:
        with path.open("xb") as output:
            created = True
            output.write(header)
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise
    return path


@dataclass(frozen=True)
class _ArchiveLayout:
    archive: MixArchiveIndex
    kind: str
    flags: int
    count: int
    data_size: int
    data_start: int
    rows: tuple[tuple[int, int, int], ...]
    encrypted_key: bytes = b""
    checksum_size: int = 0

    @property
    def header_size(self) -> int:
        return self.data_start - self.archive.source_offset

    @property
    def trailing_size(self) -> int:
        archive_end = self.archive.source_offset + self.archive.source_size
        content_end = self.data_start + self.data_size + self.checksum_size
        return archive_end - content_end


def write_back_mix_entry(
    archive: MixArchiveIndex,
    entry_id: int,
    modified_file: Path,
    temporary_root: Path,
    *,
    original_content_hash: str,
    expected_content_hash: str,
    expected_archive_signature: tuple[int, int],
    progress: ProgressCallback | None = None,
    cancellation_requested: CancellationCheck | None = None,
) -> tuple[int, int]:
    root_path = archive.path
    initial_stat = root_path.stat()
    initial_signature = (initial_stat.st_size, initial_stat.st_mtime_ns)
    if initial_signature != expected_archive_signature:
        raise ExternalFileChangedError("The MIX archive changed after the entry was opened.")

    layouts = _build_archive_chain(archive, entry_id)
    replacement_size = modified_file.stat().st_size
    output_sizes: list[int] = []
    current_replacement_size = replacement_size
    for layout, target_id in layouts:
        output_size = _output_size(layout, target_id, current_replacement_size)
        output_sizes.append(output_size)
        current_replacement_size = output_size
    total = replacement_size + sum(output_sizes) + output_sizes[-1]
    completed = 0
    last_progress_at = 0.0
    last_progress_bytes = 0

    def report(amount: int) -> None:
        nonlocal completed, last_progress_at, last_progress_bytes
        completed += amount
        now = time.monotonic()
        if progress and (
            completed >= total
            or completed - last_progress_bytes >= 4 * 1024 * 1024
            or now - last_progress_at >= 0.15
        ):
            progress(completed, total)
            last_progress_at = now
            last_progress_bytes = completed

    if progress:
        progress(0, total)

    temporary_paths: list[Path] = []
    sibling_path: Path | None = None
    try:
        snapshot_path = _temporary_path(temporary_root, "edited-entry-")
        temporary_paths.append(snapshot_path)
        edited_hash, _copied_size = _copy_and_hash(
            modified_file,
            snapshot_path,
            report,
            cancellation_requested,
        )
        if edited_hash == original_content_hash:
            raise NoExternalChangesError("The edited file matches the original MIX entry.")
        if edited_hash != expected_content_hash:
            raise ExternalFileChangedError("The edited file changed during write-back. Check it again and retry.")

        replacement_path = snapshot_path
        for (layout, target_id), expected_size in zip(layouts, output_sizes, strict=True):
            _check_cancelled(cancellation_requested)
            output_path = _temporary_path(temporary_root, "updated-mix-")
            temporary_paths.append(output_path)
            _rewrite_archive_range(
                layout,
                target_id,
                replacement_path,
                output_path,
                expected_size=expected_size,
                report=report,
                cancellation_requested=cancellation_requested,
            )
            replacement_path = output_path

        _check_cancelled(cancellation_requested)
        sibling_path = _temporary_path(root_path.parent, ".mix-browser-update-", suffix=".tmp")
        _copy_file(replacement_path, sibling_path, report, cancellation_requested)
        try:
            shutil.copystat(root_path, sibling_path)
            os.utime(sibling_path, None)
        except OSError:
            pass

        current_stat = root_path.stat()
        current_signature = (current_stat.st_size, current_stat.st_mtime_ns)
        if current_signature != expected_archive_signature:
            raise ExternalFileChangedError("The MIX archive changed while the update was being prepared.")
        _check_cancelled(cancellation_requested)
        os.replace(sibling_path, root_path)
        sibling_path = None
        updated_stat = root_path.stat()
        if progress:
            progress(total, total)
        return updated_stat.st_size, updated_stat.st_mtime_ns
    finally:
        if sibling_path is not None:
            sibling_path.unlink(missing_ok=True)
        for path in temporary_paths:
            path.unlink(missing_ok=True)


# @arch mix-browser.mix-add-writer service | en: Adds or replaces named files in a MIX archive and its nested parents | zh: 向 MIX 归档及其嵌套父归档添加或替换命名文件
def add_files_to_mix(
    archive: MixArchiveIndex,
    source_paths: Sequence[Path],
    temporary_root: Path,
    *,
    overwrite: bool = False,
    expected_archive_signature: tuple[int, int],
    progress: ProgressCallback | None = None,
    cancellation_requested: CancellationCheck | None = None,
) -> tuple[tuple[int, int], tuple[str, ...], tuple[str, ...]]:
    root_path = archive.path
    current_stat = root_path.stat()
    if (current_stat.st_size, current_stat.st_mtime_ns) != expected_archive_signature:
        raise ExternalFileChangedError("The MIX archive changed before files were added.")
    if not source_paths:
        raise ValueError("At least one source file is required.")

    layouts = _build_archive_layout_chain(archive)
    leaf = layouts[0]
    legacy_hash = leaf.kind == "cnc"
    existing_rows = {file_id: (offset, size) for file_id, offset, size in leaf.rows}
    existing_entries = {entry.file_id: entry for entry in archive.entries}
    source_records: list[tuple[Path, str, int, int, tuple[int, int]]] = []
    source_names: set[str] = set()
    source_ids: dict[int, str] = {}
    total_input_size = 0

    for raw_path in source_paths:
        path = raw_path.expanduser().resolve()
        if path == root_path.resolve() or not path.is_file():
            raise ValueError(f"The source must be a regular file outside the target MIX: {path}")
        name = path.name
        if not _is_valid_mix_filename(name):
            raise ValueError(f"The file name cannot be stored in a MIX archive: {name}")
        if name.casefold() == LOCAL_MIX_DATABASE_NAME.casefold():
            raise ValueError(f"{LOCAL_MIX_DATABASE_NAME} is reserved for embedded MIX name data.")
        name_key = name.casefold()
        if name_key in source_names:
            raise ValueError(f"More than one source file has the same name: {name}")
        source_names.add(name_key)
        metadata = path.stat()
        file_id = _mix_file_hashes(name)[0 if legacy_hash else 1]
        previous_name = source_ids.get(file_id)
        if previous_name is not None and previous_name.casefold() != name.casefold():
            raise ValueError(f"Two dropped files resolve to the same MIX ID: {previous_name}, {name}")
        source_ids[file_id] = name
        current = existing_entries.get(file_id)
        if current is not None and current.name and current.name.casefold() != name.casefold():
            raise ExternalFileChangedError(
                f"The name {name} hashes to the existing entry {current.name}."
            )
        if current is not None and not overwrite:
            raise FileExistsError(_entry_collision_message(current, file_id))
        total_input_size += metadata.st_size
        source_records.append(
            (path, name, file_id, metadata.st_size, (metadata.st_size, metadata.st_mtime_ns))
        )

    database_id = _mix_file_hashes(LOCAL_MIX_DATABASE_NAME)[0 if legacy_hash else 1]
    if database_id in source_ids:
        raise ValueError(f"A source file collides with the reserved local name database ID: {source_ids[database_id]}")
    if database_id in existing_rows:
        database_entry = existing_entries.get(database_id)
        if database_entry is None:
            raise MixFormatError("The embedded MIX name database entry is not indexed.")
        database_data = read_mix_entry_bytes(archive, database_entry)
        if (
            database_data is None
            or len(database_data) < 52
            or not database_data.startswith(LOCAL_MIX_DATABASE_SIGNATURE)
            or struct.unpack_from("<I", database_data, 48)[0] > 0xFFFF
        ):
            raise ExternalFileChangedError(
                f"MIX entry 0x{database_id:08X} conflicts with the reserved local name database."
            )
        database_names = list(_names_from_local_database(database_data))
    else:
        database_names = []

    known_names = {name.casefold() for name in database_names}
    new_names = [name for _path, name, _file_id, _size, _signature in source_records]
    database_names.extend(name for name in new_names if name.casefold() not in known_names)
    database_names = _ordered_local_database_names(
        database_names,
        hash_index=0 if legacy_hash else 1,
    )
    encoded_names = [name.encode("ascii") for name in database_names]
    if len(encoded_names) > 0xFFFF:
        raise ValueError("The embedded MIX name database exceeds its format limit.")
    updated_database = (
        LOCAL_MIX_DATABASE_SIGNATURE.ljust(48, b"\0")
        + struct.pack("<I", len(encoded_names))
        + b"".join(name + b"\0" for name in encoded_names)
    )

    current_database_entry = existing_entries.get(database_id)
    if current_database_entry is None:
        additions_count = 1
        database_size = len(updated_database)
    else:
        additions_count = 0
        database_size = len(updated_database)
    if leaf.count + additions_count + sum(
        1 for _path, _name, file_id, _size, _signature in source_records if file_id not in existing_rows
    ) > 0xFFFF:
        raise ValueError("The MIX entry table exceeds the format limit.")

    replacements: dict[int, Path] = {}
    additions: list[tuple[int, Path]] = []
    replacement_sizes: dict[int, int] = {}
    addition_sizes: list[tuple[int, int]] = []
    replaced_names: list[str] = []
    for _path, name, file_id, size, _signature in source_records:
        if file_id in existing_rows:
            entry = existing_entries.get(file_id)
            replaced_names.append(entry.name if entry is not None and entry.name else f"Unknown (0x{file_id:08X})")
            replacement_sizes[file_id] = size
        else:
            addition_sizes.append((file_id, size))
    if current_database_entry is not None:
        replacement_sizes[database_id] = database_size
    else:
        addition_sizes.append((database_id, database_size))

    output_sizes: list[int] = []
    output_size = _output_size_with_changes(leaf, replacement_sizes, addition_sizes)
    output_sizes.append(output_size)
    current_replacement_size = output_size
    for layout, parent_ref in zip(layouts[1:], reversed(archive.parents), strict=True):
        output_size = _output_size(layout, parent_ref.entry_id, current_replacement_size)
        output_sizes.append(output_size)
        current_replacement_size = output_size

    total = total_input_size + database_size + sum(output_sizes) + output_sizes[-1]
    completed = 0
    last_progress_at = 0.0
    last_progress_bytes = 0

    def report(amount: int) -> None:
        nonlocal completed, last_progress_at, last_progress_bytes
        completed += amount
        now = time.monotonic()
        if progress and (
            completed >= total
            or completed - last_progress_bytes >= 4 * 1024 * 1024
            or now - last_progress_at >= 0.15
        ):
            progress(completed, total)
            last_progress_at = now
            last_progress_bytes = completed

    if progress:
        progress(0, total)

    temporary_paths: list[Path] = []
    sibling_path: Path | None = None
    try:
        snapshots: dict[int, Path] = {}
        for index, (source, _name, file_id, _size, expected_signature) in enumerate(source_records):
            _check_cancelled(cancellation_requested)
            snapshot = _temporary_path(temporary_root, f"added-entry-{index:08d}-")
            temporary_paths.append(snapshot)
            _copy_and_verify_source(source, snapshot, expected_signature, report, cancellation_requested)
            snapshots[file_id] = snapshot

        database_snapshot = _temporary_path(temporary_root, "local-mix-database-")
        temporary_paths.append(database_snapshot)
        _write_bytes(database_snapshot, updated_database, report, cancellation_requested)
        if current_database_entry is not None:
            replacements[database_id] = database_snapshot
        else:
            additions.append((database_id, database_snapshot))
        for _path, _name, file_id, _size, _signature in source_records:
            snapshot = snapshots[file_id]
            if file_id in existing_rows:
                replacements[file_id] = snapshot
            else:
                additions.append((file_id, snapshot))

        replacement_path = _temporary_path(temporary_root, "updated-mix-")
        temporary_paths.append(replacement_path)
        _rewrite_archive_with_changes(
            leaf,
            replacements,
            additions,
            replacement_path,
            expected_size=output_sizes[0],
            report=report,
            cancellation_requested=cancellation_requested,
        )

        for index, (layout, parent_ref) in enumerate(
            zip(layouts[1:], reversed(archive.parents), strict=True),
            start=1,
        ):
            _check_cancelled(cancellation_requested)
            output_path = _temporary_path(temporary_root, "updated-parent-mix-")
            temporary_paths.append(output_path)
            _rewrite_archive_range(
                layout,
                parent_ref.entry_id,
                replacement_path,
                output_path,
                expected_size=output_sizes[index],
                report=report,
                cancellation_requested=cancellation_requested,
            )
            replacement_path = output_path

        _check_cancelled(cancellation_requested)
        sibling_path = _temporary_path(root_path.parent, ".mix-browser-add-", suffix=".tmp")
        _copy_file(replacement_path, sibling_path, report, cancellation_requested)
        try:
            shutil.copystat(root_path, sibling_path)
            os.utime(sibling_path, None)
        except OSError:
            pass

        latest = root_path.stat()
        if (latest.st_size, latest.st_mtime_ns) != expected_archive_signature:
            raise ExternalFileChangedError("The MIX archive changed while the update was being prepared.")
        _check_cancelled(cancellation_requested)
        os.replace(sibling_path, root_path)
        sibling_path = None
        updated_stat = root_path.stat()
        if progress:
            progress(total, total)
        return (
            (updated_stat.st_size, updated_stat.st_mtime_ns),
            tuple(name for _path, name, _id, _size, _signature in source_records),
            tuple(replaced_names),
        )
    finally:
        if sibling_path is not None:
            sibling_path.unlink(missing_ok=True)
        for path in temporary_paths:
            path.unlink(missing_ok=True)


# @arch mix-browser.mix-entry-editor service | en: Removes, renames, or copies MIX entries through atomic archive rewrites | zh: 通过原子重写删除、重命名或复制 MIX 条目
def edit_mix_entries(
    archive: MixArchiveIndex,
    *,
    temporary_root: Path,
    remove_ids: Sequence[int] = (),
    rename_entries: Mapping[int, str] | None = None,
    copy_entries: Sequence[tuple[MixArchiveIndex, MixEntry]] = (),
    expected_archive_signature: tuple[int, int],
    progress: ProgressCallback | None = None,
    cancellation_requested: CancellationCheck | None = None,
) -> tuple[tuple[int, int], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    root_path = archive.path
    initial_stat = root_path.stat()
    if (initial_stat.st_size, initial_stat.st_mtime_ns) != expected_archive_signature:
        raise ExternalFileChangedError("The MIX archive changed before the edit began.")

    layouts = _build_archive_layout_chain(archive)
    leaf = layouts[0]
    hash_index = 0 if leaf.kind == "cnc" else 1
    existing_entries = {entry.file_id: entry for entry in archive.entries}
    existing_ids = {file_id for file_id, _offset, _size in leaf.rows}
    database_id = _mix_file_hashes(LOCAL_MIX_DATABASE_NAME)[hash_index]
    removed_ids = set(remove_ids)
    renames = dict(rename_entries or {})
    if len(removed_ids) != len(remove_ids):
        raise ValueError("A MIX entry ID was requested for deletion more than once.")
    if removed_ids & renames.keys():
        raise ValueError("An entry cannot be deleted and renamed in the same operation.")
    if not removed_ids.issubset(existing_ids) or not set(renames).issubset(existing_ids):
        raise FileNotFoundError("One or more MIX entries no longer exist.")
    if database_id in removed_ids or database_id in renames:
        raise ValueError("The embedded MIX name database cannot be edited as a regular entry.")

    renamed_ids: dict[int, int] = {}
    renamed_names: list[str] = []
    for old_id, name in renames.items():
        if not _is_valid_mix_filename(name) or name.casefold() == LOCAL_MIX_DATABASE_NAME.casefold():
            raise ValueError(f"The name cannot be stored in a MIX archive: {name}")
        renamed_ids[old_id] = _mix_file_hashes(name)[hash_index]
        renamed_names.append(name)

    prepared_copies: list[tuple[MixArchiveIndex, MixEntry, int, str | None]] = []
    copied_names: list[str] = []
    source_hash_indexes: dict[tuple[Path, int, int], int] = {}
    for source_archive, raw_entry in copy_entries:
        entry = raw_entry
        source_key = (
            source_archive.path.resolve(),
            source_archive.source_offset,
            source_archive.source_size,
        )
        source_hash_index = source_hash_indexes.get(source_key)
        if source_hash_index is None:
            source_hash_index = 0 if _read_layout(source_archive).kind == "cnc" else 1
            source_hash_indexes[source_key] = source_hash_index
        if entry.file_id == _mix_file_hashes(LOCAL_MIX_DATABASE_NAME)[source_hash_index]:
            raise ValueError("The embedded MIX name database cannot be copied as a regular entry.")
        name = entry.name
        if name and (not _is_valid_mix_filename(name) or name.casefold() == LOCAL_MIX_DATABASE_NAME.casefold()):
            raise ValueError(f"The name cannot be stored in a MIX archive: {name}")
        target_id = _mix_file_hashes(name)[hash_index] if name else entry.file_id
        prepared_copies.append((source_archive, entry, target_id, name))
        if name:
            copied_names.append(name)

    retained_ids = existing_ids - removed_ids - set(renames) - {database_id}
    destination_ids = set(retained_ids)
    requested_ids = (*renamed_ids.values(), *(item[2] for item in prepared_copies))
    if database_id in requested_ids:
        raise ValueError("A requested entry name collides with the embedded MIX name database.")
    for target_id in requested_ids:
        if target_id in destination_ids:
            raise FileExistsError(f"A MIX entry with ID 0x{target_id:08X} already exists.")
        destination_ids.add(target_id)
    if len(destination_ids) > 0xFFFF:
        raise ValueError("The MIX entry table exceeds the format limit.")

    database_entry = existing_entries.get(database_id)
    if database_entry is not None:
        database_data = read_mix_entry_bytes(archive, database_entry)
        if (
            database_data is None
            or len(database_data) < 52
            or not database_data.startswith(LOCAL_MIX_DATABASE_SIGNATURE)
            or struct.unpack_from("<I", database_data, 48)[0] > 0xFFFF
        ):
            raise ExternalFileChangedError("The reserved local MIX name database is invalid.")
        database_names = list(_names_from_local_database(database_data))
    else:
        database_names = []
    # Keep the embedded local name database aligned with the same archive edit.
    affected_ids = removed_ids | set(renames)
    database_names = [
        name for name in database_names
        if _mix_file_hashes(name)[hash_index] not in affected_ids
    ]
    known_names = {name.casefold() for name in database_names}
    for name in (*renamed_names, *copied_names):
        if name.casefold() not in known_names:
            database_names.append(name)
            known_names.add(name.casefold())
    database_names = _ordered_local_database_names(database_names, hash_index=hash_index)
    if len(database_names) > 0xFFFF:
        raise ValueError("The embedded MIX name database exceeds its format limit.")
    updated_database = (
        LOCAL_MIX_DATABASE_SIGNATURE.ljust(48, b"\0")
        + struct.pack("<I", len(database_names))
        + b"".join(name.encode("ascii") + b"\0" for name in database_names)
    )

    database_size_changed = database_entry is not None or bool(renamed_names or copied_names)
    replacement_sizes = (
        {database_id: len(updated_database)}
        if database_size_changed and database_entry is not None
        else {}
    )
    additions_sizes = [(target_id, entry.size) for _source, entry, target_id, _name in prepared_copies]
    if database_size_changed and database_entry is None:
        additions_sizes.append((database_id, len(updated_database)))
    output_sizes: list[int] = []
    current_size = _output_size_with_changes(
        leaf,
        replacement_sizes,
        additions_sizes,
        removed_ids=removed_ids,
        id_mapping=renamed_ids,
    )
    output_sizes.append(current_size)
    for layout, parent_ref in zip(layouts[1:], reversed(archive.parents), strict=True):
        current_size = _output_size(layout, parent_ref.entry_id, current_size)
        output_sizes.append(current_size)

    total = sum(entry.size for _source, entry, _target_id, _name in prepared_copies)
    if database_size_changed:
        total += len(updated_database)
    total += sum(output_sizes) + output_sizes[-1]
    completed = 0
    last_progress_at = 0.0
    last_progress_bytes = 0

    def report(amount: int) -> None:
        nonlocal completed, last_progress_at, last_progress_bytes
        completed += amount
        now = time.monotonic()
        if progress and (
            completed >= total
            or completed - last_progress_bytes >= 4 * 1024 * 1024
            or now - last_progress_at >= 0.15
        ):
            progress(completed, total)
            last_progress_at = now
            last_progress_bytes = completed

    if progress:
        progress(0, total)

    temporary_paths: list[Path] = []
    sibling_path: Path | None = None
    try:
        additions: list[tuple[int, Path]] = []
        source_paths: set[Path] = set()
        for index, (source_archive, entry, target_id, _name) in enumerate(prepared_copies):
            source_path = source_archive.path.resolve()
            if source_path not in source_paths:
                source_stat = source_path.stat()
                if (source_stat.st_size, source_stat.st_mtime_ns) != source_archive.file_signature:
                    raise ExternalFileChangedError(f"The source MIX archive changed: {source_path}")
                source_paths.add(source_path)
            snapshot = _temporary_path(temporary_root, f"copied-entry-{index:08d}-")
            temporary_paths.append(snapshot)
            _copy_mix_entry_to_path(source_archive, entry, snapshot, report, cancellation_requested)
            additions.append((target_id, snapshot))
        replacements: dict[int, Path] = {}
        if database_size_changed:
            database_snapshot = _temporary_path(temporary_root, "local-mix-database-")
            temporary_paths.append(database_snapshot)
            _write_bytes(database_snapshot, updated_database, report, cancellation_requested)
            if database_entry is not None:
                replacements[database_id] = database_snapshot
            else:
                additions.append((database_id, database_snapshot))

        replacement_path = _temporary_path(temporary_root, "edited-mix-")
        temporary_paths.append(replacement_path)
        _rewrite_archive_with_changes(
            leaf,
            replacements,
            additions,
            replacement_path,
            expected_size=output_sizes[0],
            report=report,
            cancellation_requested=cancellation_requested,
            removed_ids=removed_ids,
            id_mapping=renamed_ids,
        )
        for index, (layout, parent_ref) in enumerate(
            zip(layouts[1:], reversed(archive.parents), strict=True),
            start=1,
        ):
            _check_cancelled(cancellation_requested)
            output_path = _temporary_path(temporary_root, "edited-parent-mix-")
            temporary_paths.append(output_path)
            _rewrite_archive_range(
                layout,
                parent_ref.entry_id,
                replacement_path,
                output_path,
                expected_size=output_sizes[index],
                report=report,
                cancellation_requested=cancellation_requested,
            )
            replacement_path = output_path

        _check_cancelled(cancellation_requested)
        sibling_path = _temporary_path(root_path.parent, ".mix-browser-edit-", suffix=".tmp")
        _copy_file(replacement_path, sibling_path, report, cancellation_requested)
        try:
            shutil.copystat(root_path, sibling_path)
            os.utime(sibling_path, None)
        except OSError:
            pass
        latest = root_path.stat()
        if (latest.st_size, latest.st_mtime_ns) != expected_archive_signature:
            raise ExternalFileChangedError("The MIX archive changed while the edit was prepared.")
        for source_path in source_paths:
            if source_path == root_path.resolve():
                continue
            source_stat = source_path.stat()
            source_archive = next(item[0] for item in prepared_copies if item[0].path.resolve() == source_path)
            if (source_stat.st_size, source_stat.st_mtime_ns) != source_archive.file_signature:
                raise ExternalFileChangedError(f"The source MIX archive changed while copying: {source_path}")
        _check_cancelled(cancellation_requested)
        os.replace(sibling_path, root_path)
        sibling_path = None
        updated_stat = root_path.stat()
        if progress:
            progress(total, total)
        removed_names = tuple(
            existing_entries[file_id].name or f"Unknown (0x{file_id:08X})"
            for file_id in remove_ids
        )
        copied_labels = tuple(
            name or f"0x{target_id:08X}"
            for _source, _entry, target_id, name in prepared_copies
        )
        return (
            (updated_stat.st_size, updated_stat.st_mtime_ns),
            removed_names,
            tuple(renamed_names),
            copied_labels,
        )
    finally:
        if sibling_path is not None:
            sibling_path.unlink(missing_ok=True)
        for path in temporary_paths:
            path.unlink(missing_ok=True)


def _build_archive_chain(
    archive: MixArchiveIndex,
    entry_id: int,
) -> list[tuple[_ArchiveLayout, int]]:
    chain: list[tuple[MixArchiveIndex, int]] = [(archive, entry_id)]
    for index in range(len(archive.parents) - 1, -1, -1):
        parent_ref = archive.parents[index]
        parent_archive = open_mix_archive(
            archive.path,
            detect_types=False,
            source_offset=parent_ref.source_offset,
            source_size=parent_ref.source_size,
            parents=archive.parents[:index],
        )
        chain.append((parent_archive, parent_ref.entry_id))
    return [(_read_layout(item), target_id) for item, target_id in chain]


def _build_archive_layout_chain(archive: MixArchiveIndex) -> list[_ArchiveLayout]:
    layouts = [_read_layout(archive)]
    for index in range(len(archive.parents) - 1, -1, -1):
        parent_ref = archive.parents[index]
        parent_archive = open_mix_archive(
            archive.path,
            detect_types=False,
            source_offset=parent_ref.source_offset,
            source_size=parent_ref.source_size,
            parents=archive.parents[:index],
        )
        layouts.append(_read_layout(parent_archive))
    return layouts


def _read_layout(archive: MixArchiveIndex) -> _ArchiveLayout:
    source_start = archive.source_offset
    source_end = source_start + archive.source_size
    with archive.path.open("rb") as source:
        source.seek(source_start)
        prefix = source.read(min(92, archive.source_size))
        if len(prefix) < 10:
            raise MixFormatError("The MIX header is incomplete.")

        first_word = struct.unpack_from("<H", prefix, 0)[0]
        if first_word:
            count = first_word
            data_size = struct.unpack_from("<I", prefix, 2)[0]
            table_start = source_start + 6
            data_start = table_start + count * 12
            kind = "cnc"
            flags = 0
            encrypted_key = b""
            checksum_size = 0
        else:
            flags = struct.unpack_from("<H", prefix, 2)[0]
            count = struct.unpack_from("<H", prefix, 4)[0]
            data_size = struct.unpack_from("<I", prefix, 6)[0]
            if flags & ~0x3:
                raise MixFormatError("The MIX archive uses unsupported header flags.")
            if flags & 0x2:
                if Blowfish is None:
                    raise MixFormatError("Encrypted MIX archives require PyCryptodome.")
                if len(prefix) < 92:
                    raise MixFormatError("The encrypted MIX header is incomplete.")
                encrypted_key = prefix[4:84]
                key = _decrypt_mix_blowfish_key(encrypted_key)
                cipher = Blowfish.new(key, Blowfish.MODE_ECB)
                first_table_block = cipher.decrypt(prefix[84:92])
                parsed_count, data_size = struct.unpack_from("<HI", first_table_block, 0)
                if parsed_count != count:
                    raise MixFormatError("The encrypted MIX table count is invalid.")
                encrypted_size = (6 + count * 12 + 7) // 8 * 8
                source.seek(source_start + 84)
                encrypted_table = source.read(encrypted_size)
                if len(encrypted_table) != encrypted_size:
                    raise MixFormatError("The encrypted MIX table is incomplete.")
                table = cipher.decrypt(encrypted_table)
                rows_start = 6
                table_start = source_start + 84
                data_start = table_start + encrypted_size
                kind = "encrypted"
                checksum_size = 20 if flags & 0x1 else 0
                return _layout_from_rows(
                    archive,
                    source_end,
                    kind,
                    flags,
                    count,
                    data_size,
                    data_start,
                    table[rows_start : rows_start + count * 12],
                    encrypted_key,
                    checksum_size,
                )
            if flags & ~0x1:
                raise MixFormatError("The MIX archive uses unsupported header flags.")
            table_start = source_start + 10
            data_start = table_start + count * 12
            kind = "standard"
            encrypted_key = b""
            checksum_size = 20 if flags & 0x1 else 0

        if data_start > source_end:
            raise MixFormatError("The MIX entry table extends beyond its archive range.")
        source.seek(table_start)
        table = source.read(count * 12)
        if len(table) != count * 12:
            raise MixFormatError("The MIX entry table is incomplete.")
        return _layout_from_rows(
            archive,
            source_end,
            kind,
            flags,
            count,
            data_size,
            data_start,
            table,
            encrypted_key,
            checksum_size,
        )


def _layout_from_rows(
    archive: MixArchiveIndex,
    source_end: int,
    kind: str,
    flags: int,
    count: int,
    data_size: int,
    data_start: int,
    table: bytes,
    encrypted_key: bytes,
    checksum_size: int,
) -> _ArchiveLayout:
    rows = tuple(struct.unpack_from("<III", table, index * 12) for index in range(count))
    ids = [file_id for file_id, _offset, _size in rows]
    if len(ids) != len(set(ids)) or set(ids) != {entry.file_id for entry in archive.entries}:
        raise MixFormatError("The MIX entry table contains duplicate or unrecognized entries.")
    available_data_size = source_end - data_start - checksum_size
    if data_size > available_data_size:
        indexed_data_size = max((offset + size for _file_id, offset, size in rows), default=0)
        if available_data_size < 0 or indexed_data_size > available_data_size or not indexed_data_size:
            raise MixFormatError("The MIX data extends beyond its archive range.")
        # Rebuild from verified entry ranges when a MIX header overstates its data section.
        data_size = indexed_data_size
    if any(offset + size > data_size for _file_id, offset, size in rows):
        raise MixFormatError("A MIX entry extends beyond the declared data section.")
    return _ArchiveLayout(
        archive,
        kind,
        flags,
        count,
        data_size,
        data_start,
        rows,
        encrypted_key,
        checksum_size,
    )


# @arch mix-browser.archive-name-hash utility | en: Resolves MIX file IDs using the target archive's hash format | zh: 按目标归档的哈希格式计算 MIX 文件 ID
def mix_file_ids_for_archive(archive: MixArchiveIndex, names: Sequence[str]) -> tuple[int, ...]:
    with archive.path.open("rb") as source:
        source.seek(archive.source_offset)
        first_word = source.read(2)
    if len(first_word) != 2:
        raise MixFormatError("The MIX header is incomplete.")
    legacy_hash = struct.unpack("<H", first_word)[0] != 0
    return tuple(
        _mix_file_hashes(name)[0 if legacy_hash else 1]
        for name in names
    )


def _output_size(layout: _ArchiveLayout, target_id: int, replacement_size: int) -> int:
    if replacement_size < 0 or replacement_size > _MAX_MIX_DATA_SIZE:
        raise ValueError("The edited file is too large for a MIX entry.")
    target_found = False
    total_data_size = 0
    for file_id, _offset, size in layout.rows:
        if file_id == target_id:
            total_data_size += replacement_size
            target_found = True
        else:
            total_data_size += size
    if not target_found:
        raise MixFormatError(f"MIX entry 0x{target_id:08X} is missing.")
    if total_data_size > _MAX_MIX_DATA_SIZE:
        raise ValueError("The updated MIX data section exceeds the format limit.")
    return _header_size(layout, layout.count) + total_data_size + layout.checksum_size + layout.trailing_size


def _output_size_with_changes(
    layout: _ArchiveLayout,
    replacement_sizes: Mapping[int, int],
    additions: Sequence[tuple[int, int]],
    *,
    removed_ids: set[int] | frozenset[int] = frozenset(),
    id_mapping: Mapping[int, int] | None = None,
) -> int:
    mapping = id_mapping or {}
    row_ids = {file_id for file_id, _offset, _size in layout.rows}
    if not set(replacement_sizes).issubset(row_ids):
        raise MixFormatError("A replacement MIX entry is missing.")
    if not removed_ids.issubset(row_ids) or removed_ids.intersection(replacement_sizes):
        raise MixFormatError("A removed MIX entry is missing or also replaced.")
    if not set(mapping).issubset(row_ids - removed_ids):
        raise MixFormatError("A renamed MIX entry is missing or also removed.")
    addition_ids = [file_id for file_id, _size in additions]
    resulting_ids = {
        mapping.get(file_id, file_id)
        for file_id in row_ids - removed_ids
    }
    if (
        len(resulting_ids) != len(row_ids - removed_ids)
        or len(addition_ids) != len(set(addition_ids))
        or resulting_ids.intersection(addition_ids)
    ):
        raise MixFormatError("The new MIX entries contain duplicate IDs.")
    count = len(resulting_ids) + len(additions)
    if count > 0xFFFF:
        raise ValueError("The MIX entry table exceeds the format limit.")
    total_data_size = sum(
        replacement_sizes.get(file_id, size)
        for file_id, _offset, size in layout.rows
        if file_id not in removed_ids
    ) + sum(size for _file_id, size in additions)
    if any(size < 0 for size in (*replacement_sizes.values(), *(size for _id, size in additions))):
        raise ValueError("A MIX entry cannot have a negative size.")
    if total_data_size > _MAX_MIX_DATA_SIZE:
        raise ValueError("The updated MIX data section exceeds the format limit.")
    return _header_size(layout, count) + total_data_size + layout.checksum_size + layout.trailing_size


def _header_size(layout: _ArchiveLayout, count: int) -> int:
    if layout.kind == "cnc":
        return 6 + count * 12
    if layout.kind == "standard":
        return 10 + count * 12
    encrypted_table_size = (6 + count * 12 + 7) // 8 * 8
    return 84 + encrypted_table_size


def _rewrite_archive_range(
    layout: _ArchiveLayout,
    target_id: int,
    replacement_path: Path,
    destination: Path,
    *,
    expected_size: int,
    report: Callable[[int], None],
    cancellation_requested: CancellationCheck | None,
) -> None:
    _rewrite_archive_with_changes(
        layout,
        {target_id: replacement_path},
        (),
        destination,
        expected_size=expected_size,
        report=report,
        cancellation_requested=cancellation_requested,
    )


def _rewrite_archive_with_changes(
    layout: _ArchiveLayout,
    replacements: Mapping[int, Path],
    additions: Sequence[tuple[int, Path]],
    destination: Path,
    *,
    expected_size: int,
    report: Callable[[int], None],
    cancellation_requested: CancellationCheck | None,
    removed_ids: set[int] | frozenset[int] = frozenset(),
    id_mapping: Mapping[int, int] | None = None,
) -> None:
    mapping = id_mapping or {}
    replacement_sizes = {file_id: path.stat().st_size for file_id, path in replacements.items()}
    addition_sizes = [(file_id, path.stat().st_size) for file_id, path in additions]
    expected_output_size = _output_size_with_changes(
        layout,
        replacement_sizes,
        addition_sizes,
        removed_ids=removed_ids,
        id_mapping=mapping,
    )
    output_rows: list[tuple[int, int, int | None, Path | None]] = []
    for file_id, old_offset, old_size in layout.rows:
        if file_id in removed_ids:
            continue
        replacement_path = replacements.get(file_id)
        output_rows.append(
            (
                mapping.get(file_id, file_id),
                replacement_sizes.get(file_id, old_size),
                old_offset,
                replacement_path,
            )
        )
    for file_id, path in additions:
        output_rows.append((file_id, path.stat().st_size, None, path))

    if layout.kind in {"standard", "encrypted"}:
        # RA2/YR CRC32 MIX tables use signed-hash ordering for game lookup.
        output_rows.sort(key=lambda row: _signed_mix_id(row[0]))

    new_rows: list[tuple[int, int, int]] = []
    data_size = 0
    for file_id, entry_size, _old_offset, _replacement_path in output_rows:
        new_rows.append((file_id, data_size, entry_size))
        data_size += entry_size
    table = b"".join(struct.pack("<III", *row) for row in new_rows)
    count = len(new_rows)
    if layout.kind == "cnc":
        header = struct.pack("<HI", count, data_size)
    elif layout.kind == "standard":
        header = struct.pack("<HHHI", 0, layout.flags, count, data_size)
    else:
        key = _decrypt_mix_blowfish_key(layout.encrypted_key)
        cipher = Blowfish.new(key, Blowfish.MODE_ECB)
        plain_table = struct.pack("<HI", count, data_size) + table
        padded_table = plain_table + b"\0" * ((-len(plain_table)) % 8)
        header = _read_exact_range(layout.archive.path, layout.archive.source_offset, 84)
        header += cipher.encrypt(padded_table)
    if layout.kind != "encrypted":
        header += table

    if expected_size != expected_output_size:
        raise ValueError("The MIX output size changed unexpectedly during reconstruction.")
    checksum = hashlib.sha1() if layout.checksum_size else None
    created = False
    source_path = layout.archive.path
    try:
        with destination.open("xb") as output:
            created = True
            _write_output(output, header, checksum, report)
            with source_path.open("rb") as source:
                for _file_id, entry_size, old_offset, replacement_path in output_rows:
                    _check_cancelled(cancellation_requested)
                    if replacement_path is not None:
                        with replacement_path.open("rb") as replacement:
                            _copy_stream(
                                replacement,
                                output,
                                entry_size,
                                checksum,
                                report,
                                cancellation_requested,
                            )
                    else:
                        if old_offset is None:
                            raise MixFormatError("A MIX entry has no source data.")
                        source.seek(layout.data_start + old_offset)
                        _copy_stream(source, output, entry_size, checksum, report, cancellation_requested)
                if checksum is not None:
                    output.write(checksum.digest())
                    report(layout.checksum_size)
                if layout.trailing_size:
                    source.seek(layout.data_start + layout.data_size + layout.checksum_size)
                    _copy_stream(
                        source,
                        output,
                        layout.trailing_size,
                        None,
                        report,
                        cancellation_requested,
                    )
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


def _copy_and_verify_source(
    source_path: Path,
    destination: Path,
    expected_signature: tuple[int, int],
    report: Callable[[int], None],
    cancellation_requested: CancellationCheck | None,
) -> None:
    before = source_path.stat()
    if (before.st_size, before.st_mtime_ns) != expected_signature:
        raise ExternalFileChangedError(f"The source file changed before copying: {source_path}")
    _copy_file(source_path, destination, report, cancellation_requested)
    after = source_path.stat()
    if (after.st_size, after.st_mtime_ns) != expected_signature:
        destination.unlink(missing_ok=True)
        raise ExternalFileChangedError(f"The source file changed while copying: {source_path}")


def _write_bytes(
    path: Path,
    data: bytes,
    report: Callable[[int], None],
    cancellation_requested: CancellationCheck | None,
) -> None:
    _check_cancelled(cancellation_requested)
    created = False
    try:
        with path.open("xb") as output:
            created = True
            output.write(data)
            report(len(data))
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def _is_valid_mix_filename(name: str) -> bool:
    return is_readable_mix_name(name) and Path(name).name == name


def _ordered_local_database_names(
    names: Sequence[str],
    *,
    hash_index: int,
) -> list[str]:
    unique_names: dict[str, str] = {}
    for name in names:
        unique_names.setdefault(name.casefold(), name)
    unique_names.setdefault(
        LOCAL_MIX_DATABASE_NAME.casefold(),
        LOCAL_MIX_DATABASE_NAME,
    )
    return sorted(
        unique_names.values(),
        key=lambda name: _signed_mix_id(_mix_file_hashes(name)[hash_index]),
    )


def _signed_mix_id(file_id: int) -> int:
    return file_id - 0x100000000 if file_id & 0x80000000 else file_id


def _entry_collision_message(entry, file_id: int) -> str:
    name = entry.name or f"Unknown (0x{file_id:08X})"
    return f"A MIX entry with this name or ID already exists: {name}"


def _read_exact_range(path: Path, offset: int, size: int) -> bytes:
    with path.open("rb") as source:
        source.seek(offset)
        data = source.read(size)
    if len(data) != size:
        raise OSError("The MIX header is incomplete.")
    return data


def _copy_and_hash(
    source_path: Path,
    destination: Path,
    report: Callable[[int], None],
    cancellation_requested: CancellationCheck | None,
) -> tuple[str, int]:
    before = source_path.stat()
    digest = hashlib.sha256()
    copied = 0
    created = False
    try:
        with source_path.open("rb") as source, destination.open("xb") as output:
            created = True
            while block := source.read(_COPY_CHUNK_SIZE):
                _check_cancelled(cancellation_requested)
                output.write(block)
                digest.update(block)
                copied += len(block)
                report(len(block))
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    after = source_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        destination.unlink(missing_ok=True)
        raise ExternalFileChangedError("The edited file changed while write-back was starting.")
    return digest.hexdigest(), copied


def _copy_file(
    source_path: Path,
    destination: Path,
    report: Callable[[int], None],
    cancellation_requested: CancellationCheck | None,
) -> None:
    created = False
    try:
        with source_path.open("rb") as source, destination.open("xb") as output:
            created = True
            while block := source.read(_COPY_CHUNK_SIZE):
                _check_cancelled(cancellation_requested)
                output.write(block)
                report(len(block))
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise


def _copy_mix_entry_to_path(
    archive: MixArchiveIndex,
    entry: MixEntry,
    destination: Path,
    report: Callable[[int], None],
    cancellation_requested: CancellationCheck | None,
) -> None:
    metadata = archive.path.stat()
    if (metadata.st_size, metadata.st_mtime_ns) != archive.file_signature:
        raise ExternalFileChangedError(f"The source MIX archive changed: {archive.path}")
    start = archive.data_start + entry.offset
    end = archive.source_offset + archive.source_size
    if entry.offset < 0 or entry.size < 0 or start + entry.size > end:
        raise MixFormatError("The copied MIX entry extends beyond its archive range.")
    created = False
    try:
        with archive.path.open("rb") as source, destination.open("xb") as output:
            created = True
            source.seek(start)
            _copy_stream(source, output, entry.size, None, report, cancellation_requested)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    latest = archive.path.stat()
    if (latest.st_size, latest.st_mtime_ns) != archive.file_signature:
        destination.unlink(missing_ok=True)
        raise ExternalFileChangedError(f"The source MIX archive changed while copying: {archive.path}")


def _copy_stream(
    source,
    destination,
    size: int,
    checksum,
    report: Callable[[int], None],
    cancellation_requested: CancellationCheck | None,
) -> None:
    remaining = size
    while remaining:
        _check_cancelled(cancellation_requested)
        block = source.read(min(_COPY_CHUNK_SIZE, remaining))
        if not block:
            raise OSError("An archive entry ended before its declared size.")
        destination.write(block)
        if checksum is not None:
            checksum.update(block)
        remaining -= len(block)
        report(len(block))


def _write_output(output, data: bytes, checksum, report: Callable[[int], None]) -> None:
    output.write(data)
    if checksum is not None:
        checksum.update(data)
    report(len(data))


def _temporary_path(directory: Path, prefix: str, *, suffix: str = ".tmp") -> Path:
    descriptor, raw_path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=directory)
    os.close(descriptor)
    path = Path(raw_path)
    path.unlink()
    return path


def _check_cancelled(cancellation_requested: CancellationCheck | None) -> None:
    if cancellation_requested and cancellation_requested():
        raise InterruptedError("The MIX update was cancelled.")
