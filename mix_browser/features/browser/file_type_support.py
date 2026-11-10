from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP

from mix_browser.features.archive.type_detection import (
    CONTENT_TYPE_SUFFIX_OVERRIDES,
    MIX_CONTAINER_SUFFIXES,
)


PCX_PREVIEW_SUFFIXES = frozenset(
    {".pcx"}
    | {
        suffix
        for suffix, file_type in CONTENT_TYPE_SUFFIX_OVERRIDES.items()
        if file_type == "PCX"
    }
)

DOCUMENT_PREVIEW_SUFFIXES = frozenset(
    {
        ".bat",
        ".cfg",
        ".csv",
        ".glsl",
        ".htm",
        ".html",
        ".ini",
        ".json",
        ".lcf",
        ".log",
        ".map",
        ".md",
        ".mpr",
        ".txt",
        ".xml",
        ".yrm",
    }
)

DIRECT_PREVIEW_SUFFIXES = frozenset(
    {
        ".shp",
        ".shp-ts",
        ".pcx",
        ".vxl",
        ".pal",
        ".wav",
        ".bik",
        ".bk2",
        ".bink",
        ".dat",
    }
)
DIRECT_PREVIEW_TYPES = frozenset(
    {
        "SHP",
        "SHP-TS",
        "PCX",
        "VXL",
        "PAL",
        "WAV",
        "BIK",
        "BK2",
        "BINK",
        "DAT",
    }
)
DOCUMENT_PREVIEW_TYPES = frozenset({"INI", "TXT"})
VIDEO_PREVIEW_TYPES = frozenset({"BIK", "BK2", "BINK"})
AUDIO_PREVIEW_TYPES = frozenset({"WAV"})
MEDIA_PREVIEW_TYPES = VIDEO_PREVIEW_TYPES | AUDIO_PREVIEW_TYPES
ASSET_PREVIEW_TYPES = DIRECT_PREVIEW_TYPES - MEDIA_PREVIEW_TYPES

MAX_TEXT_PREVIEW_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PREVIEW_BYTES = 64 * 1024 * 1024
MAX_DAT_PREVIEW_BYTES = 64 * 1024 * 1024
MAX_MEDIA_PREVIEW_BYTES = 128 * 1024 * 1024
MAX_IMAGE_PREVIEW_PIXELS = 32 * 1024 * 1024


def _preview_suffixes_for_types(types: frozenset[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            suffix
            for suffix in DIRECT_PREVIEW_SUFFIXES
            if suffix[1:].upper() in types
        )
    )


PREVIEW_FORMAT_GROUPS = (
    (
        QT_TRANSLATE_NOOP("PreviewSupportDialog", "Video"),
        _preview_suffixes_for_types(VIDEO_PREVIEW_TYPES),
    ),
    (
        QT_TRANSLATE_NOOP("PreviewSupportDialog", "Audio"),
        _preview_suffixes_for_types(AUDIO_PREVIEW_TYPES),
    ),
    (
        QT_TRANSLATE_NOOP("PreviewSupportDialog", "SHP animations"),
        _preview_suffixes_for_types(frozenset({"SHP", "SHP-TS"})),
    ),
    (
        QT_TRANSLATE_NOOP("PreviewSupportDialog", "PCX images"),
        tuple(sorted(PCX_PREVIEW_SUFFIXES)),
    ),
    (
        QT_TRANSLATE_NOOP("PreviewSupportDialog", "Palettes"),
        _preview_suffixes_for_types(frozenset({"PAL"})),
    ),
    (
        QT_TRANSLATE_NOOP("PreviewSupportDialog", "Voxel models"),
        _preview_suffixes_for_types(frozenset({"VXL"})),
    ),
    (
        QT_TRANSLATE_NOOP("PreviewSupportDialog", "XCC name data"),
        _preview_suffixes_for_types(frozenset({"DAT"})),
    ),
    (
        QT_TRANSLATE_NOOP("PreviewSupportDialog", "Text documents"),
        tuple(sorted(DOCUMENT_PREVIEW_SUFFIXES)),
    ),
    (
        QT_TRANSLATE_NOOP("PreviewSupportDialog", "Browsable MIX containers"),
        tuple(sorted(MIX_CONTAINER_SUFFIXES)),
    ),
)

SUPPORTED_BROWSER_SUFFIXES = frozenset(
    suffix
    for _group_label, suffixes in PREVIEW_FORMAT_GROUPS
    for suffix in suffixes
) | {".hva"}

OTHER_FILE_TYPE_FILTER = "__other__"
NON_ADJUSTABLE_BROWSER_TYPE_FILTERS = frozenset({"Folder", "MIX"})
DEFAULT_FLAT_BROWSER_TYPE_FILTERS = (
    "SHP",
    "PAL",
    "VXL",
    "HVA",
    "INI|TXT",
    OTHER_FILE_TYPE_FILTER,
)
DEFAULT_VISIBLE_BROWSER_TYPE_FILTERS = DEFAULT_FLAT_BROWSER_TYPE_FILTERS


