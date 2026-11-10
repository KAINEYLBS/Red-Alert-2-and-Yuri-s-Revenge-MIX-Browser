from __future__ import annotations

import re
import struct


_INI_SECTION_RE = re.compile(r"(?m)^\s*\[[^\]\r\n]{1,128}\]")
_INI_ASSIGNMENT_RE = re.compile(r"(?m)^\s*[A-Za-z0-9_.$~-]+\s*=")
_PCX_VERSIONS = frozenset({0, 2, 3, 5})
_PCX_BITS_PER_PIXEL = frozenset({1, 2, 4, 8})
_BINK_SIGNATURES = tuple(
    b"BIK" + bytes((version,)) for version in b"fghijklm"
) + (b"KB2a", b"KB2b")
CONTENT_TYPE_SUFFIX_OVERRIDES = {
    ".mmx": "MIX",
    ".mmp": "PCX",
    ".yro": "MIX",
}
MIX_CONTAINER_SUFFIXES = frozenset(
    {".mix"}
    | {
        suffix
        for suffix, file_type in CONTENT_TYPE_SUFFIX_OVERRIDES.items()
        if file_type == "MIX"
    }
)


# @arch mix-browser.detect-content-type-for-suffix utility | en: Applies confirmed extension-specific content type overrides | zh: 应用已确认的扩展名内容类型覆盖规则
def detect_content_type_for_suffix(
    prefix: bytes,
    file_size: int,
    suffix: str,
) -> str | None:
    detected_type = detect_content_type(prefix, file_size)
    expected_type = CONTENT_TYPE_SUFFIX_OVERRIDES.get(suffix.casefold())
    if expected_type is not None and detected_type != expected_type:
        return None
    return detected_type


def detect_content_type(prefix: bytes, file_size: int) -> str | None:
    if _looks_like_mix(prefix, file_size):
        return "MIX"
    if prefix.startswith(b"XCC by Olaf van der Spek"):
        return "DAT"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "JPG"
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if prefix.startswith(b"BM"):
        return "BMP"
    if prefix.startswith(b"DDS "):
        return "DDS"
    if prefix.startswith(b"Voxel Animation"):
        return "VXL"
    if prefix[:4] in _BINK_SIGNATURES:
        return "BINK"
    if prefix.startswith(b"JASC-PAL"):
        return "PAL"
    if prefix.startswith(b"RIFF") and len(prefix) >= 12 and prefix[8:12] == b"PAL ":
        return "PAL"
    if file_size == 768 and len(prefix) >= 128 and all(value <= 63 for value in prefix[:128]):
        return "PAL"
    if len(prefix) >= 4 and prefix[0] == 0x0A and prefix[1] in _PCX_VERSIONS:
        if prefix[2] == 1 and prefix[3] in _PCX_BITS_PER_PIXEL:
            return "PCX"
    if prefix.startswith(b"FCS"):
        return "CSF"
    if prefix.startswith(b"FORM") and prefix[8:12] == b"WVQA":
        return "VQA"
    if prefix.startswith(b"RIFF") and len(prefix) >= 12:
        if prefix[8:12] == b"WAVE":
            return "WAV"
        if prefix[8:12] == b"AVI ":
            return "AVI"
    if prefix.startswith(b"OggS"):
        return "OGG"
    if prefix.startswith(b"MThd"):
        return "MID"
    if prefix.startswith(b"ID3"):
        return "MP3"
    if prefix.startswith(b"PK\x03\x04"):
        return "ZIP"
    if prefix.startswith(b"\x00\x00\x01\x00") and len(prefix) >= 22:
        image_count = struct.unpack_from("<H", prefix, 4)[0]
        directory_end = 6 + image_count * 16
        image_size = struct.unpack_from("<I", prefix, 14)[0]
        image_offset = struct.unpack_from("<I", prefix, 18)[0]
        if (
            0 < image_count <= 64
            and image_offset >= directory_end
            and image_size > 0
            and image_offset + image_size <= file_size
        ):
            return "ICO"
    if _looks_like_shp(prefix, file_size):
        return "SHP"
    if prefix.startswith(b"MZ"):
        return _detect_pe_type(prefix)
    return _detect_text_type(prefix)


def _looks_like_shp(prefix: bytes, file_size: int) -> bool:
    if len(prefix) < 8 or struct.unpack_from("<H", prefix, 0)[0] != 0:
        return False
    width, height, frame_count = struct.unpack_from("<HHH", prefix, 2)
    table_end = 8 + frame_count * 24
    valid_header = (
        1 <= width <= 8192
        and 1 <= height <= 8192
        and 1 <= frame_count <= 2048
        and table_end <= file_size
    )
    if not valid_header:
        return False
    if len(prefix) < 32:
        return True
    frame_width, frame_height = struct.unpack_from("<HH", prefix, 12)
    compression = prefix[16]
    frame_offset = struct.unpack_from("<I", prefix, 28)[0]
    return (
        frame_width <= 8192
        and frame_height <= 8192
        and compression <= 3
        and (frame_offset == 0 or table_end <= frame_offset < file_size)
    )


def _looks_like_mix(prefix: bytes, file_size: int) -> bool:
    if len(prefix) < 10:
        return False
    first_word = struct.unpack_from("<H", prefix, 0)[0]
    if first_word:
        table_end = 6 + first_word * 12
        if table_end > file_size or len(prefix) < 18:
            return False
        _file_id, offset, size = struct.unpack_from("<III", prefix, 6)
        return offset + size <= file_size - table_end

    flags = struct.unpack_from("<H", prefix, 2)[0]
    if flags in (2, 3):
        return file_size >= 92 and any(prefix[4:84])
    if flags not in (0, 1):
        return False

    count = struct.unpack_from("<H", prefix, 4)[0]
    declared_data_size = struct.unpack_from("<I", prefix, 6)[0]
    table_end = 10 + count * 12
    checksum_size = 20 if flags & 1 else 0
    if count <= 0 or table_end > file_size or len(prefix) < 22:
        return False
    _file_id, offset, size = struct.unpack_from("<III", prefix, 10)
    expected_data_size = file_size - table_end - checksum_size
    return (
        expected_data_size >= 0
        and declared_data_size == expected_data_size
        and offset + size <= declared_data_size
    )


def _detect_pe_type(prefix: bytes) -> str:
    if len(prefix) >= 64:
        pe_offset = struct.unpack_from("<I", prefix, 0x3C)[0]
        characteristics_offset = pe_offset + 22
        if (
            prefix[pe_offset : pe_offset + 4] == b"PE\0\0"
            and characteristics_offset + 2 <= len(prefix)
        ):
            characteristics = struct.unpack_from("<H", prefix, characteristics_offset)[0]
            if characteristics & 0x2000:
                return "DLL"
    return "EXE"


def _detect_text_type(prefix: bytes) -> str | None:
    if not prefix:
        return None
    if prefix.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16"
    elif b"\0" in prefix[:256]:
        return None
    else:
        encoding = "utf-8"
    try:
        text = prefix.decode(encoding)
    except UnicodeError:
        text = prefix.decode("latin-1")
    if not text:
        return None
    printable_ratio = sum(character.isprintable() or character in "\r\n\t" for character in text) / len(text)
    if printable_ratio < 0.9:
        return None
    if _INI_SECTION_RE.search(text) and _INI_ASSIGNMENT_RE.search(text):
        return "INI"
    return "TXT"
