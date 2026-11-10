from __future__ import annotations

import hashlib
from pathlib import Path
from collections.abc import Callable

from mix_browser.features.archive.domain import MixArchiveIndex, MixEntry


def copy_mix_entry_and_hash(
    archive: MixArchiveIndex,
    entry: MixEntry,
    destination: Path,
    *,
    chunk_size: int = 1024 * 1024,
    progress: Callable[[int, int], None] | None = None,
    cancellation_requested: Callable[[], bool] | None = None,
) -> str:
    if chunk_size <= 0:
        raise ValueError("The copy chunk size must be positive.")

    source_start = archive.data_start + entry.offset
    source_end = source_start + entry.size
    archive_end = archive.source_offset + archive.source_size
    if (
        entry.offset < 0
        or entry.size < 0
        or source_start < archive.source_offset
        or source_start < archive.data_start
        or source_end > archive_end
    ):
        raise ValueError("The MIX entry extends beyond its archive range.")

    created = False
    digest = hashlib.sha256()
    copied = 0
    try:
        with archive.path.open("rb") as source:
            source.seek(source_start)
            with destination.open("xb") as target:
                created = True
                remaining = entry.size
                while remaining:
                    if cancellation_requested and cancellation_requested():
                        raise InterruptedError("The MIX entry copy was cancelled.")
                    block = source.read(min(chunk_size, remaining))
                    if not block:
                        raise OSError("The MIX entry ended before its declared size.")
                    target.write(block)
                    digest.update(block)
                    remaining -= len(block)
                    copied += len(block)
                    if progress:
                        progress(copied, entry.size)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    if progress and entry.size == 0:
        progress(0, 0)
    return digest.hexdigest()


# @arch mix-browser.file-hash service | en: Hashes a file while checking that it stays unchanged | zh: 计算文件哈希并检查文件在读取期间未改变
def hash_file(path: Path, *, chunk_size: int = 1024 * 1024) -> tuple[str, tuple[int, int]]:
    if chunk_size <= 0:
        raise ValueError("The hash chunk size must be positive.")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(chunk_size):
            digest.update(block)
    after = path.stat()
    before_signature = (before.st_size, before.st_mtime_ns)
    after_signature = (after.st_size, after.st_mtime_ns)
    if before_signature != after_signature:
        raise OSError("The file changed while its contents were being checked.")
    return digest.hexdigest(), after_signature


# @arch mix-browser.mix-entry-hash service | en: Hashes one MIX entry while checking archive bounds and stability | zh: 校验归档边界与稳定性并计算 MIX 条目的哈希
def hash_mix_entry(
    archive: MixArchiveIndex,
    entry: MixEntry,
    *,
    chunk_size: int = 1024 * 1024,
) -> str:
    if chunk_size <= 0:
        raise ValueError("The hash chunk size must be positive.")

    source_start = archive.data_start + entry.offset
    source_end = source_start + entry.size
    archive_end = archive.source_offset + archive.source_size
    if (
        entry.offset < 0
        or entry.size < 0
        or source_start < archive.source_offset
        or source_start < archive.data_start
        or source_end > archive_end
    ):
        raise ValueError("The MIX entry extends beyond its archive range.")

    before = archive.path.stat()
    before_signature = (before.st_size, before.st_mtime_ns)
    if before_signature != archive.file_signature:
        raise OSError("The source MIX archive changed after it was opened.")

    digest = hashlib.sha256()
    try:
        with archive.path.open("rb") as source:
            source.seek(source_start)
            remaining = entry.size
            while remaining:
                block = source.read(min(chunk_size, remaining))
                if not block:
                    raise OSError("The MIX entry ended before its declared size.")
                digest.update(block)
                remaining -= len(block)
    except OSError:
        raise

    after = archive.path.stat()
    if (after.st_size, after.st_mtime_ns) != before_signature:
        raise OSError("The source MIX archive changed while the entry was being read.")
    return digest.hexdigest()
