from __future__ import annotations

import base64
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import lru_cache
import struct
import zlib
from pathlib import Path

from mix_browser.features.archive.dat_format import LOCAL_MIX_DATABASE_SIGNATURE
from mix_browser.features.archive.type_detection import (
    CONTENT_TYPE_SUFFIX_OVERRIDES,
    detect_content_type_for_suffix,
)

try:
    from Crypto.Cipher import Blowfish
except ImportError:
    try:
        from Cryptodome.Cipher import Blowfish
    except ImportError:  # Encrypted MIX support is unavailable without either package namespace.
        Blowfish = None


WESTWOOD_PUBLIC_KEY = "AihRvNoIbTn85FZRYNZRcT+i6KpU+maCsEqr3Q5q+LDB5tH7Tz2qQ38V"
EMPTY_MIX_ARCHIVE_HEADER = struct.pack("<HHHI", 0, 0, 0, 0)
LOCAL_MIX_DATABASE_NAME = "local mix database.dat"
_MAX_LOCAL_DATABASE_NAMES = 65_535
_MAX_LOCAL_DATABASE_NAME_TOKENS = 131_070


class MixFormatError(ValueError):
    """Raised when a file is not a readable MIX archive."""


@dataclass(frozen=True)
class MixEntry:
    file_id: int
    offset: int
    size: int
    name: str | None = None
    name_sources: tuple[str, ...] = ()
    file_type: str | None = None


@dataclass(frozen=True)
class MixNameCandidate:
    name: str
    source: str


# @arch mix-browser.mix-name-candidate-index utility | en: Indexes candidate filenames by MIX hash | zh: 按 MIX 哈希索引候选文件名
class MixNameCandidateIndex:
    def __init__(self) -> None:
        self._candidates_by_hash: dict[int, list[MixNameCandidate]] = {}
        self._candidate_order: dict[MixNameCandidate, int] = {}
        self._candidate_snapshot: object | None = None

    def add_candidates(self, names: Iterable[str | MixNameCandidate]) -> None:
        for raw_candidate in names:
            candidate = _normalize_mix_name_candidate(raw_candidate)
            if candidate is None or candidate in self._candidate_order:
                continue
            self._candidate_order[candidate] = len(self._candidate_order)
            for file_hash in set(_mix_file_hashes(candidate.name)):
                self._candidates_by_hash.setdefault(file_hash, []).append(candidate)

    def map(
        self,
        entries: dict[int, tuple[int, int]],
        names: Iterable[str | MixNameCandidate],
    ) -> tuple[dict[int, tuple[str, tuple[str, ...]]], set[int]]:
        if not isinstance(names, tuple) or names is not self._candidate_snapshot:
            self.add_candidates(names)
            self._candidate_snapshot = names if isinstance(names, tuple) else None

        matches_by_candidate: dict[MixNameCandidate, set[int]] = {}
        for file_id in entries:
            for candidate in self._candidates_by_hash.get(file_id, ()):
                matches_by_candidate.setdefault(candidate, set()).add(file_id)

        candidates_by_id: dict[int, dict[str, tuple[str, set[str]]]] = {}
        claimed_ids: set[int] = set()
        for candidate in sorted(matches_by_candidate, key=self._candidate_order.__getitem__):
            matches = matches_by_candidate[candidate]
            claimed_ids.update(matches)
            if len(matches) != 1:
                continue
            file_id = next(iter(matches))
            display_name, sources = candidates_by_id.setdefault(file_id, {}).setdefault(
                candidate.name.casefold(),
                (candidate.name, set()),
            )
            sources.add(candidate.source)

        resolved = {
            file_id: (display_name, tuple(sorted(sources)))
            for file_id, names_for_id in candidates_by_id.items()
            if len(names_for_id) == 1
            for display_name, sources in names_for_id.values()
        }
        return resolved, claimed_ids


@dataclass(frozen=True)
class MixArchiveParent:
    source_offset: int
    source_size: int
    entry_id: int


@dataclass(frozen=True)
class MixArchiveIndex:
    path: Path
    data_start: int
    entries: tuple[MixEntry, ...]
    source_offset: int
    source_size: int
    parents: tuple[MixArchiveParent, ...] = ()
    file_signature: tuple[int, int] = (0, 0)


