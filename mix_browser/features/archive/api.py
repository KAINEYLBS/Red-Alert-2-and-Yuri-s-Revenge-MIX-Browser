from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

from mix_browser.features.archive.domain import (
    LOCAL_MIX_DATABASE_NAME,
    MixEntry,
    MixFormatError,
    is_readable_mix_name,
)
from mix_browser.features.archive.loader import MixArchiveLoader
from mix_browser.features.archive.name_catalog import (
    community_name_database_size_bytes,
    download_community_name_database,
)
from mix_browser.features.archive.source import copy_mix_entry_and_hash, hash_file, hash_mix_entry
from mix_browser.features.archive.type_detection import detect_content_type
from mix_browser.features.archive.writer import (
    ExternalFileChangedError,
    NoExternalChangesError,
    add_files_to_mix,
    create_empty_mix_archive,
    edit_mix_entries,
    mix_file_ids_for_archive,
    write_back_mix_entry,
)
from mix_browser.shared.application_errors import ApplicationApiError

__all__ = ["MixArchiveApplication"]


# @arch mix-browser.archive-api component | en: Exposes stable archive inspection and editing use cases | zh: 提供稳定的归档检查与编辑用例
class MixArchiveApplication:
    def __init__(self, loader: MixArchiveLoader) -> None:
        self._loader = loader

    # @arch mix-browser.archive-download-community-names service | en: Installs the optional CnCNet name database beside the application | zh: 将可选的 CnCNet 名称数据库下载到程序目录
    def download_community_name_database(
        self,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        path = download_community_name_database(
            progress=progress,
            cancellation_requested=cancellation_requested,
        )
        self._loader.reload_name_sources(community=True)
        return {"path": str(path), "size_bytes": path.stat().st_size}

    # @arch mix-browser.archive-community-name-database-size service | en: Returns the current remote CnCNet database file size | zh: 返回 CnCNet 社区数据库当前的远程文件大小
    def community_name_database_size_bytes(self) -> int:
        return community_name_database_size_bytes()

    # @arch mix-browser.create-empty-mix service | en: Creates an empty standard MIX archive and optionally replaces an existing path | zh: 创建标准空 MIX 归档并可选择替换现有路径
    def create_empty_mix(
        self,
        destination: Path,
        *,
        overwrite: bool = False,
    ) -> dict[str, object]:
        try:
            path = create_empty_mix_archive(destination, overwrite=overwrite)
        except FileExistsError as exc:
            raise ApplicationApiError("output_exists", f"The output path already exists: {destination}") from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except OSError as exc:
            raise self._io_error(exc, "The empty MIX archive could not be created.") from exc
        except ValueError as exc:
            raise ApplicationApiError("invalid_output", str(exc)) from exc
        return {
            "archive_path": str(path),
            "entry_count": 0,
            "size_bytes": 10,
        }

    # @arch mix-browser.create-mix-from-files service | en: Creates a populated MIX archive from files and atomically installs it at the destination | zh: 从文件创建完整 MIX 归档并原子安装到目标位置
    def create_mix_from_files(
        self,
        destination: Path,
        source_paths: tuple[Path, ...],
        *,
        item_names: tuple[str, ...] | None = None,
        overwrite: bool = False,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        if not source_paths:
            raise ApplicationApiError("invalid_input", "At least one source file is required.")
        if item_names is not None and len(item_names) != len(source_paths):
            raise ApplicationApiError(
                "invalid_input",
                "The number of MIX item names must match the number of source files.",
            )

        requested_path = destination.expanduser()
        if requested_path.suffix.casefold() != ".mix":
            raise ApplicationApiError("invalid_output", "The destination must use the .mix extension.")
        parent = requested_path.parent.resolve()
        if not parent.is_dir():
            raise ApplicationApiError("not_directory", f"The destination is not a directory: {parent}")
        target = parent / requested_path.name
        source_keys = {os.path.normcase(str(path.expanduser().resolve())) for path in source_paths}
        if os.path.normcase(str(target.resolve(strict=False))) in source_keys:
            raise ApplicationApiError("invalid_input", "The new MIX archive cannot replace one of its source files.")

        initial_signature: tuple[int, int] | None = None
        if os.path.lexists(target):
            if not overwrite:
                raise ApplicationApiError("output_exists", f"The output path already exists: {target}")
            if target.is_symlink() or not target.is_file():
                raise ApplicationApiError("invalid_output", f"The output path is not a regular file: {target}")
            metadata = target.stat()
            initial_signature = (metadata.st_size, metadata.st_mtime_ns)

        try:
            with tempfile.TemporaryDirectory(prefix=".mix-browser-create-", dir=parent) as temporary_root:
                staged_path = Path(temporary_root) / target.name
                self.create_empty_mix(staged_path)
                added = self.add_files(
                    staged_path,
                    source_paths,
                    item_names=item_names,
                    progress=progress,
                    cancellation_requested=cancellation_requested,
                )
                if cancellation_requested and cancellation_requested():
                    raise InterruptedError("MIX creation was cancelled.")

                if initial_signature is None:
                    if os.path.lexists(target):
                        raise ApplicationApiError("conflict", f"The output path appeared during creation: {target}")
                    os.rename(staged_path, target)
                else:
                    try:
                        current = target.lstat()
                    except OSError as exc:
                        raise ApplicationApiError("conflict", f"The output path changed during creation: {target}") from exc
                    if not stat.S_ISREG(current.st_mode):
                        raise ApplicationApiError("conflict", f"The output path changed during creation: {target}")
                    if (current.st_size, current.st_mtime_ns) != initial_signature:
                        raise ApplicationApiError("conflict", f"The output path changed during creation: {target}")
                    os.replace(staged_path, target)
        except ApplicationApiError:
            raise
        except InterruptedError:
            raise
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except (MixFormatError, ValueError) as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except OSError as exc:
            raise self._io_error(exc, "The MIX archive could not be created from the selected files.") from exc

        return {
            "archive_path": str(target),
            "added_names": list(added["added_names"]),
            "entry_count": len(added["added_names"]),
            "size_bytes": target.stat().st_size,
        }

    # @arch mix-browser.create-nested-mix-from-entries service | en: Packs selected entries into a nested MIX and atomically adds or moves it within the parent archive | zh: 将选中条目打包为内嵌 MIX，并在父归档中原子添加或移动
    def create_mix_from_archive_entries(
        self,
        archive_path: Path,
        name: str,
        entry_ids: tuple[int, ...],
        *,
        parent_entry_ids: tuple[int, ...] = (),
        move_entries: bool = False,
        overwrite: bool = False,
        expected_archive_signature: tuple[int, int] | None = None,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        if not entry_ids:
            raise ApplicationApiError("invalid_input", "At least one MIX entry is required.")
        if len(entry_ids) != len(set(entry_ids)):
            raise ApplicationApiError("invalid_input", "MIX entry IDs must be unique.")
        if (
            Path(name).suffix.casefold() != ".mix"
            or Path(name).name != name
            or not is_readable_mix_name(name)
            or name.casefold() == LOCAL_MIX_DATABASE_NAME.casefold()
        ):
            raise ApplicationApiError("invalid_output", "The nested archive name must be a valid .mix file name.")

        parent_archive = self._load_archive(archive_path, parent_entry_ids)
        if (
            expected_archive_signature is not None
            and parent_archive.file_signature != expected_archive_signature
        ):
            raise ApplicationApiError("conflict", "The MIX archive changed after the operation was confirmed.")
        selected_entries = tuple(
            self._find_entry(parent_archive.entries, entry_id) for entry_id in entry_ids
        )
        reserved_id = mix_file_ids_for_archive(parent_archive, (LOCAL_MIX_DATABASE_NAME,))[0]
        if any(entry.file_id == reserved_id for entry in selected_entries):
            raise ApplicationApiError("invalid_input", "The embedded MIX name database cannot be packed as a regular item.")

        try:
            with tempfile.TemporaryDirectory(prefix="mix-browser-nested-mix-") as temporary_root:
                nested_path = Path(temporary_root) / name
                create_empty_mix_archive(nested_path)
                nested_archive = self._load_archive(nested_path, ())
                self.edit_entries(
                    nested_path,
                    source_archive_path=parent_archive.path,
                    source_parent_entry_ids=parent_entry_ids,
                    copy_entry_ids=entry_ids,
                    expected_archive_signature=nested_archive.file_signature,
                    progress=progress,
                    cancellation_requested=cancellation_requested,
                )
                if cancellation_requested and cancellation_requested():
                    raise InterruptedError("Nested MIX creation was cancelled.")
                result = self.edit_entries(
                    parent_archive.path,
                    parent_entry_ids=parent_entry_ids,
                    remove_entry_ids=entry_ids if move_entries else (),
                    add_file_paths=(nested_path,),
                    overwrite_added_files=overwrite,
                    expected_archive_signature=parent_archive.file_signature,
                    progress=progress,
                    cancellation_requested=cancellation_requested,
                )
        except ApplicationApiError:
            raise
        except InterruptedError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("entry_not_found", str(exc)) from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except (MixFormatError, ValueError) as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except OSError as exc:
            raise self._io_error(exc, "The selected entries could not be packed into a nested MIX.") from exc

        return {
            "archive_path": str(result["archive_path"]),
            "parent_entry_ids": list(parent_entry_ids),
            "added_names": list(result["added_file_names"]),
            "removed_names": list(result["removed_names"]),
            "archive_modified_ns": result["archive_modified_ns"],
        }

    def inspect(
        self,
        archive_path: Path,
        *,
        parent_entry_ids: tuple[int, ...] = (),
        name_game: str | None = None,
    ) -> dict[str, object]:
        archive = self._load_archive(
            archive_path,
            parent_entry_ids,
            name_game=name_game,
        )
        return {
            "path": str(archive.path),
            "source_offset": archive.source_offset,
            "source_size_bytes": archive.source_size,
            "entry_count": len(archive.entries),
            "parent_entry_ids": [parent.entry_id for parent in archive.parents],
            "entries": [self._entry_record(entry) for entry in archive.entries],
        }

    def extract(
        self,
        archive_path: Path,
        entry_id: int,
        destination: Path,
        *,
        parent_entry_ids: tuple[int, ...] = (),
    ) -> dict[str, object]:
        archive = self._load_archive(archive_path, parent_entry_ids)
        entry = self._find_entry(archive.entries, entry_id)
        output_path = destination.expanduser()
        if output_path.resolve() == archive.path.resolve():
            raise ApplicationApiError("invalid_output", "The output path cannot replace the source MIX archive.")
        extracted = False
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            digest = copy_mix_entry_and_hash(archive, entry, output_path)
            extracted = True
            self._ensure_archive_unchanged(archive.path, archive.file_signature)
        except FileExistsError as exc:
            raise ApplicationApiError("output_exists", f"The output file already exists: {output_path}") from exc
        except ApplicationApiError:
            if extracted:
                output_path.unlink(missing_ok=True)
            raise
        except ValueError as exc:
            if extracted:
                output_path.unlink(missing_ok=True)
            raise ApplicationApiError("invalid_entry", str(exc)) from exc
        except OSError as exc:
            if extracted:
                output_path.unlink(missing_ok=True)
            raise self._io_error(exc, "The MIX entry could not be extracted.") from exc
        return {
            "archive_path": str(archive.path),
            "entry_id": entry.file_id,
            "name": entry.name,
            "output_path": str(output_path.resolve()),
            "size_bytes": entry.size,
            "sha256": digest,
        }

    def replace(
        self,
        archive_path: Path,
        entry_id: int,
        replacement_path: Path,
        *,
        parent_entry_ids: tuple[int, ...] = (),
    ) -> dict[str, object]:
        archive = self._load_archive(archive_path, parent_entry_ids)
        entry = self._find_entry(archive.entries, entry_id)
        replacement = replacement_path.expanduser().resolve()
        if replacement == archive.path.resolve():
            raise ApplicationApiError("invalid_input", "The replacement file cannot be the MIX archive itself.")
        try:
            original_hash = hash_mix_entry(archive, entry)
            replacement_hash, _replacement_signature = hash_file(replacement)
            with tempfile.TemporaryDirectory(prefix="mix-browser-api-") as temporary_root:
                size, modified_ns = write_back_mix_entry(
                    archive,
                    entry.file_id,
                    replacement,
                    Path(temporary_root),
                    original_content_hash=original_hash,
                    expected_content_hash=replacement_hash,
                    expected_archive_signature=archive.file_signature,
                )
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", str(exc)) from exc
        except NoExternalChangesError as exc:
            raise ApplicationApiError("no_changes", str(exc)) from exc
        except ExternalFileChangedError as exc:
            raise ApplicationApiError("conflict", str(exc)) from exc
        except (MixFormatError, ValueError) as exc:
            raise ApplicationApiError("invalid_mix", str(exc)) from exc
        except OSError as exc:
            raise self._io_error(exc, "The MIX entry could not be replaced.") from exc
        return {
            "archive_path": str(archive.path),
            "entry_id": entry.file_id,
            "replacement_path": str(replacement),
            "size_bytes": size,
            "archive_modified_ns": modified_ns,
        }

    def add_files(
        self,
        archive_path: Path,
        source_paths: tuple[Path, ...],
        *,
        item_names: tuple[str, ...] | None = None,
        parent_entry_ids: tuple[int, ...] = (),
        overwrite: bool = False,
        expected_archive_signature: tuple[int, int] | None = None,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        if not source_paths:
            raise ApplicationApiError("invalid_input", "At least one source file is required.")
        archive = self._load_archive(archive_path, parent_entry_ids)
        if (
            expected_archive_signature is not None
            and archive.file_signature != expected_archive_signature
        ):
            raise ApplicationApiError("conflict", "The MIX archive changed after the add operation was confirmed.")
        try:
            with tempfile.TemporaryDirectory(prefix="mix-browser-add-") as temporary_root:
                signature, added_names, replaced_names = add_files_to_mix(
                    archive,
                    source_paths,
                    Path(temporary_root),
                    item_names=item_names,
                    overwrite=overwrite,
                    expected_archive_signature=archive.file_signature,
                    progress=progress,
                    cancellation_requested=cancellation_requested,
                )
        except InterruptedError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", str(exc)) from exc
        except FileExistsError as exc:
            raise ApplicationApiError("output_exists", str(exc)) from exc
        except ExternalFileChangedError as exc:
            raise ApplicationApiError("conflict", str(exc)) from exc
        except MixFormatError as exc:
            raise ApplicationApiError("invalid_mix", str(exc)) from exc
        except ValueError as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except OSError as exc:
            raise self._io_error(exc, "Files could not be added to the MIX archive.") from exc
        return {
            "archive_path": str(archive.path),
            "parent_entry_ids": list(parent_entry_ids),
            "added_names": list(added_names),
            "replaced_names": list(replaced_names),
            "archive_modified_ns": signature[1],
        }

    # @arch mix-browser.edit-mix-entries service | en: Deletes, renames, or copies entries in a MIX archive | zh: 删除、重命名或复制 MIX 归档中的条目
    def edit_entries(
        self,
        archive_path: Path,
        *,
        parent_entry_ids: tuple[int, ...] = (),
        remove_entry_ids: tuple[int, ...] = (),
        rename_entries: dict[int, str] | None = None,
        source_archive_path: Path | None = None,
        source_parent_entry_ids: tuple[int, ...] = (),
        copy_entry_ids: tuple[int, ...] = (),
        add_file_paths: tuple[Path, ...] = (),
        overwrite_added_files: bool = False,
        expected_archive_signature: tuple[int, int] | None = None,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        if not remove_entry_ids and not rename_entries and not copy_entry_ids and not add_file_paths:
            raise ApplicationApiError("invalid_input", "At least one MIX edit is required.")
        target_archive = self._load_archive(archive_path, parent_entry_ids)
        if (
            expected_archive_signature is not None
            and target_archive.file_signature != expected_archive_signature
        ):
            raise ApplicationApiError("conflict", "The MIX archive changed after the edit was confirmed.")
        source_archive = target_archive
        if copy_entry_ids:
            if source_archive_path is not None:
                source_archive = self._load_archive(source_archive_path, source_parent_entry_ids)
            elif source_parent_entry_ids:
                source_archive = self._load_archive(archive_path, source_parent_entry_ids)
            copy_entries = tuple(
                (source_archive, self._find_entry(source_archive.entries, entry_id))
                for entry_id in copy_entry_ids
            )
        else:
            copy_entries = ()
        try:
            with tempfile.TemporaryDirectory(prefix="mix-browser-edit-") as temporary_root:
                signature, removed, renamed, copied, added_files = edit_mix_entries(
                    target_archive,
                    temporary_root=Path(temporary_root),
                    remove_ids=remove_entry_ids,
                    rename_entries=rename_entries,
                    copy_entries=copy_entries,
                    add_file_paths=add_file_paths,
                    overwrite_added_files=overwrite_added_files,
                    expected_archive_signature=target_archive.file_signature,
                    progress=progress,
                    cancellation_requested=cancellation_requested,
                )
        except InterruptedError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("entry_not_found", str(exc)) from exc
        except FileExistsError as exc:
            raise ApplicationApiError("entry_exists", str(exc)) from exc
        except ExternalFileChangedError as exc:
            raise ApplicationApiError("conflict", str(exc)) from exc
        except MixFormatError as exc:
            raise ApplicationApiError("invalid_mix", str(exc)) from exc
        except ValueError as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except OSError as exc:
            raise self._io_error(exc, "The MIX entries could not be edited.") from exc
        return {
            "archive_path": str(target_archive.path),
            "parent_entry_ids": list(parent_entry_ids),
            "removed_names": list(removed),
            "renamed_names": list(renamed),
            "copied_names": list(copied),
            "added_file_names": list(added_files),
            "archive_modified_ns": signature[1],
        }

    def detect_type(self, path: Path) -> dict[str, object]:
        file_path = path.expanduser()
        try:
            metadata = file_path.stat()
            if not file_path.is_file():
                raise ApplicationApiError("invalid_input", "The path must point to a regular file.")
            with file_path.open("rb") as source:
                prefix = source.read(4096)
        except ApplicationApiError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", f"File not found: {file_path}") from exc
        except OSError as exc:
            raise self._io_error(exc, "The file type could not be detected.") from exc
        return {
            "path": str(file_path.resolve()),
            "size_bytes": metadata.st_size,
            "content_type": detect_content_type(prefix, metadata.st_size),
        }

    def _load_archive(
        self,
        archive_path: Path,
        parent_entry_ids: tuple[int, ...],
        *,
        name_game: str | None = None,
    ):
        path = archive_path.expanduser()
        try:
            session = self._loader.create_session(name_game=name_game)
            archive = session.load(path)
            for entry_id in parent_entry_ids:
                entry = self._find_entry(archive.entries, entry_id)
                try:
                    archive = session.load_nested(archive, entry)
                except (MixFormatError, OSError, ValueError) as exc:
                    raise ApplicationApiError("invalid_nested_mix", str(exc)) from exc
            return archive
        except ApplicationApiError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", f"MIX archive not found: {path}") from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", f"The MIX archive cannot be read: {path}") from exc
        except MixFormatError as exc:
            raise ApplicationApiError("invalid_mix", str(exc)) from exc
        except ValueError as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except OSError as exc:
            raise self._io_error(exc, "The MIX archive could not be opened.") from exc

    @staticmethod
    def _find_entry(entries: tuple[MixEntry, ...], entry_id: int) -> MixEntry:
        if not 0 <= entry_id <= 0xFFFFFFFF:
            raise ApplicationApiError("invalid_input", "A MIX entry ID must be an unsigned 32-bit integer.")
        entry = next((candidate for candidate in entries if candidate.file_id == entry_id), None)
        if entry is None:
            raise ApplicationApiError("entry_not_found", f"MIX entry 0x{entry_id:08X} was not found.")
        return entry

    @staticmethod
    def _entry_record(entry: MixEntry) -> dict[str, object]:
        return {
            "file_id": entry.file_id,
            "id_hex": f"0x{entry.file_id:08X}",
            "name": entry.name or f"Unknown (0x{entry.file_id:08X})",
            "name_sources": list(entry.name_sources),
            "type": entry.file_type,
            "offset": entry.offset,
            "size_bytes": entry.size,
        }

    @staticmethod
    def _ensure_archive_unchanged(path: Path, expected_signature: tuple[int, int]) -> None:
        metadata = path.stat()
        if (metadata.st_size, metadata.st_mtime_ns) != expected_signature:
            raise ApplicationApiError("archive_changed", "The MIX archive changed during the operation.")

    @staticmethod
    def _io_error(error: OSError, fallback: str) -> ApplicationApiError:
        if isinstance(error, PermissionError):
            return ApplicationApiError("access_denied", str(error))
        return ApplicationApiError("io_error", str(error) or fallback)
