from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice

from mix_browser.features.archive.domain import MixEntry, MixFormatError
from mix_browser.features.archive.loader import MixArchiveLoader
from mix_browser.features.archive.name_catalog import validate_mix_name_game
from mix_browser.features.archive.type_detection import detect_content_type
from mix_browser.features.browser.asset_preview import (
    PaletteLibraryRule,
    indexed_frame_image,
    load_entry_preview,
    load_path_preview,
)
from mix_browser.features.browser.directory_listing import load_directory_entries
from mix_browser.features.browser.document_data import decode_document
from mix_browser.features.browser.directory_operations import (
    create_directory as _create_directory,
    create_file as _create_file,
    delete_entries as _delete_directory_entries,
    rename_entry as _rename_directory_entry,
    transfer_entries as _transfer_directory_entries,
)
from mix_browser.features.browser.file_add import add_files_to_directory as _add_files_to_directory
from mix_browser.features.browser.recursive_search import (
    ArchivePageLocation,
    DirectoryPageLocation,
    SearchRoot,
    search_from_root,
)
from mix_browser.shared.application_errors import ApplicationApiError

__all__ = ["MixBrowserFeatureApplication"]


# @arch mix-browser.browser-api component | en: Exposes filesystem management, directory browsing, file addition, and recursive search use cases | zh: 提供文件系统管理、目录浏览、文件添加与递归搜索用例
class MixBrowserFeatureApplication:
    def __init__(self, archive_loader: MixArchiveLoader) -> None:
        self._archive_loader = archive_loader

    def list_directory(self, directory: Path) -> dict[str, object]:
        path = directory.expanduser()
        try:
            if not path.exists():
                raise ApplicationApiError("not_found", f"Directory not found: {path}")
            if not path.is_dir():
                raise ApplicationApiError("not_directory", f"The path is not a directory: {path}")
            entries = load_directory_entries(path)
        except ApplicationApiError:
            raise
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", f"The directory cannot be read: {path}") from exc
        except OSError as exc:
            raise ApplicationApiError("io_error", str(exc)) from exc
        return {
            "path": str(path.resolve()),
            "entry_count": len(entries),
            "entries": [
                {
                    "name": entry.path.name,
                    "path": str(entry.path),
                    "is_directory": entry.is_directory,
                    "type": entry.file_type,
                    "size_bytes": entry.size,
                    "modified_unix_seconds": entry.modified,
                }
                for entry in entries
            ],
        }

    def add_files_to_directory(
        self,
        directory: Path,
        source_paths: tuple[Path, ...],
        *,
        overwrite: bool = False,
        approved_overwrites: frozenset[str] | None = None,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        target = directory.expanduser()
        try:
            return _add_files_to_directory(
                target,
                source_paths,
                overwrite=overwrite,
                approved_overwrites=approved_overwrites,
                progress=progress,
                cancellation_requested=cancellation_requested,
            )
        except InterruptedError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", str(exc)) from exc
        except NotADirectoryError as exc:
            raise ApplicationApiError("not_directory", str(exc)) from exc
        except FileExistsError as exc:
            raise ApplicationApiError("output_exists", str(exc)) from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except (ValueError, IsADirectoryError) as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except OSError as exc:
            raise ApplicationApiError("io_error", str(exc)) from exc

    # @arch mix-browser.directory-create service | en: Creates one child filesystem directory, optionally replacing an existing item | zh: 创建子文件系统目录，并可选替换已有对象
    def create_directory(
        self,
        directory: Path,
        name: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, object]:
        try:
            return _create_directory(directory, name, overwrite=overwrite)
        except FileExistsError as exc:
            raise ApplicationApiError("output_exists", str(exc)) from exc
        except NotADirectoryError as exc:
            raise ApplicationApiError("not_directory", str(exc)) from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except (ValueError, IsADirectoryError) as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except OSError as exc:
            raise ApplicationApiError("io_error", str(exc)) from exc

    def create_file(
        self,
        directory: Path,
        name: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, object]:
        try:
            return _create_file(directory, name, overwrite=overwrite)
        except FileExistsError as exc:
            raise ApplicationApiError("output_exists", str(exc)) from exc
        except NotADirectoryError as exc:
            raise ApplicationApiError("not_directory", str(exc)) from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except (ValueError, IsADirectoryError) as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except OSError as exc:
            raise ApplicationApiError("io_error", str(exc)) from exc

    def rename_directory_entry(
        self,
        path: Path,
        new_name: str,
        *,
        overwrite: bool = False,
    ) -> dict[str, object]:
        try:
            return _rename_directory_entry(path, new_name, overwrite=overwrite)
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", str(exc)) from exc
        except FileExistsError as exc:
            raise ApplicationApiError("output_exists", str(exc)) from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except ValueError as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except OSError as exc:
            raise ApplicationApiError("io_error", str(exc)) from exc

    def delete_directory_entries(
        self,
        paths: tuple[Path, ...],
        *,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        try:
            return _delete_directory_entries(
                paths,
                progress=progress,
                cancellation_requested=cancellation_requested,
            )
        except InterruptedError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", str(exc)) from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except ValueError as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except OSError as exc:
            raise ApplicationApiError("io_error", str(exc)) from exc

    def transfer_directory_entries(
        self,
        destination: Path,
        source_paths: tuple[Path, ...],
        *,
        move: bool = False,
        overwrite: bool = False,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        try:
            return _transfer_directory_entries(
                destination,
                source_paths,
                move=move,
                overwrite=overwrite,
                progress=progress,
                cancellation_requested=cancellation_requested,
            )
        except InterruptedError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", str(exc)) from exc
        except NotADirectoryError as exc:
            raise ApplicationApiError("not_directory", str(exc)) from exc
        except FileExistsError as exc:
            raise ApplicationApiError("output_exists", str(exc)) from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except (ValueError, IsADirectoryError) as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        except OSError as exc:
            raise ApplicationApiError("io_error", str(exc)) from exc

    def search(
        self,
        root_path: Path,
        query: str,
        *,
        regular_expression: bool = False,
        parent_entry_ids: tuple[int, ...] = (),
        max_results: int = 1000,
        name_game: str | None = None,
    ) -> dict[str, object]:
        name_game = self._validate_name_game(name_game)
        if not query:
            raise ApplicationApiError("invalid_input", "The search query must not be empty.")
        if max_results <= 0:
            raise ApplicationApiError("invalid_input", "The result limit must be positive.")
        root_path = root_path.expanduser()
        search_root = self._make_search_root(
            root_path,
            parent_entry_ids,
            name_game=name_game,
        )
        try:
            outcome = search_from_root(
                search_root,
                query,
                regular_expression=regular_expression,
                archive_loader=self._archive_loader,
                cancellation_requested=lambda: False,
                result_limit=max_results,
                name_game=name_game,
            )
        except ValueError as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc
        if outcome.error:
            raise ApplicationApiError("invalid_regex", outcome.error)
        return {
            "root": search_root.label,
            "query": query,
            "regular_expression": regular_expression,
            "result_count": len(outcome.hits),
            "cancelled": outcome.cancelled,
            "truncated": outcome.truncated,
            "hits": [
                {
                    "relative_path": hit.relative_path,
                    "type": hit.type_label,
                    "physical_path": str(hit.physical_path) if hit.physical_path else None,
                    "entry_id": hit.entry_id,
                    "archive_chain": [
                        {
                            "path": str(location.archive.path),
                            "source_offset": location.archive.source_offset,
                            "source_size_bytes": location.archive.source_size,
                            "parent_entry_ids": [
                                parent.entry_id for parent in location.archive.parents
                            ],
                        }
                        for location in hit.archive_chain
                    ],
                    "directory_chain": [
                        {"path": str(location.path), "title": location.title}
                        for location in hit.directory_chain
                    ],
                }
                for hit in outcome.hits
            ],
        }

    def preview(
        self,
        path: Path,
        *,
        entry_id: int | None = None,
        parent_entry_ids: tuple[int, ...] = (),
        game_directory: Path | None = None,
        palette_theater: str = "auto",
        palette_library: tuple[tuple[Path, str], ...] = (),
        frame_index: int = 0,
        palette_index: int | None = None,
        encoding: str | None = None,
        name_game: str | None = None,
    ) -> dict[str, object]:
        name_game = self._validate_name_game(name_game)
        if palette_theater not in {"auto", "tem", "sno", "urb", "des", "lun", "ubn"}:
            raise ApplicationApiError("invalid_input", f"Unsupported theater: {palette_theater}")
        if entry_id is not None and not 0 <= entry_id <= 0xFFFFFFFF:
            raise ApplicationApiError("invalid_input", "A MIX entry ID must be an unsigned 32-bit integer.")
        library_rules = tuple(
            PaletteLibraryRule(rule_path, pattern)
            for rule_path, pattern in palette_library
        )
        if entry_id is None:
            if parent_entry_ids:
                raise ApplicationApiError(
                    "invalid_input",
                    "Parent entry IDs require a MIX archive entry ID.",
                )
            result = load_path_preview(
                path.expanduser(),
                game_directory,
                palette_theater=palette_theater,
                xcc_names_enabled=self._name_sources_enabled("xcc"),
                community_names_enabled=self._name_sources_enabled("community"),
                palette_library=library_rules,
            )
        else:
            archive, archive_path, palette_context = self._load_archive_for_entry(
                path,
                parent_entry_ids,
                name_game=name_game,
            )
            entry = next(
                (item for item in archive.entries if item.file_id == entry_id),
                None,
            )
            if entry is None:
                raise ApplicationApiError(
                    "entry_not_found",
                    f"MIX entry 0x{entry_id:08X} was not found in {archive_path}.",
                )
            result = load_entry_preview(
                archive,
                entry,
                game_directory,
                palette_theater=palette_theater,
                xcc_names_enabled=self._name_sources_enabled("xcc"),
                community_names_enabled=self._name_sources_enabled("community"),
                palette_library=library_rules,
                palette_context=palette_context,
            )

        output: dict[str, object] = {
            "kind": result.kind,
            "message": result.message,
            "details": list(result.details),
            "frame_count": len(result.frames),
            "palette_options": [
                {
                    "name": palette.name,
                    "source": palette.source,
                    "group": palette.group,
                }
                for palette in result.palettes
            ],
        }
        if result.document is not None:
            document = result.document
            selected_encoding = encoding or document.detected_encoding
            decoded = (
                decode_document(
                    document.data,
                    selected_encoding,
                    truncated=document.truncated,
                )
                if selected_encoding != document.detected_encoding
                else None
            )
            output["document"] = {
                "text": decoded.text if decoded is not None else document.text,
                "encoding": selected_encoding,
                "detected_encoding": document.detected_encoding,
                "line_endings": decoded.line_endings if decoded is not None else document.line_endings,
                "truncated": document.truncated,
                "message": decoded.message if decoded is not None else document.message,
            }
        if result.image is not None:
            output["image_png"] = self._encode_png(result.image)
        elif result.frames:
            selected_frame = self._valid_index(frame_index, len(result.frames), "frame")
            selected_palette_index = (
                result.default_palette_index if palette_index is None else palette_index
            )
            selected_palette_index = self._valid_index(
                selected_palette_index,
                len(result.palettes),
                "palette",
            )
            output["selected_frame"] = selected_frame
            output["selected_palette"] = output["palette_options"][selected_palette_index]
            output["image_png"] = self._encode_png(
                indexed_frame_image(
                    result.frames[selected_frame],
                    result.palettes[selected_palette_index],
                    transparent_zero=True,
                )
            )
        if result.palette is not None:
            output["palette"] = {
                "name": result.palette.name,
                "source": result.palette.source,
                "color_count": result.palette.color_count,
                "colors_rgb": [list(color) for color in result.palette.colors],
            }
        if result.voxel_model is not None:
            selected_palette_index = (
                result.default_palette_index if palette_index is None else palette_index
            )
            output["model"] = {
                "vertex_count": result.voxel_model.vertex_count,
                "voxel_count": result.voxel_model.voxel_count,
            }
            if result.palettes:
                selected_palette_index = self._valid_index(
                    selected_palette_index,
                    len(result.palettes),
                    "palette",
                )
                palette = result.palettes[selected_palette_index]
                output["selected_palette"] = {
                    "name": palette.name,
                    "source": palette.source,
                    "group": palette.group,
                }
        if result.kind == "media":
            output["media"] = {
                "suffix": result.media_suffix,
                "is_video": result.is_video,
                "size_bytes": len(result.media_data),
            }
            output["media_data"] = result.media_data
        return output

    def _make_search_root(
        self,
        root_path: Path,
        parent_entry_ids: tuple[int, ...],
        *,
        name_game: str | None = None,
    ) -> SearchRoot:
        try:
            if root_path.is_dir():
                if parent_entry_ids:
                    raise ApplicationApiError(
                        "invalid_input",
                        "Parent entry IDs can only be used when the root is a MIX archive.",
                    )
                path = root_path.resolve()
                return SearchRoot(
                    directory=DirectoryPageLocation(
                        path=path,
                        key=str(path).casefold(),
                        title=path.name or str(path),
                    )
                )
            if not root_path.is_file():
                raise ApplicationApiError("not_found", f"Search root not found: {root_path}")
            with root_path.open("rb") as source:
                prefix = source.read(128)
            if root_path.suffix.casefold() != ".mix" and detect_content_type(
                prefix,
                root_path.stat().st_size,
            ) != "MIX":
                raise ApplicationApiError(
                    "unsupported_root",
                    "The search root must be a directory or MIX archive.",
                )
            session = self._archive_loader.create_session(name_game=name_game)
            archive = session.load(root_path)
            root_location = ArchivePageLocation(
                archive=archive,
                key=str(archive.path).casefold(),
                title=archive.path.name,
                location_text=str(archive.path),
            )
            archive_chain = [root_location]
            for entry_id in parent_entry_ids:
                parent = archive_chain[-1]
                entry = self._find_entry(archive.entries, entry_id, parent.location_text)
                archive = session.load_nested(archive, entry)
                title = entry.name or f"Unknown (0x{entry.file_id:08X})"
                archive_chain.append(
                    ArchivePageLocation(
                        archive=archive,
                        key=f"{parent.key}!{entry.file_id:08x}",
                        title=title,
                        location_text=f"{parent.location_text} > {title}",
                        ancestors=(*parent.ancestors, (parent.key, parent.title)),
                    )
                )
            return SearchRoot(archive=archive_chain[-1])
        except ApplicationApiError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", f"Search root not found: {root_path}") from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except OSError as exc:
            raise ApplicationApiError("io_error", str(exc)) from exc
        except MixFormatError as exc:
            raise ApplicationApiError("invalid_mix", str(exc)) from exc
        except ValueError as exc:
            raise ApplicationApiError("invalid_nested_mix", str(exc)) from exc

    def _load_archive_for_entry(
        self,
        archive_path: Path,
        parent_entry_ids: tuple[int, ...],
        *,
        name_game: str | None = None,
    ):
        path = archive_path.expanduser()
        try:
            session = self._archive_loader.create_session(name_game=name_game)
            archive = session.load(path)
            palette_context = [path.name]
            for entry_id in parent_entry_ids:
                entry = self._find_entry(archive.entries, entry_id, str(archive.path))
                palette_context.append(
                    entry.name or f"Unknown (0x{entry.file_id:08X})"
                )
                archive = session.load_nested(archive, entry)
            return archive, path, tuple(palette_context)
        except ApplicationApiError:
            raise
        except FileNotFoundError as exc:
            raise ApplicationApiError("not_found", f"MIX archive not found: {path}") from exc
        except PermissionError as exc:
            raise ApplicationApiError("access_denied", str(exc)) from exc
        except OSError as exc:
            raise ApplicationApiError("io_error", str(exc)) from exc
        except ValueError as exc:
            raise ApplicationApiError("invalid_mix", str(exc)) from exc

    @staticmethod
    def _find_entry(
        entries: tuple[MixEntry, ...],
        entry_id: int,
        archive_label: str,
    ) -> MixEntry:
        if not 0 <= entry_id <= 0xFFFFFFFF:
            raise ApplicationApiError("invalid_input", "A MIX entry ID must be an unsigned 32-bit integer.")
        entry = next((item for item in entries if item.file_id == entry_id), None)
        if entry is None:
            raise ApplicationApiError(
                "entry_not_found",
                f"MIX entry 0x{entry_id:08X} was not found in {archive_label}.",
            )
        return entry

    def _name_sources_enabled(self, source: str) -> bool:
        return bool(
            getattr(
                self._archive_loader,
                "name_sources_enabled",
                {"xcc": True, "community": True},
            ).get(source, True)
        )

    @staticmethod
    def _validate_name_game(name_game: str | None) -> str | None:
        if name_game is None:
            return None
        try:
            return validate_mix_name_game(name_game)
        except ValueError as exc:
            raise ApplicationApiError("invalid_input", str(exc)) from exc

    @staticmethod
    def _encode_png(image) -> bytes:
        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise ApplicationApiError("preview_error", "The PNG output buffer could not be opened.")
        try:
            if not image.save(buffer, "PNG"):
                raise ApplicationApiError("preview_error", "The preview image could not be encoded as PNG.")
            return bytes(buffer.data())
        finally:
            buffer.close()

    @staticmethod
    def _valid_index(index: int, length: int, label: str) -> int:
        if not 0 <= index < length:
            raise ApplicationApiError(
                "invalid_input",
                f"The {label} index must be between 0 and {length - 1}.",
            )
        return index
