from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

from mix_browser.features.archive.domain import MixEntry, MixFormatError
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
        expected_archive_signature: tuple[int, int] | None = None,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        if not remove_entry_ids and not rename_entries and not copy_entry_ids:
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
                signature, removed, renamed, copied = edit_mix_entries(
                    target_archive,
                    temporary_root=Path(temporary_root),
                    remove_ids=remove_entry_ids,
                    rename_entries=rename_entries,
                    copy_entries=copy_entries,
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
