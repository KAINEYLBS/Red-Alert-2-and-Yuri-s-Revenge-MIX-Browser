from __future__ import annotations

import struct
from dataclasses import dataclass


LOCAL_MIX_DATABASE_SIGNATURE = b"XCC by Olaf van der Spek"
_MAX_LOCAL_DATABASE_NAMES = 65_535
_MAX_GLOBAL_DATABASE_RECORDS = 100_000
_MAX_DATABASE_STRING_BYTES = 4096


# @arch mix-browser.dat-record model | en: Holds one name and description from an XCC DAT database | zh: 保存 XCC DAT 数据库中的一条名称和描述
@dataclass(frozen=True)
class DatRecord:
    group: str
    name: str
    description: str = ""


# @arch mix-browser.dat-contents model | en: Holds parsed records and the detected XCC DAT format | zh: 保存解析记录与识别出的 XCC DAT 格式
@dataclass(frozen=True)
class DatContents:
    format_name: str
    records: tuple[DatRecord, ...]


# @arch mix-browser.xcc-dat-parser service | en: Parses supported local and global XCC MIX name databases | zh: 解析受支持的本地和全局 XCC MIX 名称数据库
def parse_xcc_dat_contents(
    data: bytes,
    *,
    included_global_groups: frozenset[int] | None = None,
) -> DatContents | None:
    local_contents = _parse_local_mix_database(data)
    if local_contents is not None:
        return local_contents
    return _parse_global_mix_database(data, included_global_groups)


def _parse_local_mix_database(data: bytes) -> DatContents | None:
    if len(data) < 52 or not data.startswith(LOCAL_MIX_DATABASE_SIGNATURE):
        return None
    count = struct.unpack_from("<I", data, 48)[0]
    if count > _MAX_LOCAL_DATABASE_NAMES:
        return None

    records: list[DatRecord] = []
    offset = 52
    for _ in range(count):
        end = data.find(b"\0", offset)
        if end < 0:
            return None
        try:
            name = data[offset:end].decode("ascii")
        except UnicodeDecodeError:
            return None
        records.append(DatRecord("Local MIX names", name))
        offset = end + 1
    return DatContents("Local MIX name database", tuple(records))


def _parse_global_mix_database(
    data: bytes,
    included_groups: frozenset[int] | None,
) -> DatContents | None:
    offset = 0
    records: list[DatRecord] = []
    total_records = 0
    for group_index in range(4):
        if offset + 4 > len(data):
            return None
        count = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        total_records += count
        if total_records > _MAX_GLOBAL_DATABASE_RECORDS:
            return None
        group = f"Database {group_index + 1}"
        for _ in range(count):
            name, offset = _read_database_string(data, offset)
            description, offset = _read_database_string(data, offset)
            if name is None or description is None:
                return None
            if included_groups is None or group_index in included_groups:
                records.append(DatRecord(group, name, description))
    if offset != len(data) or total_records == 0:
        return None
    return DatContents("Global MIX name database", tuple(records))


def _read_database_string(data: bytes, offset: int) -> tuple[str | None, int]:
    end = data.find(b"\0", offset)
    if end < 0 or end - offset > _MAX_DATABASE_STRING_BYTES:
        return None, offset
    try:
        value = data[offset:end].decode("ascii")
    except UnicodeDecodeError:
        return None, offset
    return value, end + 1