# @arch mix-browser.recognized-browser-file-type utility | en: Identifies browser-known types used by previews and shared filters | zh: 识别预览与共用筛选所使用的浏览器类型
def recognized_browser_file_type(type_label: str, relative_path: str) -> str | None:
    normalized_type = type_label.strip().upper()
    if normalized_type == "FOLDER":
        return "Folder"
    suffix = Path(relative_path).suffix.casefold()
    if suffix == ".mix":
        return "MIX"
    if suffix in SUPPORTED_BROWSER_SUFFIXES:
        return suffix[1:].upper()
    if normalized_type == "MIX":
        return "MIX"
    if normalized_type == "HVA":
        return "HVA"
    if normalized_type in DIRECT_PREVIEW_TYPES:
        return normalized_type
    if normalized_type in DOCUMENT_PREVIEW_TYPES:
        return normalized_type
    return None


# @arch mix-browser.browser-type-filter-key utility | en: Classifies browser entries into the shared search and table filter categories | zh: 将浏览对象归入搜索和主表共用的筛选分类
def browser_type_filter_key(type_label: str, relative_path: str) -> str:
    file_type = recognized_browser_file_type(type_label, relative_path)
    if file_type in {"INI", "TXT"}:
        return "INI|TXT"
    return file_type or OTHER_FILE_TYPE_FILTER


# @arch mix-browser.browser-type-filter-label utility | en: Formats a shared browser type filter as a readable suffix label | zh: 将共用浏览类型筛选项格式化为可读的后缀标签
def browser_type_filter_label(type_filter: str) -> str:
    if type_filter == OTHER_FILE_TYPE_FILTER:
        return QCoreApplication.translate("BrowserFileType", "Other")
    if type_filter == "INI|TXT":
        return ".ini | .txt"
    return browser_file_type_label(type_filter, "")


# @arch mix-browser.browser-entry-type-display utility | en: Formats a file's actual extension and adds its recognized content role when it differs | zh: 显示文件实际扩展名，并在内容类型不同时补充识别用途
def browser_entry_type_display(type_label: str, relative_path: str) -> str:
    suffix = Path(relative_path).suffix.casefold()
    normalized_type = type_label.strip().upper()
    if suffix:
        extension_type = suffix[1:].upper()
        content_type = CONTENT_TYPE_SUFFIX_OVERRIDES.get(suffix)
        if content_type and normalized_type == content_type:
            return f"{extension_type} ({content_type})"
        return extension_type
    return type_label or "Unknown"


# @arch mix-browser.browser-file-type-label utility | en: Formats browser file types as suffixes or object labels | zh: 将浏览器文件类型格式化为扩展名或对象标签
def browser_file_type_label(type_label: str, relative_path: str) -> str:
    normalized_type = type_label.strip()
    normalized_key = normalized_type.casefold()
    if normalized_key == "folder":
        return QCoreApplication.translate("BrowserFileType", "Folder")
    if normalized_key == "link":
        return QCoreApplication.translate("BrowserFileType", "Link")
    if normalized_key == "file":
        return QCoreApplication.translate("BrowserFileType", "File")
    if normalized_key == "unknown":
        return QCoreApplication.translate("BrowserFileType", "Unknown")

    suffix = Path(relative_path).suffix.casefold()
    if suffix:
        content_type = CONTENT_TYPE_SUFFIX_OVERRIDES.get(suffix)
        if content_type and normalized_type.upper() == content_type:
            return f"{suffix} ({content_type})"
        return suffix

    supported_type = recognized_browser_file_type(type_label, relative_path)
    if supported_type is not None:
        return f".{supported_type.casefold()}"

    if normalized_type and normalized_type.casefold() not in {"file", "unknown"}:
        return f".{normalized_type.lstrip('.').casefold()}"
    return normalized_type or "Unknown"


_OPTIONAL_BROWSER_TYPE_FILTERS = {
    suffix[1:].upper()
    for suffix in SUPPORTED_BROWSER_SUFFIXES
    if suffix not in {".mix", ".ini", ".txt"}
} | {"INI|TXT"}
ALL_BROWSER_TYPE_FILTERS = (
    ("Folder", "MIX")
    + tuple(
        sorted(
            _OPTIONAL_BROWSER_TYPE_FILTERS,
            key=lambda file_type: browser_file_type_label(file_type, "").casefold(),
        )
    )
    + (OTHER_FILE_TYPE_FILTER,)
)
CONFIGURABLE_BROWSER_TYPE_FILTERS = tuple(
    type_filter
    for type_filter in ALL_BROWSER_TYPE_FILTERS
    if type_filter != OTHER_FILE_TYPE_FILTER
)
FILTERABLE_BROWSER_TYPE_FILTERS = tuple(
    type_filter
    for type_filter in ALL_BROWSER_TYPE_FILTERS
    if type_filter not in NON_ADJUSTABLE_BROWSER_TYPE_FILTERS
    and type_filter != OTHER_FILE_TYPE_FILTER
)