# @arch mix-browser.mix-archive-reader adapter | en: Reads MIX archives into indexed entries | zh: 将 MIX 归档读取为索引条目
def open_mix_archive(
    path: Path,
    *,
    candidate_names: Iterable[str | MixNameCandidate] = (),
    candidate_index: MixNameCandidateIndex | None = None,
    max_local_database_bytes: int = 64 * 1024 * 1024,
    detect_types: bool = True,
    source_offset: int = 0,
    source_size: int | None = None,
    parents: tuple[MixArchiveParent, ...] = (),
) -> MixArchiveIndex:
    archive_path = path.expanduser().resolve()
    try:
        file_stat = archive_path.stat()
        file_size = file_stat.st_size
        if source_size is None:
            source_size = file_size - source_offset
        if source_offset < 0 or source_size < 0 or source_offset + source_size > file_size:
            raise MixFormatError("The MIX archive range extends beyond the source file.")
        data_start, raw_entries = _read_entry_table(
            archive_path,
            source_offset=source_offset,
            source_size=source_size,
        )
    except OSError:
        raise
    except MixFormatError:
        raise
    except (OverflowError, struct.error, ValueError) as exc:
        raise MixFormatError("The MIX archive header is invalid.") from exc

    entries = [MixEntry(file_id, offset, size) for file_id, (offset, size) in raw_entries.items()]
    entry_ids = set(raw_entries)
    database_id = _find_entry_id(LOCAL_MIX_DATABASE_NAME, {file_id: 0 for file_id in entry_ids})
    database_names: tuple[str, ...] = ()
    if database_id is not None:
        database_entry = next(entry for entry in entries if entry.file_id == database_id)
        database_data = _read_entry_bytes(
            archive_path,
            data_start,
            database_entry,
            max_bytes=max_local_database_bytes,
            source_end=source_offset + source_size,
        )
        database_names = _names_from_local_database(database_data)

    embedded_candidates = (
        MixNameCandidate(LOCAL_MIX_DATABASE_NAME, "Embedded local MIX database"),
        *(MixNameCandidate(name, "Embedded local MIX database") for name in database_names),
    )
    resolved_names, database_claimed_ids = _map_candidate_names(raw_entries, embedded_candidates)
    external_names, _external_claimed_ids = _map_candidate_names(
        raw_entries,
        candidate_names,
        candidate_index=candidate_index,
    )
    for file_id, candidate in external_names.items():
        if file_id not in database_claimed_ids:
            resolved_names.setdefault(file_id, candidate)
    entries = [
        MixEntry(
            entry.file_id,
            entry.offset,
            entry.size,
            resolved_names[entry.file_id][0] if entry.file_id in resolved_names else None,
            resolved_names[entry.file_id][1] if entry.file_id in resolved_names else (),
        )
        for entry in entries
    ]
    if detect_types:
        entries = _identify_entry_types(archive_path, data_start, entries)

    final_stat = archive_path.stat()
    initial_signature = (file_stat.st_size, file_stat.st_mtime_ns)
    if (final_stat.st_size, final_stat.st_mtime_ns) != initial_signature:
        raise MixFormatError("The MIX archive changed while it was being read.")

    return MixArchiveIndex(
        archive_path,
        data_start,
        tuple(entries),
        source_offset,
        source_size,
        parents,
        initial_signature,
    )


def read_mix_entry_bytes(
    archive: MixArchiveIndex,
    entry: MixEntry,
    *,
    max_bytes: int = 64 * 1024 * 1024,
) -> bytes | None:
    if entry.size <= 0 or entry.size > max_bytes:
        return None
    data = read_mix_entry_prefix(archive, entry, max_bytes=max_bytes)
    return data if data is not None and len(data) == entry.size else None


def read_mix_entry_prefix(
    archive: MixArchiveIndex,
    entry: MixEntry,
    *,
    max_bytes: int,
) -> bytes | None:
    if max_bytes < 0 or entry.size < 0:
        return None
    entry_start = archive.data_start + entry.offset
    if entry_start + entry.size > archive.source_offset + archive.source_size:
        return None
    bytes_to_read = min(entry.size, max_bytes)
    try:
        with archive.path.open("rb") as source:
            source.seek(entry_start)
            data = source.read(bytes_to_read)
    except OSError:
        return None
    return data if len(data) == bytes_to_read else None


def _identify_entry_types(path: Path, data_start: int, entries: list[MixEntry]) -> list[MixEntry]:
    typed_by_id: dict[int, MixEntry] = {}
    try:
        archive = path.open("rb")
    except OSError:
        return entries
    with archive:
        for entry in sorted(entries, key=lambda item: item.offset):
            raw_suffix = Path(entry.name).suffix.casefold() if entry.name else ""
            suffix = raw_suffix[1:].upper()
            expected_content_type = CONTENT_TYPE_SUFFIX_OVERRIDES.get(raw_suffix)
            if suffix and expected_content_type is None:
                typed_by_id[entry.file_id] = replace(entry, file_type=suffix)
                continue
            if entry.size <= 0:
                typed_by_id[entry.file_id] = replace(
                    entry,
                    file_type=suffix or entry.file_type,
                )
                continue
            archive.seek(data_start + entry.offset)
            prefix = archive.read(min(entry.size, 128))
            if prefix.startswith(b"MZ") and len(prefix) >= 64:
                pe_offset = struct.unpack_from("<I", prefix, 0x3C)[0]
                pe_end = pe_offset + 24
                if pe_end > len(prefix) and pe_end <= min(entry.size, 4096):
                    archive.seek(data_start + entry.offset)
                    prefix = archive.read(pe_end)
            file_type = (
                detect_content_type_for_suffix(prefix, entry.size, raw_suffix)
                or suffix
                or None
            )
            typed_by_id[entry.file_id] = replace(entry, file_type=file_type)
    return [typed_by_id.get(entry.file_id, entry) for entry in entries]


