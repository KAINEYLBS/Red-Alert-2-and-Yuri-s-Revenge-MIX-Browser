from __future__ import annotations

import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from collections.abc import Callable, Sequence

from mix_browser.features.archive.domain import MixArchiveIndex, MixEntry
from mix_browser.features.archive.loader import MixArchiveLoader
from mix_browser.features.archive.source import copy_mix_entry_and_hash, hash_file
from mix_browser.features.browser.recursive_search import SearchHit


_INVALID_FILENAME_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SIMPLE_FILE_TYPE = re.compile(r"^[A-Za-z0-9]{1,16}$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


@dataclass(frozen=True)
class ExtractedEntry:
    path: Path
    content_hash: str
    archive_signature: tuple[int, int]
    file_signature: tuple[int, int]


# @arch mix-browser.extract-mix-entries-for-drag service | en: Copies selected MIX entries to temporary files for drag-and-drop | zh: 将选中的 MIX 条目复制到临时文件以供拖放
def extract_entries_for_drag(
    archive: MixArchiveIndex,
    entries: Sequence[MixEntry],
    destination: Path,
    *,
    cancellation_requested: Callable[[], bool] | None = None,
) -> tuple[Path, ...]:
    before = archive.path.stat()
    expected_signature = (before.st_size, before.st_mtime_ns)
    if expected_signature != archive.file_signature:
        raise OSError("The source MIX archive changed after it was opened.")
    destination.mkdir(parents=True, exist_ok=False)
    used_names: set[str] = set()
    paths: list[Path] = []
    try:
        for entry in entries:
            if cancellation_requested and cancellation_requested():
                raise InterruptedError("The MIX entry drag was cancelled.")
            filename = _temporary_filename(entry)
            if filename.casefold() in used_names:
                base_filename = filename
                filename = f"{entry.file_id:08X}_{base_filename}"
                duplicate_index = 1
                while filename.casefold() in used_names:
                    filename = f"{entry.file_id:08X}_{duplicate_index}_{base_filename}"
                    duplicate_index += 1
            used_names.add(filename.casefold())
            path = destination / filename
            copy_mix_entry_and_hash(
                archive,
                entry,
                path,
                cancellation_requested=cancellation_requested,
            )
            paths.append(path)
        after = archive.path.stat()
        if (after.st_size, after.st_mtime_ns) != expected_signature:
            raise OSError("The source MIX archive changed during drag preparation.")
        return tuple(paths)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


# @arch mix-browser.prepare-search-hit-targets service | en: Prepares selected recursive search results as filesystem targets | zh: 将选中的递归搜索结果准备为文件系统对象
def prepare_search_hit_targets(
    hits: Sequence[SearchHit],
    destination: Path,
    *,
    cancellation_requested: Callable[[], bool] | None = None,
) -> tuple[Path, ...]:
    destination.mkdir(parents=True, exist_ok=False)
    paths: list[Path] = []
    try:
        for index, hit in enumerate(hits):
            if cancellation_requested and cancellation_requested():
                raise InterruptedError(
                    "Preparing search result targets was cancelled."
                )
            if hit.physical_path is not None:
                if not hit.physical_path.exists() and not hit.physical_path.is_symlink():
                    raise FileNotFoundError(hit.physical_path)
                paths.append(hit.physical_path)
                continue
            if not hit.archive_chain or hit.entry_id is None:
                raise OSError(
                    f"The search result is no longer available: {hit.relative_path}"
                )
            archive = hit.archive_chain[-1].archive
            entry = next(
                (entry for entry in archive.entries if entry.file_id == hit.entry_id),
                None,
            )
            if entry is None:
                raise OSError(
                    f"The search result is no longer available: {hit.relative_path}"
                )
            paths.extend(
                extract_entries_for_drag(
                    archive,
                    (entry,),
                    destination / f"item-{index:08d}",
                    cancellation_requested=cancellation_requested,
                )
            )
        if not paths:
            raise OSError("No search result targets are available.")
        return tuple(paths)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def extract_entry_to_temporary_file(
    archive: MixArchiveIndex,
    entry: MixEntry,
    temporary_root: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    cancellation_requested: Callable[[], bool] | None = None,
) -> ExtractedEntry:
    if cancellation_requested and cancellation_requested():
        raise InterruptedError("The MIX entry copy was cancelled.")
    before = archive.path.stat()
    before_signature = (before.st_size, before.st_mtime_ns)
    if before_signature != archive.file_signature:
        raise OSError("The source MIX archive changed after it was opened.")
    entry_directory = Path(tempfile.mkdtemp(prefix="entry-", dir=temporary_root))
    filename = _temporary_filename(entry)
    destination = entry_directory / filename
    last_progress_at = 0.0
    last_progress_bytes = 0

    def report_progress(completed: int, total: int) -> None:
        nonlocal last_progress_at, last_progress_bytes
        if progress is None:
            return
        now = time.monotonic()
        if completed == total or completed - last_progress_bytes >= 4 * 1024 * 1024 or now - last_progress_at >= 0.15:
            progress(completed, total)
            last_progress_at = now
            last_progress_bytes = completed

    try:
        content_hash = copy_mix_entry_and_hash(
            archive,
            entry,
            destination,
            progress=report_progress,
            cancellation_requested=cancellation_requested,
        )
        if cancellation_requested and cancellation_requested():
            raise InterruptedError("The MIX entry copy was cancelled.")
        after = archive.path.stat()
        after_signature = (after.st_size, after.st_mtime_ns)
        if after_signature != before_signature:
            raise OSError("The source MIX archive changed during extraction.")
        file_stat = destination.stat()
        file_signature = (file_stat.st_size, file_stat.st_mtime_ns)
        return ExtractedEntry(destination, content_hash, before_signature, file_signature)
    except Exception:
        shutil.rmtree(entry_directory, ignore_errors=True)
        raise


def load_archive_chain(
    loader: MixArchiveLoader,
    root_path: Path,
    entry_ids: tuple[int, ...],
) -> MixArchiveIndex:
    archive = loader.load(root_path)
    for entry_id in entry_ids:
        entry = next((item for item in archive.entries if item.file_id == entry_id), None)
        if entry is None:
            raise OSError(f"MIX entry 0x{entry_id:08X} is no longer present.")
        archive = loader.load_nested(archive, entry)
    return archive


def reload_archive_indexes(
    loader: MixArchiveLoader,
    root_path: Path,
    targets: tuple[tuple[str, tuple[int, ...]], ...],
) -> dict[str, MixArchiveIndex]:
    root_archive = loader.load(root_path)
    cache: dict[tuple[int, ...], MixArchiveIndex] = {(): root_archive}
    reloaded: dict[str, MixArchiveIndex] = {}
    for target_key, entry_ids in sorted(targets, key=lambda item: len(item[1])):
        for depth in range(1, len(entry_ids) + 1):
            chain = entry_ids[:depth]
            if chain in cache:
                continue
            parent = cache[chain[:-1]]
            entry = next((item for item in parent.entries if item.file_id == chain[-1]), None)
            if entry is None:
                raise OSError(f"MIX entry 0x{chain[-1]:08X} is no longer present.")
            cache[chain] = loader.load_nested(parent, entry)
        reloaded[target_key] = cache[entry_ids]
    return reloaded


def _temporary_filename(entry: MixEntry) -> str:
    source_name = PureWindowsPath(entry.name or "").name
    filename = _INVALID_FILENAME_CHARACTERS.sub("_", source_name).rstrip(" .")
    if not filename or filename in {".", ".."}:
        filename = f"{entry.file_id:08X}"

    suffix = Path(filename).suffix
    if not suffix and entry.file_type and _SIMPLE_FILE_TYPE.fullmatch(entry.file_type):
        suffix = f".{entry.file_type.lower()}"
        filename = f"{filename}{suffix}"

    stem = filename[: -len(suffix)] if suffix else filename
    stem = stem[:120].rstrip(" .") or f"{entry.file_id:08X}"
    if stem.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem}{suffix[:32]}"
