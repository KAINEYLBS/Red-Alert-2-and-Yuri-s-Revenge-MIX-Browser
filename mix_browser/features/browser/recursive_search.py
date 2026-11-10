from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRegularExpression

from mix_browser.features.archive.domain import MixArchiveIndex, MixEntry
from mix_browser.features.archive.loader import MixArchiveLoader
from mix_browser.features.archive.type_detection import (
    CONTENT_TYPE_SUFFIX_OVERRIDES,
    detect_content_type,
    detect_content_type_for_suffix,
)
from mix_browser.features.browser.asset_preview import (
    FallbackPaletteClassifier,
    PaletteLibraryRule,
)

_MAX_MIX_DEPTH = 64


@dataclass(frozen=True)
class DirectoryPageLocation:
    path: Path
    key: str
    title: str
    ancestors: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ArchivePageLocation:
    archive: MixArchiveIndex
    key: str
    title: str
    location_text: str
    ancestors: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SearchRoot:
    directory: DirectoryPageLocation | None = None
    archive: ArchivePageLocation | None = None

    @property
    def label(self) -> str:
        if self.directory is not None:
            return str(self.directory.path)
        if self.archive is not None:
            return self.archive.location_text
        return ""


# @arch mix-browser.search-hit model | en: Stores a recursive search result and its palette diagnostic state | zh: 保存递归搜索结果及其色盘诊断状态
@dataclass(frozen=True)
class SearchHit:
    relative_path: str
    type_label: str
    physical_path: Path | None = None
    directory_chain: tuple[DirectoryPageLocation, ...] = ()
    archive_chain: tuple[ArchivePageLocation, ...] = ()
    entry_id: int | None = None
    uses_fallback_palette: bool | None = None


@dataclass(frozen=True)
class SearchOutcome:
    hits: tuple[SearchHit, ...]
    cancelled: bool = False
    truncated: bool = False
    error: str | None = None