def _read_entry_table(
    path: Path,
    *,
    source_offset: int = 0,
    source_size: int | None = None,
) -> tuple[int, dict[int, tuple[int, int]]]:
    file_size = path.stat().st_size
    source_end = source_offset + source_size if source_size is not None else file_size
    with path.open("rb") as archive:
        archive.seek(source_offset)
        prefix = archive.read(min(10, source_end - source_offset))
        if len(prefix) < 10:
            raise MixFormatError("The file is too small to contain a MIX header.")

        is_cnc_mix = struct.unpack_from("<H", prefix, 0)[0] != 0
        header_offset = 0 if is_cnc_mix else 4
        if not is_cnc_mix and struct.unpack_from("<H", prefix, 2)[0] & 0x2:
            return _read_encrypted_entry_table(archive, prefix, source_end, source_offset)

        count = struct.unpack_from("<H", prefix, header_offset)[0]
        table_start = header_offset + 6
        data_start = source_offset + table_start + count * 12
        if data_start > source_end:
            raise MixFormatError("The MIX entry table extends beyond the end of the file.")
        archive.seek(source_offset + table_start)
        table = archive.read(count * 12)
        if len(table) != count * 12:
            raise MixFormatError("The MIX entry table is incomplete.")
        return data_start, _unpack_entries(table, count, data_start, source_end)


def _read_encrypted_entry_table(
    archive,
    prefix: bytes,
    source_end: int,
    source_offset: int,
) -> tuple[int, dict[int, tuple[int, int]]]:
    if Blowfish is None:
        raise MixFormatError("Encrypted MIX archives require PyCryptodome (Crypto) or PyCryptodomex (Cryptodome).")
    if len(prefix) < 92:
        archive.seek(source_offset)
        prefix = archive.read(min(92, source_end - source_offset))
    if len(prefix) < 92:
        raise MixFormatError("The encrypted MIX header is incomplete.")

    try:
        key = _decrypt_mix_blowfish_key(prefix[4:84])
        cipher = Blowfish.new(key, Blowfish.MODE_ECB)
        first_block = cipher.decrypt(prefix[84:92])
        count, declared_size = struct.unpack_from("<HI", first_block, 0)
        table_length = 6 + count * 12
        encrypted_length = (table_length + 7) // 8 * 8
        encrypted_end = source_offset + 84 + encrypted_length
        if count <= 0 or declared_size <= 0 or encrypted_end > source_end:
            raise MixFormatError("The encrypted MIX header contains invalid sizes.")

        archive.seek(source_offset + 84)
        encrypted_table = archive.read(encrypted_length)
        if len(encrypted_table) != encrypted_length:
            raise MixFormatError("The encrypted MIX entry table is incomplete.")
        table = cipher.decrypt(encrypted_table)[:table_length]
        parsed_count = struct.unpack_from("<H", table, 0)[0]
        if parsed_count != count:
            raise MixFormatError("The encrypted MIX entry table could not be decrypted.")
        return encrypted_end, _unpack_entries(table[6:], count, encrypted_end, source_end)
    except MixFormatError:
        raise
    except Exception as exc:
        raise MixFormatError("The encrypted MIX archive could not be read.") from exc


def _unpack_entries(
    table: bytes,
    count: int,
    data_start: int,
    file_size: int,
) -> dict[int, tuple[int, int]]:
    entries: dict[int, tuple[int, int]] = {}
    for index in range(count):
        file_id, offset, size = struct.unpack_from("<III", table, index * 12)
        if data_start + offset + size <= file_size:
            entries[file_id] = (offset, size)
    return entries


def _decrypt_mix_blowfish_key(encrypted: bytes) -> bytes:
    if len(encrypted) != 80:
        raise ValueError("Encrypted MIX key block must be 80 bytes.")
    der_key = base64.b64decode(WESTWOOD_PUBLIC_KEY)
    modulus = int.from_bytes(der_key[2:], "big")
    output = bytearray()
    for offset in (0, 40):
        cipher_value = int.from_bytes(encrypted[offset : offset + 40], "little")
        plain_value = pow(cipher_value, 0x10001, modulus)
        output.extend(plain_value.to_bytes(39, "little"))
    return bytes(output[:56])


def _find_entry_id(name: str, entries: dict[int, int]) -> int | None:
    return next((file_id for file_id in _mix_file_hashes(name) if file_id in entries), None)


def _read_entry_bytes(
    path: Path,
    data_start: int,
    entry: MixEntry,
    *,
    max_bytes: int = 64 * 1024 * 1024,
    source_end: int | None = None,
) -> bytes | None:
    if entry.size <= 0 or entry.size > max_bytes:
        return None
    entry_start = data_start + entry.offset
    if source_end is not None and entry_start + entry.size > source_end:
        return None
    try:
        with path.open("rb") as archive:
            archive.seek(entry_start)
            data = archive.read(entry.size)
    except OSError:
        return None
    return data if len(data) == entry.size else None


def _names_from_local_database(data: bytes | None) -> tuple[str, ...]:
    if not data or len(data) < 52 or not data.startswith(LOCAL_MIX_DATABASE_SIGNATURE):
        return ()
    count = min(struct.unpack_from("<I", data, 48)[0], _MAX_LOCAL_DATABASE_NAMES)
    names: list[str] = []
    offset = 52
    tokens = 0
    while offset < len(data) and len(names) < count and tokens < _MAX_LOCAL_DATABASE_NAME_TOKENS:
        end = data.find(b"\0", offset)
        if end < 0:
            end = len(data)
        raw_name = data[offset:end]
        offset = end + 1
        tokens += 1
        try:
            name = raw_name.decode("ascii").strip()
        except UnicodeDecodeError:
            continue
        if is_readable_mix_name(name):
            names.append(name)
    return tuple(names)


def _map_candidate_names(
    entries: dict[int, tuple[int, int]],
    names: Iterable[str | MixNameCandidate],
    *,
    candidate_index: MixNameCandidateIndex | None = None,
) -> tuple[dict[int, tuple[str, tuple[str, ...]]], set[int]]:
    if candidate_index is not None:
        return candidate_index.map(entries, names)

    candidates_by_id: dict[int, dict[str, tuple[str, set[str]]]] = {}
    claimed_ids: set[int] = set()
    for raw_candidate in names:
        candidate = _normalize_mix_name_candidate(raw_candidate)
        if candidate is None:
            continue
        name = candidate.name
        source = candidate.source
        matches = {file_id for file_id in _mix_file_hashes(name) if file_id in entries}
        claimed_ids.update(matches)
        if len(matches) == 1:
            file_id = next(iter(matches))
            name_key = name.casefold()
            display_name, sources = candidates_by_id.setdefault(file_id, {}).setdefault(
                name_key,
                (name, set()),
            )
            sources.add(source)
    resolved = {
        file_id: (display_name, tuple(sorted(sources)))
        for file_id, names_for_id in candidates_by_id.items()
        if len(names_for_id) == 1
        for display_name, sources in names_for_id.values()
    }
    return resolved, claimed_ids


def _normalize_mix_name_candidate(
    raw_candidate: str | MixNameCandidate,
) -> MixNameCandidate | None:
    if isinstance(raw_candidate, MixNameCandidate):
        name = raw_candidate.name.strip()
        source = raw_candidate.source
    else:
        name = str(raw_candidate or "").strip()
        source = "External name candidate"
    if not is_readable_mix_name(name):
        return None
    return MixNameCandidate(name, source)


def is_readable_mix_name(name: str) -> bool:
    if not name or name != name.strip() or len(name) > 260 or name in {".", ".."}:
        return False
    if not name.isascii() or any(not character.isprintable() for character in name):
        return False
    return not any(character in '<>:"/\\|?*' for character in name)


@lru_cache(maxsize=100_000)
def _mix_file_hashes(name: str) -> tuple[int, int]:
    return _mix_file_classic_hash(name), _mix_file_crc32_hash(name)


def _prewarm_mix_file_hashes(names: Iterable[str]) -> None:
    for name in names:
        _mix_file_hashes(name)


def _mix_file_classic_hash(name: str) -> int:
    data = name.upper().encode("ascii", errors="ignore")
    data += b"\0" * ((-len(data)) % 4)
    result = 0
    for offset in range(0, len(data), 4):
        word = struct.unpack_from("<I", data, offset)[0]
        result = (((result << 1) | (result >> 31)) + word) & 0xFFFFFFFF
    return result


def _mix_file_crc32_hash(name: str) -> int:
    upper = name.upper()
    length = len(upper)
    padding = 4 - length % 4 if length % 4 else 0
    characters = list(upper + "\0" * padding)
    rounded_length = length // 4 * 4
    if length != rounded_length:
        characters[length] = chr(length - rounded_length)
        for offset in range(1, padding):
            characters[length + offset] = characters[rounded_length]
    return zlib.crc32("".join(characters).encode("ascii", errors="ignore")) & 0xFFFFFFFF