# @arch mix-browser.recursive-search service | en: Searches directory trees and nested MIX archives | zh: 搜索目录树与嵌套 MIX 归档
def search_from_root(
    root: SearchRoot,
    query: str,
    *,
    regular_expression: bool,
    archive_loader: MixArchiveLoader,
    cancellation_requested: Callable[[], bool],
    name_game: str | None = None,
    result_limit: int | None = None,
    classify_fallback_palettes: bool = False,
    fallback_palette_only: bool = False,
    palette_directory: Path | None = None,
    palette_theater: str = "auto",
    palette_library: tuple[PaletteLibraryRule, ...] = (),
) -> SearchOutcome:
    if result_limit is not None and result_limit <= 0:
        raise ValueError("The result limit must be positive.")
    pattern = query if regular_expression else QRegularExpression.escape(query)
    expression = QRegularExpression(
        pattern,
        QRegularExpression.PatternOption.CaseInsensitiveOption,
    )
    if not expression.isValid():
        return SearchOutcome((), error=expression.errorString())

    archive_session = archive_loader.create_session(name_game=name_game)
    palette_classifier = (
        FallbackPaletteClassifier(
            palette_directory=palette_directory,
            palette_theater=palette_theater,
            palette_library=palette_library,
            cancellation_requested=cancellation_requested,
        )
        if classify_fallback_palettes
        else None
    )
    hits: list[SearchHit] = []
    cancelled = False
    truncated = False

    def add_hit(hit: SearchHit) -> None:
        if fallback_palette_only and hit.uses_fallback_palette is not True:
            return
        hits.append(hit)

    def matches(relative_path: str) -> bool:
        return not query or expression.match(relative_path).hasMatch()

    def fallback_status(
        entry: MixEntry,
        *,
        archive: MixArchiveIndex | None = None,
        path: Path | None = None,
        palette_context: tuple[str, ...] = (),
    ) -> bool | None:
        if palette_classifier is None:
            return None
        return palette_classifier.uses_fallback(
            entry,
            archive=archive,
            path=path,
            palette_context=palette_context,
        )

    def scan_archive(
        archive: MixArchiveIndex,
        archive_chain: tuple[ArchivePageLocation, ...],
        directory_chain: tuple[DirectoryPageLocation, ...],
        relative_prefix: str,
        ancestor_ranges: frozenset[tuple[str, int, int]],
        depth: int,
    ) -> None:
        nonlocal cancelled, truncated
        for entry in archive.entries:
            if cancellation_requested():
                cancelled = True
                return
            name = _entry_name(entry)
            relative_path = "/".join(part for part in (relative_prefix, name) if part)
            if matches(relative_path):
                uses_fallback_palette = fallback_status(
                    entry,
                    archive=archive,
                    palette_context=tuple(location.title for location in archive_chain),
                )
                add_hit(
                    SearchHit(
                        relative_path,
                        entry.file_type or "Unknown",
                        directory_chain=directory_chain,
                        archive_chain=archive_chain,
                        entry_id=entry.file_id,
                        uses_fallback_palette=uses_fallback_palette,
                    )
                )

            if not _is_nested_mix(entry):
                continue
            if depth >= _MAX_MIX_DEPTH:
                truncated = True
                continue
            try:
                nested = archive_session.load_nested(archive, entry)
            except Exception:
                continue
            identity = _archive_identity(nested)
            if identity in ancestor_ranges:
                truncated = True
                continue
            nested_title = _entry_name(entry)
            parent_location = archive_chain[-1]
            nested_location = ArchivePageLocation(
                archive=nested,
                key=f"{parent_location.key}!{entry.file_id:08x}",
                title=nested_title,
                location_text=f"{parent_location.location_text} > {nested_title}",
                ancestors=(*parent_location.ancestors, (parent_location.key, parent_location.title)),
            )
            scan_archive(
                nested,
                (*archive_chain, nested_location),
                directory_chain,
                relative_path,
                ancestor_ranges | {identity},
                depth + 1,
            )
            if cancelled:
                return

    if root.archive is not None:
        identity = _archive_identity(root.archive.archive)
        scan_archive(
            root.archive.archive,
            (root.archive,),
            (),
            "",
            frozenset({identity}),
            0,
        )
    elif root.directory is not None:
        pending: list[tuple[Path, str, tuple[DirectoryPageLocation, ...]]] = [
            (root.directory.path, "", (root.directory,))
        ]
        while pending and not cancelled:
            directory, relative_directory, directory_chain = pending.pop()
            if cancellation_requested():
                cancelled = True
                break
            try:
                with os.scandir(directory) as iterator:
                    entries = sorted(iterator, key=lambda item: item.name.casefold())
            except OSError:
                continue
            child_directories: list[
                tuple[Path, str, tuple[DirectoryPageLocation, ...]]
            ] = []
            for directory_entry in entries:
                if cancellation_requested():
                    cancelled = True
                    break
                try:
                    path = Path(directory_entry.path)
                    if directory_entry.is_symlink():
                        relative_path = "/".join(
                            part for part in (relative_directory, directory_entry.name) if part
                        )
                        if matches(relative_path):
                            add_hit(
                                SearchHit(
                                    relative_path,
                                    "Link",
                                    physical_path=path,
                                    directory_chain=directory_chain,
                                )
                            )
                        continue
                    is_directory = directory_entry.is_dir(follow_symlinks=False)
                    is_file = not is_directory and directory_entry.is_file(
                        follow_symlinks=False
                    )
                    if not is_directory and not is_file:
                        continue
                    relative_path = "/".join(
                        part for part in (relative_directory, directory_entry.name) if part
                    )
                    if matches(relative_path):
                        entry_type = "Folder" if is_directory else _path_type(path)
                        uses_fallback_palette = None
                        if is_file:
                            try:
                                size = directory_entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                size = 0
                            physical_entry = MixEntry(
                                0,
                                0,
                                size,
                                directory_entry.name,
                                file_type=entry_type,
                            )
                            uses_fallback_palette = fallback_status(
                                physical_entry,
                                path=path,
                                palette_context=tuple(
                                    location.title for location in directory_chain
                                ),
                            )
                        add_hit(
                            SearchHit(
                                relative_path,
                                entry_type,
                                physical_path=path,
                                directory_chain=directory_chain,
                                uses_fallback_palette=uses_fallback_palette,
                            )
                        )
                    if is_directory:
                        child_location = DirectoryPageLocation(
                            path,
                            str(path.resolve()).casefold(),
                            path.name or str(path),
                            (
                                *directory_chain[-1].ancestors,
                                (directory_chain[-1].key, directory_chain[-1].title),
                            ),
                        )
                        child_directories.append(
                            (path, relative_path, (*directory_chain, child_location))
                        )
                        continue

                    if _is_mix_file(path):
                        try:
                            archive = archive_session.load(path)
                        except Exception:
                            continue
                        archive_location = ArchivePageLocation(
                            archive=archive,
                            key=str(archive.path).casefold(),
                            title=path.name,
                            location_text=str(path),
                            ancestors=(
                                *directory_chain[-1].ancestors,
                                (directory_chain[-1].key, directory_chain[-1].title),
                            ),
                        )
                        identity = _archive_identity(archive)
                        scan_archive(
                            archive,
                            (archive_location,),
                            directory_chain,
                            relative_path,
                            frozenset({identity}),
                            0,
                        )
                        if cancelled:
                            break
                except OSError:
                    continue
            pending.extend(reversed(child_directories))

    hits.sort(key=lambda hit: (hit.relative_path.casefold(), hit.relative_path))
    if result_limit is not None and len(hits) > result_limit:
        hits = hits[:result_limit]
        truncated = True
    return SearchOutcome(tuple(hits), cancelled=cancelled, truncated=truncated)


def _entry_name(entry: MixEntry) -> str:
    return entry.name or f"Unknown (0x{entry.file_id:08X})"


def _is_nested_mix(entry: MixEntry) -> bool:
    return (
        Path(entry.name or "").suffix.casefold() == ".mix"
        or (entry.file_type or "").casefold() == "mix"
    )


def _archive_identity(archive: MixArchiveIndex) -> tuple[str, int, int]:
    return (str(archive.path).casefold(), archive.source_offset, archive.source_size)


def _is_mix_file(path: Path) -> bool:
    if path.suffix.casefold() == ".mix":
        return True
    try:
        metadata = path.stat()
        with path.open("rb") as source:
            prefix = source.read(128)
    except OSError:
        return False
    return detect_content_type(prefix, metadata.st_size) == "MIX"


def _path_type(path: Path) -> str:
    raw_suffix = path.suffix.casefold()
    suffix = raw_suffix[1:].upper()
    if suffix and raw_suffix not in CONTENT_TYPE_SUFFIX_OVERRIDES:
        return suffix
    try:
        metadata = path.stat()
        with path.open("rb") as source:
            prefix = source.read(128)
    except OSError:
        return "File"
    return (
        detect_content_type_for_suffix(prefix, metadata.st_size, raw_suffix)
        or suffix
        or "File"
    )
