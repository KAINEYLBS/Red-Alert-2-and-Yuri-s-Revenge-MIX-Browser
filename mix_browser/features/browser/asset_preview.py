from __future__ import annotations

import configparser
import hashlib
import io
import json
import math
import os
import re
import struct
import tempfile
import wave
from array import array
from collections.abc import Callable
from concurrent.futures import (
    CancelledError,
    Future,
    TimeoutError as FutureTimeoutError,
)
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
from threading import Event, RLock

from PySide6.QtCore import QCoreApplication, QT_TRANSLATE_NOOP
from PySide6.QtGui import QColor, QImage

from mix_browser.features.archive.dat_format import DatRecord, parse_xcc_dat_contents
from mix_browser.features.archive.domain import (
    MixArchiveIndex,
    MixEntry,
    read_mix_entry_bytes,
    read_mix_entry_prefix,
)
from mix_browser.features.archive.loader import MixArchiveLoader
from mix_browser.features.archive.type_detection import detect_content_type
from mix_browser.shared.application_settings import application_directory
from mix_browser.features.browser.document_data import (
    DocumentPreviewResult,
    load_document_preview,
)
from mix_browser.features.browser.file_type_support import (
    DIRECT_PREVIEW_SUFFIXES as _DIRECT_PREVIEW_SUFFIXES,
    DIRECT_PREVIEW_TYPES as _DIRECT_PREVIEW_TYPES,
    MAX_DAT_PREVIEW_BYTES as _MAX_DAT_PREVIEW_BYTES,
    MAX_IMAGE_PREVIEW_BYTES as _MAX_IMAGE_BYTES,
    MAX_IMAGE_PREVIEW_PIXELS as _MAX_IMAGE_PIXELS,
    MAX_MEDIA_PREVIEW_BYTES as _MAX_MEDIA_BYTES,
)


_MAX_SHP_FRAMES = 2048
_MAX_VXL_LIMBS = 32
_MAX_VXL_VOXELS = 300_000
_MAX_VXL_SURFACE_FACES = 120_000
_VXL_FIXED_HEADER_SIZE = 802
_VXL_LIMB_HEADER_SIZE = 28
_VXL_LIMB_FOOTER_SIZE = 92
_MAX_GAME_PALETTE_ARCHIVES = 2048
_MAX_GAME_PALETTES = 256
_MAX_GAME_RULE_CONFIGS = 16
_MAX_GAME_RULE_CONFIG_BYTES = 4 * 1024 * 1024
_GAME_RULE_CONFIG_NAMES = ("rules.ini", "rulesmd.ini", "art.ini", "artmd.ini")
_PALETTE_RESOURCE_REFERENCE_FIELDS = (
    "image",
    "buildup",
    "bibshape",
    "activeanim",
    "activeanimdamaged",
    "activeanimtwo",
    "activeanimtwodamaged",
    "activeanimthree",
    "activeanimthreedamaged",
    "idleanim",
    "specialanim",
    "specialanimdamaged",
    "specialzoverlay",
    "specialzoverlaydamaged",
)
_ANIMATION_REFERENCE_FIELDS = (
    "anim",
    "animlist",
    "explosion",
    "trailer",
    "traileranim",
    "next",
    "debrisanims",
    "deathanims",
)
_MIN_PALETTE_PREFIX_STEM_LENGTH = 6
_MIN_PALETTE_NAME_SIMILARITY = 0.7
_THEATER_SUFFIXES = {
    "tem": ("unittem.pal", "isotem.pal", "temperat.pal"),
    "sno": ("unitsno.pal", "isosno.pal", "snow.pal"),
    "urb": ("uniturb.pal", "isourb.pal", "urban.pal"),
    "des": ("unitdes.pal", "isodes.pal", "desert.pal"),
    "lun": ("unitlun.pal", "isolun.pal", "lunar.pal"),
    "ubn": ("unitubn.pal", "isoubn.pal", "urbann.pal"),
}
_ISO_ARCHIVE_THEATERS = {
    "tem": "tem",
    "temp": "tem",
    "sno": "sno",
    "snow": "sno",
    "urb": "urb",
    "des": "des",
    "lun": "lun",
    "ubn": "ubn",
}
_THEATER_ARCHIVE_THEATERS = {
    "temperat": "tem",
    "snow": "sno",
    "snowmd": "sno",
    "urban": "urb",
    "desert": "des",
    "des": "des",
    "lunar": "lun",
    "lun": "lun",
    "urbann": "ubn",
    "ubn": "ubn",
}
_NEW_THEATER_PLACEHOLDER_LETTERS = frozenset({"g", "t"})
_THEATER_LETTER_TO_CODE = {
    "a": "sno",
    "d": "des",
    "l": "lun",
    "n": "ubn",
    "t": "tem",
    "u": "urb",
}
_PaletteCancellationSignal = Event | Callable[[], bool] | None


@dataclass(frozen=True)
class IndexedFrame:
    width: int
    height: int
    pixels: bytes
    opaque: bytes | None = None


@dataclass(frozen=True)
class PaletteOption:
    name: str
    colors: tuple[tuple[int, int, int], ...]
    color_count: int
    source: str = ""
    group: str = "other"
    asset_pattern: str = ""


@dataclass(frozen=True)
class _GameArtRuleIndex:
    references: dict[str, tuple[dict[str, str], ...]]
    variants: dict[tuple[str, str], tuple[tuple[str, dict[str, str]], ...]]
    linked_palettes: dict[str, tuple[str, ...]]


# @arch mix-browser.palette-selection-stage model | en: Defines a palette selection stage and its visible matching rules | zh: 定义色盘选择阶段及其展示的匹配规则
@dataclass(frozen=True)
class PaletteSelectionStage:
    key: str
    title: str
    details: tuple[str, ...]


PALETTE_SELECTION_STAGES = (
    PaletteSelectionStage(
        "user_defined",
        QT_TRANSLATE_NOOP("EntryPreviewPane", "User Defined"),
        (
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Check palette-library rows in their configured order."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Run each regular expression with a case-insensitive search against the asset basename, including its extension; an unanchored expression can match part of the name."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "The first matching row is selected. Blank and invalid expressions do not match; palettes with blank expressions remain available for manual selection."),
        ),
    ),
    PaletteSelectionStage(
        "game_rules",
        QT_TRANSLATE_NOOP("EntryPreviewPane", "Game Rule"),
        (
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Read {0} from the configured game folder and from MIX archives under it, including nested MIX archives.").format(", ".join(_GAME_RULE_CONFIG_NAMES)),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Resolve rules by asset section name and Art resource references, including buildup, bib, active animation, idle animation, and special overlay assets. NewTheater variants can link a theater-specific asset back to its base section."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Rules [Animations] and animation-reference fields identify animation SHPs; particle Image references identify particle graphics; [OverlayTypes] and [TerrainTypes] identify terrain SHPs; weapon Projectile links identify projectile Image SHPs; [VoxelAnims] identifies unit-palette VXLs."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Use the first applicable target source in this order: non-default CustomPalette; non-default Palette; enabled AltPalette; enabled NewTheater; enabled AnimPalette; enabled TerrainPalette; Cameo/AltCameo and SidebarImage links; ICON/UICO cameo defaults; then animation, building, terrain, or unit defaults inferred from Art fields and file type. Boolean flags accept yes, true, or 1, case-insensitively. Lower-priority target sources are not tried after a source applies."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "When no explicit Art palette rule applies, smoke names containing SMK, wake and leak names, and the Chrono effect family use the animation palette."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "When a projectile rule linked through Image has FirersPalette=yes, use the firing unit's theater unit palette."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "When Art identifies an object with Cameo or AltCameo but no Foundation, infer its SHP as a unit image; Foundation continues to identify building images."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "CustomPalette values none and default are ignored; otherwise replace ~~~ with the theater code and add .pal when needed. Palette values none and default are ignored. An explicit .pal name is used as written; a base name tries the theater-suffixed name before the unsuffixed name. NewTheater maps second-character A, D, L, N, and U to Snow, Desert, Lunar, New Urban, and Urban; G, T, and unmapped letters use the selected theater. Building-buildup SHPs ending in MK use this filename mapping even when no matching Art section is available. Auto uses tem when no theater can be identified. Theater codes are tem, sno, urb, des, lun, and ubn."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Cameo and AltCameo use UnitArt.CameoPalette, default cameo.pal. SidebarImage uses SidebarPalette, also default cameo.pal. An animation defaults to anim.pal. If AnimPalette is present but disabled and TerrainPalette does not match, the current rule logic returns the theater unit palette. Building, terrain, and unit defaults use theater-specific palettes."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Check only the expected name or names returned by the first applicable target source. For each name, compare palette basenames case-insensitively and check current-MIX/same-folder palettes before game-folder palettes. A local copy wins over a game-folder copy with the same basename, even when their colors differ. If multiple local palettes have that basename, choose by the local candidate order: case-insensitive full name, source, then color values. If that source's returned names are absent from both places, continue to inference instead of trying lower-priority target sources."),
        ),
    ),
    PaletteSelectionStage(
        "inference",
        QT_TRANSLATE_NOOP("EntryPreviewPane", "Inference"),
        (
            QT_TRANSLATE_NOOP("EntryPreviewPane", "First compare asset and palette basename stems for exact equality, case-insensitively, with no minimum-length requirement. Check current-MIX/same-folder palettes before game-folder palettes."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "A SHP in cameo.mix uses cameo.pal when available."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "After exact basename and archive-context matches, a one-frame SHP with a 60 by 48 canvas is treated as a cameo and uses cameo.pal when available; this precedes prefix and similarity matching."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "For SHPs in ISO MIX archives, parse iso<theater> or iso<theater>md and use that theater's ISO palette; temp and snow are aliases for tem and sno. isogen and isogenmd use the configured theater; Auto uses tem. This follows exact basename matching and precedes prefix and similarity matching."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "For SHP assets in a named non-ISO theater MIX, infer the theater from the nearest matching archive name and use its unit palette. Recognized names include temperat, snow/snowmd, urban, desert/des, lunar/lun, and urbann/ubn. This follows exact basename matching and precedes prefix and similarity matching."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "Built-in SHP UI families use their matching game palettes: arrow uses mousepal.pal; ebtn-dn/up use sdbtnanm.pal; pipbrd, pips/pips2, and progbar/progbar2/progbarm use sidebar.pal."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "If there is no exact stem match, compare filename prefixes. A palette stem must contain at least {0} characters and prefix-match the asset stem; the longest match wins. Check current-MIX/same-folder palettes before game-folder palettes.").format(_MIN_PALETTE_PREFIX_STEM_LENGTH),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "If no exact or prefix match applies, compare case-folded filename stems of current-MIX/same-folder palettes with difflib.SequenceMatcher.ratio. Choose the highest-scoring local palette only when its score is greater than {0:.0%}; break ties by case-insensitive palette name, source, then color values.").format(_MIN_PALETTE_NAME_SIMILARITY),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "If no local similarity score is greater than {0:.0%}, compare game-directory palette stems with the same method and threshold. Break ties by case-insensitive palette name, source, then color values.").format(_MIN_PALETTE_NAME_SIMILARITY),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "If neither similarity step matches, choose one local palette deterministically by case-insensitive palette name, source, then color values. Do not choose an unrelated game-directory palette at this step."),
            QT_TRANSLATE_NOOP("EntryPreviewPane", "If inference finds no palette and no local palette is available, use grayscale."),
        ),
    ),
    PaletteSelectionStage(
        "fallback",
        QT_TRANSLATE_NOOP("EntryPreviewPane", "Fallback"),
        (QT_TRANSLATE_NOOP("EntryPreviewPane", "Grayscale is always available and is selected when the earlier stages find no palette."),),
    ),
)

PALETTE_GROUPS = (
    ("fallback", QT_TRANSLATE_NOOP("EntryPreviewPane", "Fallback")),
    ("custom", QT_TRANSLATE_NOOP("EntryPreviewPane", "User Defined")),
    ("local", QT_TRANSLATE_NOOP("EntryPreviewPane", "Same Directory")),
    ("game", QT_TRANSLATE_NOOP("EntryPreviewPane", "Game Directory")),
)


# @arch mix-browser.palette-library-rule model | en: Stores a user palette and the asset-name pattern that selects it | zh: 保存用户色盘及用于匹配资源名的规则
@dataclass(frozen=True)
class PaletteLibraryRule:
    path: Path
    asset_pattern: str = ""


# The persisted index is keyed only by path; explicit refresh is the only invalidation path.
_GAME_PALETTE_CACHE: dict[
    tuple[str, int],
    tuple[tuple[PaletteOption, ...], dict[str, dict[str, str]]],
] = {}
_GAME_PALETTE_INFLIGHT: dict[
    tuple[str, int],
    Future[tuple[tuple[PaletteOption, ...], dict[str, dict[str, str]]]],
] = {}
_GAME_PALETTE_GENERATIONS: dict[str, int] = {}
_GAME_PALETTE_SCHEDULED: set[str] = set()
_GAME_PALETTE_CACHE_LOCK = RLock()
_GAME_PALETTE_DISK_CACHE_VERSION = 10
_GAME_ART_RULE_INDEX_CACHE: dict[
    int,
    tuple[dict[str, dict[str, str]], _GameArtRuleIndex],
] = {}
_MAX_GAME_ART_RULE_INDEX_CACHE = 4


@dataclass(frozen=True)
class VoxelModel:
    vertices: bytes
    vertex_count: int
    voxel_count: int


@dataclass(frozen=True)
class EntryPreviewResult:
    kind: str
    message: str | None = None
    details: tuple[str, ...] = ()
    document: DocumentPreviewResult | None = None
    image: QImage | None = None
    frames: tuple[IndexedFrame, ...] = ()
    voxel_model: VoxelModel | None = None
    palettes: tuple[PaletteOption, ...] = ()
    palette: PaletteOption | None = None
    media_data: bytes = b""
    media_suffix: str = ""
    is_video: bool = False
    default_palette_index: int = 0
    dat_format: str = ""
    dat_records: tuple[DatRecord, ...] = ()
    is_shp: bool = False


def load_entry_preview(
    archive: MixArchiveIndex,
    entry: MixEntry,
    palette_directory: Path | None = None,
    *,
    palette_theater: str = "auto",
    xcc_names_enabled: bool = True,
    community_names_enabled: bool = False,
    palette_library: tuple[PaletteLibraryRule, ...] = (),
    include_game_palettes: bool = True,
    palette_context: tuple[str, ...] = (),
) -> EntryPreviewResult:
    suffix = Path(entry.name or "").suffix.casefold()
    file_type = (entry.file_type or "").casefold()
    asset_type = suffix[1:] if suffix in _DIRECT_PREVIEW_SUFFIXES else file_type
    if asset_type == "mix":
        return EntryPreviewResult(
            "message",
            message=QCoreApplication.translate(
                "EntryPreviewPane",
                "MIX containers are browsed in their own tabs and have no standalone preview.",
            ),
        )
    effective_palette_directory = (
        palette_directory if include_game_palettes else None
    )

    if asset_type in {"shp", "shp-ts"}:
        result = _load_shp_preview(
            archive,
            entry,
            effective_palette_directory,
            palette_theater=palette_theater,
            xcc_names_enabled=xcc_names_enabled,
            community_names_enabled=community_names_enabled,
            palette_library=palette_library,
            palette_context=palette_context,
        )
        return _defer_game_palette_notice(
            result,
            palette_directory,
            include_game_palettes,
        )
    if asset_type == "pcx":
        return _load_pcx_preview(archive, entry)
    if asset_type == "vxl":
        result = _load_vxl_preview(
            archive,
            entry,
            effective_palette_directory,
            palette_theater=palette_theater,
            xcc_names_enabled=xcc_names_enabled,
            community_names_enabled=community_names_enabled,
            palette_library=palette_library,
            palette_context=palette_context,
        )
        return _defer_game_palette_notice(
            result,
            palette_directory,
            include_game_palettes,
        )
    if asset_type == "pal":
        return _load_palette_preview(archive, entry)
    if asset_type == "dat":
        return _load_dat_preview(archive, entry)
    if asset_type in {"wav", "bik", "bk2", "bink"}:
        return _load_media_preview(archive, entry, asset_type)

    document = load_document_preview(archive, entry)
    return EntryPreviewResult(
        "document",
        message=document.message,
        document=document,
    )


def _load_dat_preview(
    archive: MixArchiveIndex,
    entry: MixEntry,
) -> EntryPreviewResult:
    if entry.size > _MAX_DAT_PREVIEW_BYTES:
        return EntryPreviewResult(
            "message",
            message=QCoreApplication.translate("EntryPreviewPane", 'DAT preview is limited to 64 MiB.'),
        )
    data = read_mix_entry_bytes(
        archive,
        entry,
        max_bytes=_MAX_DAT_PREVIEW_BYTES,
    )
    if data is None:
        return EntryPreviewResult("message", message=QCoreApplication.translate("EntryPreviewPane", 'The DAT file could not be read.'))
    contents = parse_xcc_dat_contents(data)
    if contents is None:
        return EntryPreviewResult(
            "message",
            message=QCoreApplication.translate("EntryPreviewPane", 'This DAT format is not a supported XCC MIX name database.'),
        )
    return EntryPreviewResult(
        "dat",
        details=(QCoreApplication.translate("EntryPreviewPane", "{0:,} records").format(len(contents.records)),),
        dat_format=contents.format_name,
        dat_records=contents.records,
    )


def load_path_preview(
    path: Path,
    palette_directory: Path | None = None,
    *,
    palette_theater: str = "auto",
    xcc_names_enabled: bool = True,
    community_names_enabled: bool = False,
    palette_library: tuple[PaletteLibraryRule, ...] = (),
    include_game_palettes: bool = True,
    palette_context: tuple[str, ...] = (),
) -> EntryPreviewResult:
    try:
        metadata = path.stat()
        if not path.is_file():
            return EntryPreviewResult("message", message=QCoreApplication.translate("EntryPreviewPane", 'This entry is not a regular file.'))
        with path.open("rb") as source:
            prefix = source.read(128)
    except OSError as exc:
        return EntryPreviewResult(
            "message",
            message=QCoreApplication.translate(
                "EntryPreviewPane", "The file could not be read: {0}"
            ).format(exc),
        )

    suffix = path.suffix[1:].upper() if path.suffix else ""
    file_type = (
        suffix
        if suffix in _DIRECT_PREVIEW_TYPES
        else detect_content_type(prefix, metadata.st_size) or suffix
    )
    entry = MixEntry(0, 0, metadata.st_size, path.name, file_type=file_type)
    archive = MixArchiveIndex(path, 0, (entry,), 0, metadata.st_size)
    result = load_entry_preview(
        archive,
        entry,
        palette_directory if include_game_palettes else None,
        palette_theater=palette_theater,
        xcc_names_enabled=xcc_names_enabled,
        community_names_enabled=community_names_enabled,
        palette_context=palette_context or tuple(path.parent.parts),
    )
    if result.kind in {"image", "model"} and file_type and file_type.casefold() in {
        "shp",
        "shp-ts",
        "vxl",
    }:
        sibling_palettes = _load_sibling_palettes(path)
        result = _add_palette_sources(
            result,
            entry,
            sibling_palettes=sibling_palettes,
            palette_directory=(
                palette_directory if include_game_palettes else None
            ),
            palette_theater=palette_theater,
            xcc_names_enabled=xcc_names_enabled,
            community_names_enabled=community_names_enabled,
            palette_library=palette_library,
            palette_context=palette_context or tuple(path.parent.parts),
        )
    return _defer_game_palette_notice(
        result,
        palette_directory,
        include_game_palettes,
    )


def _defer_game_palette_notice(
    result: EntryPreviewResult,
    palette_directory: Path | None,
    include_game_palettes: bool,
) -> EntryPreviewResult:
    if (
        include_game_palettes
        or palette_directory is None
        or result.kind not in {"image", "model"}
        or (not result.frames and result.voxel_model is None)
    ):
        return result
    if game_palette_catalog_is_ready_or_loading(palette_directory):
        return replace(result, message=None)
    return replace(
        result,
        message=QCoreApplication.translate(
            "EntryPreviewPane", "Checking configured game palettes..."
        ),
    )


# @arch mix-browser.archive-palette-enrichment service | en: Adds configured game palettes to a decoded MIX entry preview | zh: 为已解码的 MIX 条目预览补充游戏色盘
def load_entry_palette_update(
    result: EntryPreviewResult,
    archive: MixArchiveIndex,
    entry: MixEntry,
    palette_directory: Path,
    *,
    palette_theater: str = "auto",
    xcc_names_enabled: bool = True,
    community_names_enabled: bool = False,
    palette_library: tuple[PaletteLibraryRule, ...] = (),
    cancellation_event: Event | None = None,
    palette_context: tuple[str, ...] = (),
) -> EntryPreviewResult:
    return _add_palette_sources(
        result,
        entry,
        archive=archive,
        palette_directory=palette_directory,
        palette_theater=palette_theater,
        xcc_names_enabled=xcc_names_enabled,
        community_names_enabled=community_names_enabled,
        palette_library=palette_library,
        cancellation_event=cancellation_event,
        palette_context=palette_context,
    )


# @arch mix-browser.directory-palette-enrichment service | en: Adds configured game palettes to a decoded directory preview | zh: 为已解码的目录文件预览补充游戏色盘
def load_path_palette_update(
    result: EntryPreviewResult,
    path: Path,
    entry: MixEntry,
    palette_directory: Path,
    *,
    palette_theater: str = "auto",
    xcc_names_enabled: bool = True,
    community_names_enabled: bool = False,
    palette_library: tuple[PaletteLibraryRule, ...] = (),
    cancellation_event: Event | None = None,
    palette_context: tuple[str, ...] = (),
) -> EntryPreviewResult:
    return _add_palette_sources(
        result,
        entry,
        sibling_palettes=_load_sibling_palettes(path),
        palette_directory=palette_directory,
        palette_theater=palette_theater,
        xcc_names_enabled=xcc_names_enabled,
        community_names_enabled=community_names_enabled,
        palette_library=palette_library,
        cancellation_event=cancellation_event,
        palette_context=palette_context or tuple(path.parent.parts),
    )


def indexed_frame_image(
    frame: IndexedFrame,
    palette: PaletteOption,
    *,
    transparent_zero: bool = False,
    shadow_mask: bool = False,
) -> QImage:
    stride = (frame.width + 3) & ~3
    pixels = bytearray(stride * frame.height)
    for row in range(frame.height):
        start = row * frame.width
        pixels[row * stride : row * stride + frame.width] = frame.pixels[
            start : start + frame.width
        ]
    colors = list(palette.colors[:256])
    if len(colors) < 256:
        colors.extend(((0, 0, 0),) * (256 - len(colors)))
    color_table = [QColor(*color).rgba() for color in colors]
    if transparent_zero:
        color_table[0] = QColor(0, 0, 0, 0).rgba()
    if shadow_mask:
        color_table[1:] = [QColor(0, 0, 0, 128).rgba()] * 255
    image = QImage(
        pixels,
        frame.width,
        frame.height,
        stride,
        QImage.Format.Format_Indexed8,
    ).copy()
    image.setColorTable(color_table)
    return image


def decode_pcx(data: bytes) -> tuple[QImage, int, int]:
    if len(data) < 128 or data[0] != 0x0A or data[2] != 1:
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The PCX header is invalid or unsupported.'))
    version = data[1]
    bits_per_plane = data[3]
    if version not in {0, 2, 3, 5} or bits_per_plane not in {1, 2, 4, 8}:
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'This PCX version or bit depth is not supported.'))

    x_min, y_min, x_max, y_max = struct.unpack_from("<HHHH", data, 4)
    width = x_max - x_min + 1
    height = y_max - y_min + 1
    planes = data[65]
    bytes_per_line = struct.unpack_from("<H", data, 66)[0]
    if (
        width <= 0
        or height <= 0
        or width * height > _MAX_IMAGE_PIXELS
        or planes not in {1, 2, 3, 4}
        or bytes_per_line < (width * bits_per_plane + 7) // 8
    ):
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The PCX image dimensions or plane layout are invalid.'))
    if bits_per_plane == 8 and planes not in {1, 3}:
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'Only indexed and RGB 8-bit PCX images are supported.'))

    pixel_bytes_per_row = bytes_per_line * planes
    decoded_size = pixel_bytes_per_row * height
    if decoded_size > _MAX_IMAGE_PIXELS * 4:
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The decoded PCX image exceeds the preview limit.'))

    palette_marker = len(data) - 769 if bits_per_plane == 8 and planes == 1 else len(data)
    if palette_marker >= 128 and data[palette_marker : palette_marker + 1] == b"\x0c":
        encoded_end = palette_marker
        extended_palette = data[palette_marker + 1 : palette_marker + 769]
    else:
        encoded_end = len(data)
        extended_palette = b""

    raster = bytearray(decoded_size)
    input_offset = 128
    output_offset = 0
    while output_offset < decoded_size:
        if input_offset >= encoded_end:
            raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The PCX image data is incomplete.'))
        value = data[input_offset]
        input_offset += 1
        if value & 0xC0 == 0xC0:
            count = value & 0x3F
            if count == 0 or input_offset >= encoded_end:
                raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The PCX run-length stream is invalid.'))
            value = data[input_offset]
            input_offset += 1
        else:
            count = 1
        if output_offset + count > decoded_size:
            raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The PCX run-length stream exceeds the image dimensions.'))
        raster[output_offset : output_offset + count] = bytes((value,)) * count
        output_offset += count

    if bits_per_plane == 8 and planes == 3:
        stride = width * 4
        rgba = bytearray(stride * height)
        for y in range(height):
            source = y * pixel_bytes_per_row
            target = y * stride
            red = raster[source : source + bytes_per_line]
            green = raster[source + bytes_per_line : source + bytes_per_line * 2]
            blue = raster[source + bytes_per_line * 2 : source + bytes_per_line * 3]
            for x in range(width):
                offset = target + x * 4
                rgba[offset : offset + 4] = bytes((red[x], green[x], blue[x], 255))
        image = QImage(rgba, width, height, stride, QImage.Format.Format_RGBA8888).copy()
        return image, width, height

    if extended_palette:
        palette_colors = _rgb_triplets(extended_palette[:768])
    else:
        palette_colors = _rgb_triplets(data[16:64])[:16]
    palette = _palette_with_fallback(palette_colors, "PCX palette")
    index_stride = (width + 3) & ~3
    indexes = bytearray(index_stride * height)
    for y in range(height):
        row_start = y * pixel_bytes_per_row
        for x in range(width):
            if bits_per_plane == 8:
                index = raster[row_start + x]
            else:
                value_mask = (1 << bits_per_plane) - 1
                packed_offset = x * bits_per_plane
                byte_offset = packed_offset // 8
                bit_shift = 8 - bits_per_plane - (packed_offset % 8)
                index = 0
                for plane in range(planes):
                    component = (raster[row_start + plane * bytes_per_line + byte_offset] >> bit_shift) & value_mask
                    index |= component << (plane * bits_per_plane)
            indexes[y * index_stride + x] = index

    compact_indexes = bytearray(width * height)
    for y in range(height):
        compact_indexes[y * width : (y + 1) * width] = indexes[
            y * index_stride : y * index_stride + width
        ]
    indexed = IndexedFrame(width, height, bytes(compact_indexes))
    image = indexed_frame_image(indexed, palette)
    return image, width, height


def decode_westwood_palette(data: bytes) -> tuple[tuple[int, int, int], ...]:
    if data.startswith(b"JASC-PAL"):
        lines = data.decode("ascii", errors="strict").replace("\r", "").split("\n")
        if len(lines) < 3 or lines[1].strip() not in {"0100", "0101"}:
            raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The JASC palette header is invalid.'))
        count = int(lines[2].strip())
        if not 1 <= count <= 256 or len(lines) < 3 + count:
            raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The JASC palette color count is invalid.'))
        colors = []
        for line in lines[3 : 3 + count]:
            channels = tuple(int(value) for value in line.split())
            if len(channels) != 3 or any(value < 0 or value > 255 for value in channels):
                raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A JASC palette color is invalid.'))
            colors.append(channels)
        return tuple(colors)

    if data.startswith(b"RIFF") and len(data) >= 16 and data[8:12] == b"PAL ":
        offset = 12
        while offset + 8 <= len(data):
            chunk_id = data[offset : offset + 4]
            chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
            start = offset + 8
            end = start + chunk_size
            if end > len(data):
                raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The RIFF palette chunk is incomplete.'))
            if chunk_id == b"data":
                chunk = data[start:end]
                if len(chunk) < 4 or struct.unpack_from("<H", chunk, 0)[0] != 0x0300:
                    raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The RIFF palette header is invalid.'))
                count = struct.unpack_from("<H", chunk, 2)[0]
                if not 1 <= count <= 256 or len(chunk) < 4 + count * 4:
                    raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The RIFF palette color count is invalid.'))
                return tuple(
                    tuple(chunk[4 + index * 4 : 7 + index * 4])
                    for index in range(count)
                )
            offset = end + (chunk_size & 1)
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The RIFF palette has no data chunk.'))

    if len(data) == 768:
        values = tuple(data)
        scale = 4 if max(values, default=0) <= 63 else 1
        return tuple(
            tuple(
                (values[index + channel] * 255 // 63)
                if scale == 4
                else values[index + channel]
                for channel in range(3)
            )
            for index in range(0, 768, 3)
        )
    raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'Only Westwood raw, JASC, and RIFF PAL palettes are supported.'))


# @arch mix-browser-shp-ts-decoder utility | en: Decodes TS/RA2 SHP animation frames | zh: 解码 TS/RA2 SHP 动画帧
def decode_shp_ts(data: bytes) -> tuple[int, int, tuple[IndexedFrame, ...]]:
    if len(data) < 8 or struct.unpack_from("<H", data, 0)[0] != 0:
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The file is not a supported TS/RA2 SHP sprite.'))
    canvas_width, canvas_height, frame_count = struct.unpack_from("<HHH", data, 2)
    if (
        not 1 <= frame_count <= _MAX_SHP_FRAMES
        or not 1 <= canvas_width <= 8192
        or not 1 <= canvas_height <= 8192
        or canvas_width * canvas_height * frame_count > _MAX_IMAGE_PIXELS
    ):
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The SHP frame table or dimensions exceed the preview limit.'))
    table_end = 8 + frame_count * 24
    if table_end > len(data):
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The SHP frame table is incomplete.'))

    headers: list[tuple[int, int, int, int, int, int]] = []
    for index in range(frame_count):
        offset = 8 + index * 24
        x, y, width, height = struct.unpack_from("<HHHH", data, offset)
        compression = data[offset + 8]
        frame_offset = struct.unpack_from("<I", data, offset + 20)[0]
        if compression > 3 or width > 8192 or height > 8192:
            raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The SHP frame header uses unsupported values.'))
        if frame_offset and not table_end <= frame_offset < len(data):
            raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A SHP frame offset extends beyond the sprite data.'))
        headers.append((x, y, width, height, compression, frame_offset))

    sorted_offsets = sorted({header[5] for header in headers if header[5]})
    next_offsets = {
        offset: sorted_offsets[index + 1] if index + 1 < len(sorted_offsets) else len(data)
        for index, offset in enumerate(sorted_offsets)
    }
    frames = []
    total_pixels = 0
    for x, y, width, height, compression, frame_offset in headers:
        if not frame_offset or width == 0 or height == 0:
            frames.append(IndexedFrame(canvas_width, canvas_height, bytes(canvas_width * canvas_height)))
            total_pixels += canvas_width * canvas_height
            continue
        total_pixels += canvas_width * canvas_height
        if total_pixels > _MAX_IMAGE_PIXELS:
            raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The SHP animation exceeds the preview memory limit.'))
        frame_end = next_offsets[frame_offset]
        frame_data = memoryview(data)[frame_offset:frame_end]
        frame_pixels = bytearray(width * height)
        cursor = 0
        for row in range(height):
            row_start = row * width
            if compression in {0, 1}:
                if cursor + width > len(frame_data):
                    raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'An uncompressed SHP frame is incomplete.'))
                frame_pixels[row_start : row_start + width] = frame_data[cursor : cursor + width]
                cursor += width
                continue

            if cursor + 2 > len(frame_data):
                raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A compressed SHP scanline header is incomplete.'))
            scanline_size = struct.unpack_from("<H", frame_data, cursor)[0]
            cursor += 2
            encoded_size = scanline_size - 2
            if encoded_size < 0 or cursor + encoded_size > len(frame_data):
                raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A compressed SHP scanline exceeds its frame range.'))
            encoded = frame_data[cursor : cursor + encoded_size]
            cursor += encoded_size
            if compression == 2:
                if len(encoded) != width:
                    raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A compressed SHP scanline has an unexpected width.'))
                frame_pixels[row_start : row_start + width] = encoded
                continue

            output = 0
            source = 0
            while source < len(encoded) and output < width:
                value = encoded[source]
                source += 1
                if value == 0:
                    if source >= len(encoded):
                        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A SHP zero-run is incomplete.'))
                    count = encoded[source]
                    source += 1
                    run_length = count or 1
                    # Pixels beyond the declared scanline are transparent and invisible.
                    output += min(run_length, width - output)
                else:
                    frame_pixels[row_start + output] = value
                    output += 1
            if output != width:
                raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A compressed SHP scanline does not fill its frame width.'))

        canvas = bytearray(canvas_width * canvas_height)
        copy_width = max(0, min(width, canvas_width - x))
        copy_height = max(0, min(height, canvas_height - y))
        for row in range(copy_height):
            source_start = row * width
            target_start = (y + row) * canvas_width + x
            canvas[target_start : target_start + copy_width] = frame_pixels[
                source_start : source_start + copy_width
            ]
        frames.append(IndexedFrame(canvas_width, canvas_height, bytes(canvas)))
    return canvas_width, canvas_height, tuple(frames)


def decode_vxl(data: bytes) -> VoxelModel:
    if len(data) < _VXL_FIXED_HEADER_SIZE or not data[:16].startswith(b"Voxel Animation"):
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The VXL header is invalid.'))
    limb_count = struct.unpack_from("<I", data, 20)[0]
    body_size = struct.unpack_from("<I", data, 28)[0]
    if not 1 <= limb_count <= _MAX_VXL_LIMBS:
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The VXL limb count exceeds the preview limit.'))

    limb_headers_end = _VXL_FIXED_HEADER_SIZE + limb_count * _VXL_LIMB_HEADER_SIZE
    body_end = limb_headers_end + body_size
    footer_end = body_end + limb_count * _VXL_LIMB_FOOTER_SIZE
    if limb_headers_end > len(data) or footer_end > len(data):
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The VXL section table is incomplete.'))

    limbs: list[
        tuple[
            list[tuple[int, int, int, int]],
            tuple[float, float, float],
            tuple[float, float, float],
            float,
        ]
    ] = []
    voxel_count = 0
    model_min = [float("inf"), float("inf"), float("inf")]
    model_max = [float("-inf"), float("-inf"), float("-inf")]
    for limb_index in range(limb_count):
        footer = body_end + limb_index * _VXL_LIMB_FOOTER_SIZE
        limb_offset = struct.unpack_from("<I", data, footer)[0]
        scale = struct.unpack_from("<f", data, footer + 12)[0]
        bounds = struct.unpack_from("<6f", data, footer + 64)
        size_x, size_y, size_z = data[footer + 88 : footer + 91]
        columns = size_x * size_y
        if not size_x or not size_y or not size_z or columns > _MAX_VXL_VOXELS:
            continue
        table = limb_headers_end + limb_offset
        voxel_data = table + columns * 8
        if table < limb_headers_end or voxel_data > body_end:
            raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A VXL limb data offset is invalid.'))
        starts = struct.unpack_from(f"<{columns}i", data, table)
        ends = struct.unpack_from(f"<{columns}i", data, table + columns * 4)
        limb_points = []
        for column, (relative_start, relative_end) in enumerate(zip(starts, ends, strict=True)):
            if relative_start == -1:
                continue
            if (
                relative_start < 0
                or relative_end < relative_start
                or voxel_data + relative_end >= body_end
            ):
                raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A VXL column span is outside the limb data range.'))
            cursor = voxel_data + relative_start
            end = voxel_data + relative_end + 1
            z = 0
            x = column % size_x
            y = column // size_x
            while z < size_z and cursor < end:
                if cursor + 2 > end:
                    raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A VXL voxel span header is incomplete.'))
                skip = data[cursor]
                count = data[cursor + 1]
                cursor += 2
                z += skip
                if z > size_z or z + count > size_z or cursor + count * 2 + 1 > end:
                    raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A VXL voxel span is malformed.'))
                for _ in range(count):
                    color = data[cursor]
                    cursor += 2
                    limb_points.append((x, y, z, color))
                    z += 1
                duplicate_count = data[cursor]
                cursor += 1
                if duplicate_count != count:
                    raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A VXL span length marker does not match its data.'))
            if cursor != end:
                raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'A VXL column ended before its declared height.'))

        voxel_count += len(limb_points)
        if voxel_count > _MAX_VXL_VOXELS:
            raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The VXL model exceeds the preview voxel limit.'))
        min_x, min_y, min_z, max_x, max_y, max_z = bounds
        extents = (max_x - min_x, max_y - min_y, max_z - min_z)
        valid_bounds = all(math.isfinite(value) and value > 0 for value in extents)
        safe_scale = scale if 0.001 <= abs(scale) <= 1000 else 1.0
        if valid_bounds:
            origin = (min_x, min_y, min_z)
            dimensions = (size_x, size_y, size_z)
            voxel_size = tuple(
                extents[axis] / dimensions[axis] for axis in range(3)
            )
        else:
            origin = (0.0, 0.0, 0.0)
            voxel_size = (1.0, 1.0, 1.0)
        for x, y, z, _color in limb_points:
            coordinates = (x, y, z)
            for axis in range(3):
                center = (
                    origin[axis]
                    + (coordinates[axis] + 0.5) * voxel_size[axis]
                ) * safe_scale
                half_size = abs(voxel_size[axis] * safe_scale) * 0.5
                model_min[axis] = min(model_min[axis], center - half_size)
                model_max[axis] = max(model_max[axis], center + half_size)
        limbs.append((limb_points, origin, voxel_size, safe_scale))

    if not voxel_count:
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The VXL file contains no renderable voxel spans.'))
    model_center = tuple(
        (model_min[axis] + model_max[axis]) * 0.5 for axis in range(3)
    )
    model_diameter = max(model_max[axis] - model_min[axis] for axis in range(3))
    if not math.isfinite(model_diameter) or model_diameter <= 0:
        model_diameter = 1.0
    normalization = 2.0 / model_diameter
    vertices = array("f")
    face_count = 0
    face_specs = (
        (
            (1, 0, 0),
            (1.0, 0.0, 0.0),
            ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)),
        ),
        (
            (-1, 0, 0),
            (-1.0, 0.0, 0.0),
            ((-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1)),
        ),
        (
            (0, 1, 0),
            (0.0, 1.0, 0.0),
            ((1, 1, -1), (-1, 1, -1), (-1, 1, 1), (1, 1, 1)),
        ),
        (
            (0, -1, 0),
            (0.0, -1.0, 0.0),
            ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)),
        ),
        (
            (0, 0, 1),
            (0.0, 0.0, 1.0),
            ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)),
        ),
        (
            (0, 0, -1),
            (0.0, 0.0, -1.0),
            ((-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1)),
        ),
    )
    triangle_vertices = (0, 1, 2, 0, 2, 3)
    for limb_points, origin, voxel_size, safe_scale in limbs:
        occupied = {(x, y, z) for x, y, z, _color in limb_points}
        normal_sign = -1.0 if safe_scale < 0 else 1.0
        for x, y, z, color in limb_points:
            coordinates = (x, y, z)
            center = tuple(
                (
                    origin[axis]
                    + (coordinates[axis] + 0.5) * voxel_size[axis]
                )
                * safe_scale
                for axis in range(3)
            )
            half_sizes = tuple(abs(voxel_size[axis] * safe_scale) * 0.5 for axis in range(3))
            for neighbor, normal, corners in face_specs:
                if (x + neighbor[0], y + neighbor[1], z + neighbor[2]) in occupied:
                    continue
                face_count += 1
                if face_count > _MAX_VXL_SURFACE_FACES:
                    raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The VXL model surface exceeds the preview mesh limit.'))
                for corner_index in triangle_vertices:
                    corner = corners[corner_index]
                    vertices.extend(
                        (
                            (center[0] + corner[0] * half_sizes[0] - model_center[0]) * normalization,
                            (center[1] + corner[1] * half_sizes[1] - model_center[1]) * normalization,
                            (center[2] + corner[2] * half_sizes[2] - model_center[2]) * normalization,
                            normal[0] * normal_sign,
                            normal[1] * normal_sign,
                            normal[2] * normal_sign,
                            float(color),
                        )
                    )

    if not face_count:
        raise ValueError(QCoreApplication.translate("EntryPreviewPane", 'The VXL file contains no renderable voxel surfaces.'))
    return VoxelModel(vertices.tobytes(), len(vertices) // 7, voxel_count)


def _load_shp_preview(
    archive: MixArchiveIndex,
    entry: MixEntry,
    palette_directory: Path | None,
    *,
    palette_theater: str,
    xcc_names_enabled: bool,
    community_names_enabled: bool,
    palette_library: tuple[PaletteLibraryRule, ...],
    palette_context: tuple[str, ...],
) -> EntryPreviewResult:
    data = read_mix_entry_bytes(archive, entry, max_bytes=_MAX_IMAGE_BYTES)
    if data is None:
        return EntryPreviewResult("message", message=QCoreApplication.translate("EntryPreviewPane", 'The SHP sprite is too large or could not be read.'))
    try:
        canvas_width, canvas_height, frames = decode_shp_ts(data)
    except (ValueError, struct.error) as exc:
        return EntryPreviewResult("message", message=str(exc))
    result = EntryPreviewResult(
        "image",
        details=(
            QCoreApplication.translate(
                "EntryPreviewPane", "SHP animation | {0} x {1} | {2} frames"
            ).format(canvas_width, canvas_height, len(frames)),
        ),
        frames=frames,
        is_shp=True,
    )
    return _add_palette_sources(
        result,
        entry,
        archive=archive,
        palette_directory=palette_directory,
        palette_theater=palette_theater,
        xcc_names_enabled=xcc_names_enabled,
        community_names_enabled=community_names_enabled,
        palette_library=palette_library,
        palette_context=palette_context,
    )


def _load_pcx_preview(archive: MixArchiveIndex, entry: MixEntry) -> EntryPreviewResult:
    data = read_mix_entry_bytes(archive, entry, max_bytes=_MAX_IMAGE_BYTES)
    if data is None:
        return EntryPreviewResult("message", message=QCoreApplication.translate("EntryPreviewPane", 'The PCX image is too large or could not be read.'))
    try:
        image, width, height = decode_pcx(data)
    except (ValueError, struct.error) as exc:
        return EntryPreviewResult("message", message=str(exc))
    return EntryPreviewResult(
        "image",
        details=(
            QCoreApplication.translate("EntryPreviewPane", "PCX image | {0} x {1}").format(width, height),
        ),
        image=image,
    )


def _load_palette_preview(archive: MixArchiveIndex, entry: MixEntry) -> EntryPreviewResult:
    data = read_mix_entry_bytes(archive, entry, max_bytes=64 * 1024)
    if data is None:
        return EntryPreviewResult("message", message=QCoreApplication.translate("EntryPreviewPane", 'The PAL file could not be read.'))
    try:
        colors = decode_westwood_palette(data)
    except (UnicodeError, ValueError, struct.error) as exc:
        return EntryPreviewResult("message", message=str(exc))
    option = PaletteOption(
        entry.name or QCoreApplication.translate("EntryPreviewPane", "PAL palette"),
        _pad_colors(colors),
        len(colors),
    )
    return EntryPreviewResult(
        "palette",
        details=(
            QCoreApplication.translate("EntryPreviewPane", "Palette | {0} colors").format(len(colors)),
        ),
        palette=option,
    )


def _load_vxl_preview(
    archive: MixArchiveIndex,
    entry: MixEntry,
    palette_directory: Path | None,
    *,
    palette_theater: str,
    xcc_names_enabled: bool,
    community_names_enabled: bool,
    palette_library: tuple[PaletteLibraryRule, ...],
    palette_context: tuple[str, ...],
) -> EntryPreviewResult:
    data = read_mix_entry_bytes(archive, entry, max_bytes=_MAX_IMAGE_BYTES)
    if data is None:
        return EntryPreviewResult("message", message=QCoreApplication.translate("EntryPreviewPane", 'The VXL model is too large or could not be read.'))
    try:
        model = decode_vxl(data)
    except (ValueError, struct.error, OverflowError) as exc:
        return EntryPreviewResult("message", message=str(exc))
    result = EntryPreviewResult(
        "model",
        details=(
            QCoreApplication.translate("EntryPreviewPane", "VXL model | {0:,} voxels").format(model.voxel_count),
        ),
        voxel_model=model,
    )
    return _add_palette_sources(
        result,
        entry,
        archive=archive,
        palette_directory=palette_directory,
        palette_theater=palette_theater,
        xcc_names_enabled=xcc_names_enabled,
        community_names_enabled=community_names_enabled,
        palette_library=palette_library,
        palette_context=palette_context,
    )


def _load_media_preview(
    archive: MixArchiveIndex,
    entry: MixEntry,
    asset_type: str,
) -> EntryPreviewResult:
    data = read_mix_entry_bytes(archive, entry, max_bytes=_MAX_MEDIA_BYTES)
    if data is None:
        return EntryPreviewResult(
            "message",
            message=QCoreApplication.translate(
                "EntryPreviewPane",
                "The {0} file is too large for the in-memory media preview or could not be read.",
            ).format(asset_type.upper()),
        )
    is_video = asset_type in {"bik", "bk2", "bink"}
    details = [
        QCoreApplication.translate("EntryPreviewPane", "Bink video")
        if is_video
        else QCoreApplication.translate("EntryPreviewPane", "WAV audio")
    ]
    if not is_video:
        try:
            with wave.open(io.BytesIO(data), "rb") as source:
                channels = source.getnchannels()
                rate = source.getframerate()
                duration = source.getnframes() / rate if rate else 0
                details.append(
                    QCoreApplication.translate(
                        "EntryPreviewPane", "{0} channels | {1:,} Hz | {2:.1f} s"
                    ).format(channels, rate, duration)
                )
        except (wave.Error, EOFError):
            details.append(
                QCoreApplication.translate("EntryPreviewPane", "Audio details unavailable")
            )
    return EntryPreviewResult(
        "media",
        details=tuple(details),
        media_data=data,
        media_suffix=(".bk2" if asset_type == "bk2" else ".bik") if is_video else ".wav",
        is_video=is_video,
    )


def _load_archive_palettes(archive: MixArchiveIndex, current_entry: MixEntry) -> tuple[PaletteOption, ...]:
    palettes = []
    for entry in archive.entries:
        if entry.file_id == current_entry.file_id:
            continue
        suffix = Path(entry.name or "").suffix.casefold()
        if suffix != ".pal" and (entry.file_type or "").casefold() != "pal":
            continue
        data = read_mix_entry_bytes(archive, entry, max_bytes=64 * 1024)
        if data is None:
            continue
        try:
            colors = decode_westwood_palette(data)
        except (UnicodeError, ValueError, struct.error):
            continue
        name = entry.name or QCoreApplication.translate(
            "EntryPreviewPane", "Unknown palette (0x{0:08X})"
        ).format(entry.file_id)
        palettes.append(
            PaletteOption(
                name,
                _pad_colors(colors),
                len(colors),
                QT_TRANSLATE_NOOP("EntryPreviewPane", "Current MIX"),
                "local",
            )
        )
        if len(palettes) >= 64:
            break
    return tuple(palettes)


def _load_sibling_palettes(path: Path) -> tuple[PaletteOption, ...]:
    palettes = []
    try:
        siblings = path.parent.iterdir()
        for candidate in siblings:
            if candidate.suffix.casefold() != ".pal" or candidate == path:
                continue
            try:
                if not candidate.is_file() or candidate.stat().st_size > 64 * 1024:
                    continue
                data = candidate.read_bytes()
                colors = decode_westwood_palette(data)
            except (OSError, UnicodeError, ValueError, struct.error):
                continue
            palettes.append(
                PaletteOption(
                    candidate.name,
                    _pad_colors(colors),
                    len(colors),
                    QT_TRANSLATE_NOOP("EntryPreviewPane", "Same folder"),
                    "local",
                )
            )
            if len(palettes) >= 64:
                break
    except OSError:
        return ()
    return tuple(palettes)


def _load_palette_library(
    rules: tuple[PaletteLibraryRule, ...],
) -> tuple[PaletteOption, ...]:
    palettes = []
    for rule in rules:
        path = rule.path.expanduser()
        try:
            if not path.is_file() or path.stat().st_size > 64 * 1024:
                continue
            colors = decode_westwood_palette(path.read_bytes())
        except (OSError, UnicodeError, ValueError, struct.error):
            continue
        palettes.append(
            PaletteOption(
                path.name,
                _pad_colors(colors),
                len(colors),
                QT_TRANSLATE_NOOP("EntryPreviewPane", "User library: {0}").format(path),
                "custom",
                rule.asset_pattern,
            )
        )
    return tuple(palettes)


# @arch mix-browser.preview-palette-selection utility | en: Selects automatic palette matches and groups the available sources | zh: 自动匹配色盘并按来源分组候选项
def _add_palette_sources(
    result: EntryPreviewResult,
    entry: MixEntry,
    *,
    archive: MixArchiveIndex | None = None,
    sibling_palettes: tuple[PaletteOption, ...] = (),
    palette_directory: Path | None = None,
    palette_theater: str = "auto",
    xcc_names_enabled: bool = True,
    community_names_enabled: bool = False,
    palette_library: tuple[PaletteLibraryRule, ...] = (),
    cancellation_event: Event | Callable[[], bool] | None = None,
    custom_palette_options: tuple[PaletteOption, ...] | None = None,
    game_palette_catalog: tuple[
        tuple[PaletteOption, ...], dict[str, dict[str, str]]
    ] | None = None,
    palette_context: tuple[str, ...] = (),
) -> EntryPreviewResult:
    custom_palettes = (
        custom_palette_options
        if custom_palette_options is not None
        else _load_palette_library(palette_library)
    )
    palettes: list[PaletteOption] = list(custom_palettes)
    if archive is not None:
        palettes.extend(_load_archive_palettes(archive, entry))
    palettes.extend(sibling_palettes)
    art_rules: dict[str, dict[str, str]] = {}
    if palette_directory is not None:
        if game_palette_catalog is None:
            game_palettes, art_rules = _load_game_palette_catalog(
                palette_directory,
                cancellation_event=cancellation_event,
            )
        else:
            game_palettes, art_rules = game_palette_catalog
        palettes.extend(game_palettes)
    gray = _grayscale_palette()
    palettes.append(gray)

    unique: dict[tuple[object, ...], PaletteOption] = {}
    for palette in palettes:
        if palette.group == "custom":
            identity: tuple[object, ...] = (
                "custom",
                palette.name.casefold(),
                palette.colors,
                palette.source,
                palette.asset_pattern,
            )
        elif palette.group == "fallback":
            identity = ("fallback", palette.name.casefold(), palette.colors)
        else:
            identity = (palette.name.casefold(), palette.colors)
        unique.setdefault(identity, palette)
    selectable_palettes = [
        palette
        for palette in palettes
        if palette.group not in {"custom", "fallback"}
    ]
    matched_custom = next(
        (
            palette
            for palette in custom_palettes
            if _palette_rule_matches(palette.asset_pattern, entry.name or "")
        ),
        None,
    )
    rule_index = _get_game_art_rule_index(art_rules)
    preferred_names = _preferred_palette_names(
        entry.name or "",
        art_rules,
        palette_theater=palette_theater,
        asset_type=entry.file_type or Path(entry.name or "").suffix.lstrip("."),
        resolved_rules=_rules_for_asset(
            entry.name or "",
            art_rules,
            rule_index=rule_index,
        ),
        resolved_linked_names=rule_index.linked_palettes.get(
            Path(entry.name or "").stem.casefold(),
            (),
        ),
    )
    group_order = {name: index for index, (name, _) in enumerate(PALETTE_GROUPS)}
    group_order["other"] = group_order["game"]
    ordered = sorted(
        unique.values(),
        key=lambda palette: (
            group_order.get(palette.group, 3),
            palette.name.casefold() if palette.group == "local" else "",
            palette.source.casefold() if palette.group == "local" else "",
            palette.colors if palette.group == "local" else (),
        ),
    )

    game_rule_palette = None
    for preferred_name in preferred_names:
        for source_group in ("local", "game", "other"):
            game_rule_palette = next(
                (
                    palette
                    for palette in ordered
                    if palette.group == source_group
                    and _palette_basename_matches(palette.name, preferred_name)
                ),
                None,
            )
            if game_rule_palette is not None:
                break
        if game_rule_palette is not None:
            break

    contextual_names = _contextual_palette_names(
        entry.name or "",
        selectable_palettes,
        shp_dimensions=(
            result.frames[0].width,
            result.frames[0].height,
            len(result.frames),
        )
        if result.is_shp and result.frames
        else None,
        archive_palette_names=_archive_context_palette_names(
            palette_context,
            entry.file_type or Path(entry.name or "").suffix.lstrip("."),
            palette_theater,
        ),
    )
    inferred_palette = None
    for source_group in ("local", "game", "other"):
        for contextual_name in contextual_names:
            inferred_palette = next(
                (
                    palette
                    for palette in ordered
                    if palette.group == source_group
                    and palette.name.casefold() == contextual_name.casefold()
                ),
                None,
            )
            if inferred_palette is not None:
                break
        if inferred_palette is not None:
            break

    stage_candidates = {
        "user_defined": matched_custom,
        "game_rules": game_rule_palette,
        "inference": inferred_palette,
        "fallback": gray,
    }
    default_palette = next(
        stage_candidates[stage.key]
        for stage in PALETTE_SELECTION_STAGES
        if stage_candidates[stage.key] is not None
    )
    default_palette_index = ordered.index(default_palette)
    if default_palette.group == "fallback":
        return replace(
            result,
            message=(
                QCoreApplication.translate(
                    "EntryPreviewPane",
                    "No matching palette could be identified; using grayscale. Choose a palette manually or set Palette Sources.",
                )
            ),
            palettes=tuple(ordered),
            default_palette_index=default_palette_index,
        )
    return replace(
        result,
        message=None,
        palettes=tuple(ordered),
        default_palette_index=default_palette_index,
    )


# @arch mix-browser.fallback-palette-classifier utility | en: Identifies SHP and VXL assets whose automatic palette resolves to grayscale | zh: 识别自动色盘最终回退为灰度色盘的 SHP 与 VXL 资源
class FallbackPaletteClassifier:
    def __init__(
        self,
        *,
        palette_directory: Path | None = None,
        palette_theater: str = "auto",
        xcc_names_enabled: bool = True,
        community_names_enabled: bool = False,
        palette_library: tuple[PaletteLibraryRule, ...] = (),
        cancellation_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        self._palette_directory = palette_directory
        self._palette_theater = palette_theater
        self._xcc_names_enabled = xcc_names_enabled
        self._community_names_enabled = community_names_enabled
        self._palette_library = palette_library
        self._custom_palettes = _load_palette_library(palette_library)
        self._cancellation_requested = cancellation_requested
        self._game_palette_catalog: tuple[
            tuple[PaletteOption, ...], dict[str, dict[str, str]]
        ] | None = None
        self._game_palette_names: set[str] = set()
        self._game_palette_exact_stems: set[str] = set()
        self._game_palette_prefix_stems: tuple[str, ...] = ()
        self._game_palette_fuzzy_stems: tuple[str, ...] = ()
        self._game_art_rules: dict[str, dict[str, str]] = {}
        self._art_rule_reference_index: dict[str, tuple[dict[str, str], ...]] = {}
        self._art_rule_variant_index: dict[
            tuple[str, str], tuple[tuple[str, dict[str, str]], ...]
        ] = {}
        self._linked_cameo_stems: set[str] = set()
        self._linked_sidebar_palettes: dict[str, tuple[str, ...]] = {}
        self._unit_cameo_palette = "cameo.pal"
        self._game_indexes_ready = False
        self._archive_palettes: dict[
            tuple[str, int, int], tuple[PaletteOption, ...]
        ] = {}
        self._directory_palettes: dict[str, tuple[PaletteOption, ...]] = {}
        self._decision_cache: dict[tuple[str, ...], bool | None] = {}
        self._similarity_cache: dict[str, bool] = {}
        self._compiled_custom_patterns = tuple(
            compiled
            for palette in self._custom_palettes
            if palette.asset_pattern.strip()
            for compiled in (_compile_palette_pattern(palette.asset_pattern),)
            if compiled is not None
        )

    def uses_fallback(
        self,
        entry: MixEntry,
        *,
        archive: MixArchiveIndex | None = None,
        path: Path | None = None,
        palette_context: tuple[str, ...] = (),
    ) -> bool | None:
        asset_type = self._asset_type(entry)
        if asset_type not in {"shp", "shp-ts", "vxl"}:
            return None
        self._check_cancelled()

        if archive is not None:
            archive_key = (
                str(archive.path).casefold(),
                archive.source_offset,
                archive.source_size,
            )
            palette_sources = self._archive_palettes.get(archive_key)
            if palette_sources is None:
                palette_sources = _load_archive_palettes(archive, entry)
                self._archive_palettes[archive_key] = palette_sources
            source_kind = "archive"
            source_id = f"{archive_key[0]}:{archive_key[1]}:{archive_key[2]}"
        elif path is not None:
            directory_key = str(path.parent).casefold()
            palette_sources = self._directory_palettes.get(directory_key)
            if palette_sources is None:
                palette_sources = _load_sibling_palettes(path)
                self._directory_palettes[directory_key] = palette_sources
            source_kind = "directory"
            source_id = directory_key
        else:
            palette_sources = ()
            source_kind = "none"
            source_id = ""

        entry_name = entry.name or ""
        decision_key = (
            source_kind,
            source_id,
            entry_name.casefold(),
            entry.file_type or "",
            *(part.casefold() for part in palette_context),
        )
        if decision_key in self._decision_cache:
            return self._decision_cache[decision_key]

        # Any local palette prevents grayscale fallback; no preview palette list is needed.
        if palette_sources:
            self._decision_cache[decision_key] = False
            return False

        try:
            basename = Path(entry_name).name
            if any(pattern.search(basename) for pattern in self._compiled_custom_patterns):
                result = False
            else:
                self._ensure_game_palette_indexes()
                rules = self._rules_for_asset(entry_name)
                preferred_names = _preferred_palette_names(
                    entry_name,
                    self._game_art_rules,
                    palette_theater=self._palette_theater,
                    asset_type=entry.file_type or Path(entry_name).suffix.lstrip("."),
                    resolved_rules=rules,
                    resolved_linked_names=self._linked_palette_names(
                        Path(entry_name).stem.casefold()
                    ),
                )
                if any(
                    Path(name).name.casefold() in self._game_palette_names
                    for name in preferred_names
                ):
                    result = False
                elif any(
                    name.casefold() in self._game_palette_names
                    for name in _archive_context_palette_names(
                        palette_context,
                        asset_type,
                        self._palette_theater,
                    )
                ):
                    result = False
                else:
                    asset_stem = Path(entry_name).stem.casefold()
                    if asset_stem in self._game_palette_exact_stems or any(
                        asset_stem.startswith(palette_stem)
                        for palette_stem in self._game_palette_prefix_stems
                    ):
                        result = False
                    elif self._similar_game_palette_exists(asset_stem):
                        result = False
                    elif (
                        "cameo.pal" in self._game_palette_names
                        and _is_standard_cameo_shp(entry, archive=archive, path=path)
                    ):
                        result = False
                    else:
                        result = True
            self._decision_cache[decision_key] = result
            return result
        except CancelledError:
            raise
        except Exception:
            return None

    def _ensure_game_palette_indexes(self) -> None:
        if self._game_palette_catalog is None:
            if self._palette_directory is None:
                self._game_palette_catalog = ((), {})
            else:
                self._game_palette_catalog = _load_game_palette_catalog(
                    self._palette_directory,
                    cancellation_event=self._cancellation_requested,
                    scan_cancellation_event=self._cancellation_requested,
                )
        if self._game_indexes_ready:
            return

        palettes, self._game_art_rules = self._game_palette_catalog
        contextual_palettes = [
            palette
            for palette in palettes
            if palette.group in {"game", "other"}
        ]
        self._game_palette_names = {
            Path(palette.name).name.casefold() for palette in contextual_palettes
        }
        self._game_palette_exact_stems = {
            Path(palette.name).stem.casefold() for palette in contextual_palettes
        }
        self._game_palette_prefix_stems = tuple(
            sorted(
                {
                    Path(palette.name).stem.casefold()
                    for palette in contextual_palettes
                    if len(Path(palette.name).stem)
                    >= _MIN_PALETTE_PREFIX_STEM_LENGTH
                }
            )
        )
        self._game_palette_fuzzy_stems = tuple(
            sorted(
                {
                    Path(palette.name).stem.casefold()
                    for palette in palettes
                    if palette.group == "game"
                }
            )
        )

        references: dict[str, list[dict[str, str]]] = {}
        variants: dict[tuple[str, str], list[tuple[str, dict[str, str]]]] = {}
        for section, section_rules in self._game_art_rules.items():
            self._check_cancelled()
            reference_stems = tuple(
                dict.fromkeys(
                    stem
                    for stem in _palette_resource_stems(section_rules)
                )
            )
            for reference_stem in reference_stems:
                references.setdefault(reference_stem, []).append(section_rules)
            if not (
                _is_enabled(section_rules.get("newtheater", ""))
                or section_rules.get("_asset_kind") == "animation"
                or section_rules.get("foundation")
            ):
                continue
            for candidate_stem in dict.fromkeys((section, *reference_stems)):
                for signature in _new_theater_variant_signatures(candidate_stem):
                    variants.setdefault(signature, []).append(
                        (candidate_stem, section_rules)
                    )
        self._art_rule_reference_index = {
            stem: tuple(rules) for stem, rules in references.items()
        }
        self._art_rule_variant_index = {
            signature: tuple(candidates)
            for signature, candidates in variants.items()
        }

        self._unit_cameo_palette = self._game_art_rules.get("unitart", {}).get(
            "cameopalette",
            "cameo.pal",
        )
        linked_cameo_stems: set[str] = set()
        linked_sidebar_palettes: dict[str, list[str]] = {}
        for section_rules in self._game_art_rules.values():
            self._check_cancelled()
            for field in ("cameo", "altcameo"):
                cameo_stem = _resource_stem(section_rules.get(field, ""))
                if cameo_stem:
                    linked_cameo_stems.add(cameo_stem)
            sidebar_stem = _resource_stem(section_rules.get("sidebarimage", ""))
            if sidebar_stem:
                linked_sidebar_palettes.setdefault(sidebar_stem, []).append(
                    section_rules.get("sidebarpalette", "cameo.pal")
                )
        self._linked_cameo_stems = linked_cameo_stems
        self._linked_sidebar_palettes = {
            stem: tuple(palettes)
            for stem, palettes in linked_sidebar_palettes.items()
        }
        self._game_indexes_ready = True

    def _rules_for_asset(self, entry_name: str) -> dict[str, str]:
        stem = Path(entry_name).stem.casefold()
        rules = dict(self._game_art_rules.get(stem, {}))
        image_rules = list(self._art_rule_reference_index.get(stem, ()))
        for signature in _new_theater_variant_signatures(stem):
            image_rules.extend(
                section_rules
                for candidate_stem, section_rules in self._art_rule_variant_index.get(
                    signature,
                    (),
                )
                if _new_theater_variant_matches(candidate_stem, stem)
            )

        unique_image_rules = []
        seen_rules: set[int] = set()
        for section_rules in image_rules:
            identity = id(section_rules)
            if identity not in seen_rules:
                seen_rules.add(identity)
                unique_image_rules.append(section_rules)
        fields = {field for section_rules in unique_image_rules for field in section_rules}
        for field in fields - rules.keys():
            values = {
                section_rules[field]
                for section_rules in unique_image_rules
                if field in section_rules
            }
            if len(values) == 1:
                rules[field] = next(iter(values))
        return rules

    def _linked_palette_names(self, entry_stem: str) -> tuple[str, ...]:
        linked: list[str] = []
        if entry_stem in self._linked_cameo_stems:
            linked.extend(_palette_value_names(self._unit_cameo_palette, "tem"))
        for sidebar_palette in self._linked_sidebar_palettes.get(entry_stem, ()):
            linked.extend(_palette_value_names(sidebar_palette, "tem"))
        return tuple(dict.fromkeys(linked))

    def _similar_game_palette_exists(self, asset_stem: str) -> bool:
        cache = self._similarity_cache
        if asset_stem in cache:
            return cache[asset_stem]
        for palette_stem in self._game_palette_fuzzy_stems:
            self._check_cancelled()
            if SequenceMatcher(
                None,
                asset_stem,
                palette_stem,
                autojunk=False,
            ).ratio() > _MIN_PALETTE_NAME_SIMILARITY:
                cache[asset_stem] = True
                return True
        cache[asset_stem] = False
        return False

    @staticmethod
    def _asset_type(entry: MixEntry) -> str:
        suffix_type = Path(entry.name or "").suffix.casefold().lstrip(".")
        if suffix_type in {"shp", "vxl"}:
            return suffix_type
        return (entry.file_type or "").casefold()

    def _check_cancelled(self) -> None:
        if self._cancellation_requested():
            raise CancelledError()


def _palette_rule_matches(pattern: str, entry_name: str) -> bool:
    if not pattern.strip():
        return False
    try:
        return re.search(pattern, Path(entry_name).name, re.IGNORECASE) is not None
    except re.error:
        return False


def _compile_palette_pattern(pattern: str) -> re.Pattern[str] | None:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def _palette_basename_matches(palette_name: str, expected_name: str) -> bool:
    return Path(palette_name).name.casefold() == Path(expected_name).name.casefold()


def _check_palette_cancellation(
    cancellation_event: _PaletteCancellationSignal,
) -> None:
    if cancellation_event is None:
        return
    is_cancelled = (
        cancellation_event()
        if callable(cancellation_event)
        else cancellation_event.is_set()
    )
    if is_cancelled:
        raise CancelledError()


def _normalized_palette_directory(directory: Path) -> Path:
    try:
        return directory.expanduser().absolute()
    except OSError:
        return directory.expanduser()


# @arch mix-browser.palette-directory-cache-key utility | en: Normalizes a configured directory path for palette index lookup | zh: 规范化配置目录路径以查询色盘索引
def game_palette_catalog_directory_key(directory: Path) -> str:
    return os.path.normcase(str(_normalized_palette_directory(directory)))


def _palette_catalog_cache_path(directory_key: str) -> Path:
    digest = hashlib.sha256(directory_key.encode("utf-8")).hexdigest()
    return application_directory() / "palette-catalog" / f"{digest}.json"


def _read_persisted_palette_catalog(
    directory_key: str,
) -> tuple[tuple[PaletteOption, ...], dict[str, dict[str, str]]] | None:
    cache_path = _palette_catalog_cache_path(directory_key)
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("version") != _GAME_PALETTE_DISK_CACHE_VERSION
            or payload.get("directory") != directory_key
        ):
            return None
        raw_palettes = payload["palettes"]
        raw_rules = payload["art_rules"]
        if not isinstance(raw_palettes, list) or not isinstance(raw_rules, dict):
            return None
        palettes = []
        for item in raw_palettes:
            colors = tuple(
                tuple(int(channel) for channel in color)
                for color in item["colors"]
            )
            if any(
                len(color) != 3 or any(not 0 <= channel <= 255 for channel in color)
                for color in colors
            ):
                return None
            color_count = int(item["color_count"])
            if not 0 <= color_count <= 256 or len(colors) > 256:
                return None
            palettes.append(
                PaletteOption(
                    str(item["name"]),
                    colors,
                    color_count,
                    str(item.get("source", "")),
                    str(item.get("group", "other")),
                    str(item.get("asset_pattern", "")),
                )
            )
        rules = {
            str(section): {
                str(field): str(value)
                for field, value in fields.items()
            }
            for section, fields in raw_rules.items()
            if isinstance(fields, dict)
        }
        return tuple(palettes), rules
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_persisted_palette_catalog(
    directory_key: str,
    catalog: tuple[tuple[PaletteOption, ...], dict[str, dict[str, str]]],
) -> None:
    cache_path = _palette_catalog_cache_path(directory_key)
    palettes, art_rules = catalog
    payload = {
        "version": _GAME_PALETTE_DISK_CACHE_VERSION,
        "directory": directory_key,
        "palettes": [
            {
                "name": palette.name,
                "colors": palette.colors,
                "color_count": palette.color_count,
                "source": palette.source,
                "group": palette.group,
                "asset_pattern": palette.asset_pattern,
            }
            for palette in palettes
        ],
        "art_rules": art_rules,
    }
    temporary_path: Path | None = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=f"{cache_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(payload, temporary_file, separators=(",", ":"))
        os.replace(temporary_path, cache_path)
    except (OSError, TypeError, ValueError):
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def game_palette_catalog_is_ready_or_loading(directory: Path) -> bool:
    directory_key = game_palette_catalog_directory_key(directory)
    with _GAME_PALETTE_CACHE_LOCK:
        generation = _GAME_PALETTE_GENERATIONS.get(directory_key, 0)
        cache_key = (directory_key, generation)
        return (
            cache_key in _GAME_PALETTE_CACHE
            or cache_key in _GAME_PALETTE_INFLIGHT
            or directory_key in _GAME_PALETTE_SCHEDULED
        )


def mark_game_palette_catalog_scheduled(directory: Path) -> None:
    directory_key = game_palette_catalog_directory_key(directory)
    with _GAME_PALETTE_CACHE_LOCK:
        generation = _GAME_PALETTE_GENERATIONS.get(directory_key, 0)
        cache_key = (directory_key, generation)
        if (
            cache_key not in _GAME_PALETTE_CACHE
            and cache_key not in _GAME_PALETTE_INFLIGHT
        ):
            _GAME_PALETTE_SCHEDULED.add(directory_key)


def clear_game_palette_catalog_scheduled(directory: Path) -> None:
    directory_key = game_palette_catalog_directory_key(directory)
    with _GAME_PALETTE_CACHE_LOCK:
        _GAME_PALETTE_SCHEDULED.discard(directory_key)


def invalidate_game_palette_catalog(directory: Path) -> None:
    directory_key = game_palette_catalog_directory_key(directory)
    with _GAME_PALETTE_CACHE_LOCK:
        _GAME_PALETTE_GENERATIONS[directory_key] = (
            _GAME_PALETTE_GENERATIONS.get(directory_key, 0) + 1
        )
        for cache_key in tuple(_GAME_PALETTE_CACHE):
            if cache_key[0] == directory_key:
                del _GAME_PALETTE_CACHE[cache_key]


# @arch mix-browser.game-palette-catalog service | en: Reads palettes and art rules from the configured game directory | zh: 从配置的游戏目录读取色盘与美术规则
def _load_game_palette_catalog(
    directory: Path,
    *,
    cancellation_event: _PaletteCancellationSignal = None,
    scan_cancellation_event: _PaletteCancellationSignal = None,
    scan_started: Callable[[], None] | None = None,
    use_persisted_cache: bool = True,
) -> tuple[tuple[PaletteOption, ...], dict[str, dict[str, str]]]:
    _check_palette_cancellation(cancellation_event)
    normalized_directory = _normalized_palette_directory(directory)
    directory_key = game_palette_catalog_directory_key(directory)
    with _GAME_PALETTE_CACHE_LOCK:
        _check_palette_cancellation(cancellation_event)
        generation = _GAME_PALETTE_GENERATIONS.get(directory_key, 0)
        cache_key = (directory_key, generation)
        cached = _GAME_PALETTE_CACHE.get(cache_key)
        if cached is not None:
            _get_game_art_rule_index(cached[1])
            return cached
        pending = _GAME_PALETTE_INFLIGHT.get(cache_key)
        owns_scan = pending is None
        if pending is None:
            pending = Future()
            _GAME_PALETTE_INFLIGHT[cache_key] = pending

    if owns_scan:
        try:
            result = (
                _read_persisted_palette_catalog(directory_key)
                if use_persisted_cache
                else None
            )
            if result is None:
                # Palette discovery stays independent of the UI's name-source filters.
                if normalized_directory.is_dir():
                    if scan_started is not None:
                        scan_started()
                    result = _build_game_palette_catalog(
                        normalized_directory,
                        xcc_names_enabled=True,
                        community_names_enabled=True,
                        cancellation_event=scan_cancellation_event,
                    )
                else:
                    result = (), {}
            _check_palette_cancellation(scan_cancellation_event)
            _get_game_art_rule_index(result[1])
        except BaseException as exc:
            with _GAME_PALETTE_CACHE_LOCK:
                _GAME_PALETTE_INFLIGHT.pop(cache_key, None)
                pending.set_exception(exc)
            raise
        with _GAME_PALETTE_CACHE_LOCK:
            _GAME_PALETTE_INFLIGHT.pop(cache_key, None)
            if _GAME_PALETTE_GENERATIONS.get(directory_key, 0) == generation:
                _GAME_PALETTE_CACHE[cache_key] = result
                _write_persisted_palette_catalog(directory_key, result)
            pending.set_result(result)
        _check_palette_cancellation(cancellation_event)
        return result

    while True:
        _check_palette_cancellation(cancellation_event)
        try:
            return pending.result(timeout=0.1)
        except FutureTimeoutError:
            continue


# @arch mix-browser.game-palette-catalog-snapshot service | en: Loads or scans the reusable game palette snapshot | zh: 读取或扫描可复用的游戏色盘快照
def load_game_palette_catalog_snapshot(
    directory: Path,
    *,
    cancellation_event: Event | None = None,
    scan_started: Callable[[], None] | None = None,
) -> tuple[tuple[PaletteOption, ...], dict[str, dict[str, str]]]:
    try:
        return _load_game_palette_catalog(
            directory,
            cancellation_event=cancellation_event,
            scan_cancellation_event=cancellation_event,
            scan_started=scan_started,
        )
    finally:
        clear_game_palette_catalog_scheduled(directory)


# @arch mix-browser.refresh-game-palette-catalog service | en: Rebuilds and caches palette data for a game directory | zh: 重建并缓存游戏目录的色盘数据
def refresh_game_palette_catalog(
    directory: Path,
    *,
    cancellation_event: Event | None = None,
) -> tuple[tuple[PaletteOption, ...], dict[str, dict[str, str]]]:
    invalidate_game_palette_catalog(directory)
    return _load_game_palette_catalog(
        directory,
        cancellation_event=cancellation_event,
        scan_cancellation_event=cancellation_event,
        use_persisted_cache=False,
    )


def _build_game_palette_catalog(
    directory: Path,
    *,
    xcc_names_enabled: bool,
    community_names_enabled: bool,
    cancellation_event: _PaletteCancellationSignal = None,
) -> tuple[tuple[PaletteOption, ...], dict[str, dict[str, str]]]:
    palettes: list[PaletteOption] = []
    rule_configs: list[tuple[str, bytes]] = []
    seen_archives: set[tuple[str, int, int]] = set()
    pending = []

    for path in sorted(directory.glob("*.pal"), key=lambda item: item.name.casefold()):
        _check_palette_cancellation(cancellation_event)
        try:
            if path.stat().st_size > 64 * 1024:
                continue
            colors = decode_westwood_palette(path.read_bytes())
        except (OSError, UnicodeError, ValueError, struct.error):
            continue
        palettes.append(
            PaletteOption(
                path.name,
                _pad_colors(colors),
                len(colors),
                QT_TRANSLATE_NOOP("EntryPreviewPane", "Game folder"),
                "game",
            )
        )

    loader = MixArchiveLoader(
        xcc_names_enabled=xcc_names_enabled,
        community_names_enabled=community_names_enabled,
    )
    session = loader.create_session()
    root_archives = sorted(
        directory.glob("*.mix"),
        key=lambda item: (_game_mix_priority(item), item.name.casefold()),
    )
    for path in reversed(root_archives):
        _check_palette_cancellation(cancellation_event)
        try:
            pending.append((session.load(path), path.name, 0))
        except (OSError, ValueError):
            continue

    scanned_archives = 0
    while pending and scanned_archives < _MAX_GAME_PALETTE_ARCHIVES:
        _check_palette_cancellation(cancellation_event)
        archive, source_label, depth = pending.pop()
        archive_key = (
            str(archive.path).casefold(),
            archive.source_offset,
            archive.source_size,
        )
        if archive_key in seen_archives or depth > 8:
            continue
        seen_archives.add(archive_key)
        scanned_archives += 1

        for entry in archive.entries:
            _check_palette_cancellation(cancellation_event)
            name = entry.name or ""
            normalized_name = Path(name).name.casefold()
            if (
                normalized_name in _GAME_RULE_CONFIG_NAMES
                and len(rule_configs) < _MAX_GAME_RULE_CONFIGS
            ):
                data = read_mix_entry_bytes(
                    archive,
                    entry,
                    max_bytes=_MAX_GAME_RULE_CONFIG_BYTES,
                )
                if data is not None:
                    rule_configs.append((normalized_name, data))

            is_palette = (
                Path(name).suffix.casefold() == ".pal"
                or (entry.file_type or "").casefold() == "pal"
            )
            if is_palette:
                data = read_mix_entry_bytes(archive, entry, max_bytes=64 * 1024)
                if data is not None:
                    try:
                        colors = decode_westwood_palette(data)
                    except (UnicodeError, ValueError, struct.error):
                        pass
                    else:
                        palette_name = name or f"Unknown palette (0x{entry.file_id:08X})"
                        if len(palettes) < _MAX_GAME_PALETTES:
                            palettes.append(
                                PaletteOption(
                                    palette_name,
                                    _pad_colors(colors),
                                    len(colors),
                                    QT_TRANSLATE_NOOP("EntryPreviewPane", "Game: {0}").format(source_label),
                                    "game",
                                )
                            )

            is_mix = (
                Path(name).suffix.casefold() == ".mix"
                or (entry.file_type or "").casefold() == "mix"
            )
            if is_mix and depth < 8:
                try:
                    nested = session.load_nested(archive, entry)
                except (OSError, ValueError):
                    continue
                nested_name = name or f"0x{entry.file_id:08X}"
                pending.append((nested, f"{source_label}!{nested_name}", depth + 1))

    unique: dict[tuple[str, tuple[tuple[int, int, int], ...]], PaletteOption] = {}
    for palette in palettes:
        unique.setdefault((palette.name.casefold(), palette.colors), palette)
    return tuple(unique.values()), _read_game_art_palette_rules(directory, rule_configs)


def _read_game_art_palette_rules(
    directory: Path,
    archive_configs: list[tuple[str, bytes]],
) -> dict[str, dict[str, str]]:
    fields = (
        "palette",
        "custompalette",
        *_PALETTE_RESOURCE_REFERENCE_FIELDS,
        "newtheater",
        "terrainpalette",
        "altpalette",
        "animpalette",
        "cameo",
        "altcameo",
        "cameopalette",
        "sidebarimage",
        "sidebarpalette",
        "firerspalette",
        "foundation",
        "sequence",
        "rotates",
        "rotcount",
        "turretoffset",
        "barrellength",
        "voxel",
        "layer",
        "rate",
        "loopstart",
        "loopend",
        "loopcount",
        "start",
        "end",
    )
    rules: dict[str, dict[str, str]] = {}
    projectile_names: set[str] = set()
    particle_names: set[str] = set()
    particle_system_names: set[str] = set()

    def mark_resource_kind(value: str, kind: str) -> None:
        for stem in _palette_resource_stems(
            {"image": value}
        ):
            resource_rules = rules.setdefault(stem, {})
            previous = resource_rules.get("_asset_kind")
            if previous is None:
                resource_rules["_asset_kind"] = kind
            elif previous != kind:
                resource_rules["_asset_kind"] = "ambiguous"

    def merge_config(data: bytes) -> None:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")

        parser = configparser.ConfigParser(
            interpolation=None,
            strict=False,
            allow_no_value=True,
            delimiters=("=",),
            comment_prefixes=(";", "#", "//"),
            inline_comment_prefixes=(";",),
        )
        parser.optionxform = str.casefold
        try:
            parser.read_string(text)
        except configparser.Error:
            return

        for section in parser.sections():
            section_rules = rules.setdefault(section.casefold(), {})
            for field in fields:
                value = (parser.get(section, field, fallback="") or "").strip()
                if value:
                    section_rules[field] = value

            for field, value in parser.items(section):
                if not value:
                    continue
                if field == "projectile":
                    projectile_names.update(_palette_resource_stems({"image": value}))
                elif field in _ANIMATION_REFERENCE_FIELDS:
                    mark_resource_kind(value, "animation")

            if section.casefold() in {"overlaytypes", "terraintypes"}:
                for _, value in parser.items(section):
                    if value:
                        mark_resource_kind(value, "terrain")
            elif section.casefold() == "particles":
                particle_names.update(
                    stem
                    for _, value in parser.items(section)
                    if value
                    for stem in _palette_resource_stems({"image": value})
                )
            elif section.casefold() == "particlesystems":
                particle_system_names.update(
                    stem
                    for _, value in parser.items(section)
                    if value
                    for stem in _palette_resource_stems({"image": value})
                )
            elif section.casefold() == "voxelanims":
                for _, value in parser.items(section):
                    if value:
                        mark_resource_kind(value, "unit")

            if section.casefold() == "animations":
                for _, value in parser.items(section):
                    if not value:
                        continue
                    resource_name = value.split(";", 1)[0].split(",", 1)[0]
                    resource_stem = Path(resource_name.strip()).stem.casefold()
                    if resource_stem:
                        mark_resource_kind(resource_stem, "animation")
                in_animation_section = False
                for line in text.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith((";", "#", "//")):
                        continue
                    if stripped.startswith("[") and "]" in stripped:
                        in_animation_section = (
                            stripped[1 : stripped.index("]")].strip().casefold()
                            == "animations"
                        )
                        continue
                    if not in_animation_section or "=" not in line:
                        continue
                    value = line.split("=", 1)[1].strip()
                    parts = value.split(";")
                    if (
                        len(parts) < 2
                        or not parts[0].strip().casefold().startswith("old_")
                    ):
                        continue
                    alias_stem = Path(parts[1].strip()).stem.casefold()
                    if alias_stem:
                        mark_resource_kind(alias_stem, "animation")

    configs_by_name: dict[str, list[bytes]] = {}
    for filename, data in archive_configs:
        configs_by_name.setdefault(filename, []).append(data)

    for filename in _GAME_RULE_CONFIG_NAMES:
        for data in configs_by_name.get(filename, ()):
            merge_config(data)
        path = directory / filename
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        merge_config(data)
    for projectile_name in projectile_names:
        projectile_rules = rules.get(projectile_name, {})
        image = projectile_rules.get("image", "")
        if not image:
            continue
        projectile_kind = (
            "unit" if _is_enabled(projectile_rules.get("firerspalette", "")) else "projectile"
        )
        mark_resource_kind(image, projectile_kind)
    for particle_name in particle_names | particle_system_names:
        particle_rules = rules.get(particle_name, {})
        image = particle_rules.get("image", "")
        if image:
            mark_resource_kind(image, "animation")
    for resource_stem, resource_rules in tuple(rules.items()):
        if resource_rules.get("_asset_kind") != "animation":
            continue
        # RA2/YR S and Y animation variants retain the base animation palette category.
        for faction_suffix in ("s", "y"):
            rules.setdefault(f"{resource_stem}{faction_suffix}", {"_asset_kind": "animation"})
    return rules


def _game_mix_priority(path: Path) -> int:
    name = path.name.casefold()
    if name in {"ra2.mix", "ra2md.mix", "expandmd01.mix"}:
        return 0
    if name.startswith(("movie", "movmd", "theme", "lang")):
        return 2
    return 1


def _preferred_palette_names(
    entry_name: str,
    art_rules: dict[str, dict[str, str]],
    *,
    palette_theater: str = "auto",
    asset_type: str = "",
    resolved_rules: dict[str, str] | None = None,
    resolved_linked_names: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    rules = (
        resolved_rules
        if resolved_rules is not None
        else _rules_for_asset(entry_name, art_rules)
    )
    theater = _theater_code(entry_name, palette_theater)
    stem = Path(entry_name).stem.casefold()
    if (
        _is_enabled(rules.get("newtheater", ""))
        or _is_building_buildup_shp(entry_name, asset_type)
    ) and len(stem) > 1:
        theater_letter = stem[1]
        if theater_letter not in _NEW_THEATER_PLACEHOLDER_LETTERS:
            theater = _THEATER_LETTER_TO_CODE.get(theater_letter, theater)
    custom_palette = rules.get("custompalette", "").strip().strip("\"'")
    if custom_palette.casefold() not in {"none", "default"}:
        custom_names = _custom_palette_names(custom_palette, theater)
        if custom_names:
            return custom_names

    configured_palette = rules.get("palette", "").strip().strip("\"'")
    if configured_palette.casefold() in {"none", "default"}:
        configured_palette = ""
    if configured_palette:
        return _palette_value_names(configured_palette, theater, expand_theater=True)
    elif _is_enabled(rules.get("altpalette", "")):
        return (_THEATER_SUFFIXES[theater][0],)
    elif _is_enabled(rules.get("newtheater", "")):
        return (_THEATER_SUFFIXES[theater][0],)
    elif _is_enabled(rules.get("animpalette", "")):
        return ("anim.pal",)
    elif _is_enabled(rules.get("terrainpalette", "")):
        return (_THEATER_SUFFIXES[theater][1],)
    elif "animpalette" in rules:
        return (_THEATER_SUFFIXES[theater][0],)

    linked_names = (
        resolved_linked_names
        if resolved_linked_names is not None
        else _linked_palette_names(entry_name, art_rules)
    )
    if linked_names:
        return linked_names

    if stem.endswith(("uico", "icon")):
        unit_art = art_rules.get("unitart", {})
        cameo_names = _palette_value_names(
            unit_art.get("cameopalette", "cameo.pal"),
            "tem",
        )
        if cameo_names:
            return cameo_names

    normalized_asset_type = (asset_type or Path(entry_name).suffix.lstrip(".")).casefold()
    if normalized_asset_type in {"shp", "shp-ts"}:
        if stem == "arrow":
            return ("mousepal.pal",)
        if re.fullmatch(r"ebtn-(?:dn|up)", stem):
            return ("sdbtnanm.pal",)
        if stem in {"pipbrd", "pips", "pips2"} or re.fullmatch(
            r"progbar(?:\d+|m)?",
            stem,
        ):
            return ("sidebar.pal",)
    asset_kind = _infer_asset_palette_kind(entry_name, rules, asset_type)
    if asset_kind == "animation":
        return ("anim.pal",)
    if asset_kind == "building":
        return (_THEATER_SUFFIXES[theater][2],)
    if asset_kind == "terrain":
        return (_THEATER_SUFFIXES[theater][1],)
    if asset_kind == "unit":
        return (_THEATER_SUFFIXES[theater][0],)

    return ()


def _rules_for_asset(
    entry_name: str,
    art_rules: dict[str, dict[str, str]],
    *,
    rule_index: _GameArtRuleIndex | None = None,
) -> dict[str, str]:
    stem = Path(entry_name).stem.casefold()
    rules = dict(art_rules.get(stem, {}))
    index = rule_index or _get_game_art_rule_index(art_rules)
    resource_rules = list(index.references.get(stem, ()))
    for signature in _new_theater_variant_signatures(stem):
        resource_rules.extend(
            section_rules
            for candidate_stem, section_rules in index.variants.get(signature, ())
            if _new_theater_variant_matches(candidate_stem, stem)
        )

    unique_rules = []
    seen_rules: set[int] = set()
    for section_rules in resource_rules:
        if id(section_rules) not in seen_rules:
            seen_rules.add(id(section_rules))
            unique_rules.append(section_rules)
    fields = {field for section_rules in unique_rules for field in section_rules}
    for field in fields - rules.keys():
        values = {
            section_rules[field]
            for section_rules in unique_rules
            if field in section_rules
        }
        if len(values) == 1:
            rules[field] = next(iter(values))
    return rules


def _get_game_art_rule_index(
    art_rules: dict[str, dict[str, str]],
) -> _GameArtRuleIndex:
    cache_key = id(art_rules)
    with _GAME_PALETTE_CACHE_LOCK:
        cached = _GAME_ART_RULE_INDEX_CACHE.get(cache_key)
        if cached is not None and cached[0] is art_rules:
            return cached[1]

        references: dict[str, list[dict[str, str]]] = {}
        variants: dict[tuple[str, str], list[tuple[str, dict[str, str]]]] = {}
        linked_palettes: dict[str, list[str]] = {}
        unit_palette = art_rules.get("unitart", {}).get("cameopalette", "cameo.pal")
        for section, section_rules in art_rules.items():
            reference_stems = _palette_resource_stems(section_rules)
            for reference_stem in reference_stems:
                references.setdefault(reference_stem, []).append(section_rules)

            if (
                _is_enabled(section_rules.get("newtheater", ""))
                or section_rules.get("_asset_kind") == "animation"
                or section_rules.get("foundation")
            ):
                for candidate_stem in dict.fromkeys((section, *reference_stems)):
                    for signature in _new_theater_variant_signatures(candidate_stem):
                        variants.setdefault(signature, []).append(
                            (candidate_stem, section_rules)
                        )

            for field in ("cameo", "altcameo"):
                for candidate in section_rules.get(field, "").split(","):
                    linked_stem = _resource_stem(candidate)
                    if linked_stem:
                        linked_palettes.setdefault(linked_stem, []).extend(
                            _palette_value_names(unit_palette, "tem")
                        )
            sidebar_stem = _resource_stem(section_rules.get("sidebarimage", ""))
            if sidebar_stem:
                linked_palettes.setdefault(sidebar_stem, []).extend(
                    _palette_value_names(
                        section_rules.get("sidebarpalette", "cameo.pal"),
                        "tem",
                    )
                )

        index = _GameArtRuleIndex(
            references={key: tuple(value) for key, value in references.items()},
            variants={key: tuple(value) for key, value in variants.items()},
            linked_palettes={
                key: tuple(dict.fromkeys(value))
                for key, value in linked_palettes.items()
            },
        )
        _GAME_ART_RULE_INDEX_CACHE[cache_key] = (art_rules, index)
        while len(_GAME_ART_RULE_INDEX_CACHE) > _MAX_GAME_ART_RULE_INDEX_CACHE:
            del _GAME_ART_RULE_INDEX_CACHE[next(iter(_GAME_ART_RULE_INDEX_CACHE))]
        return index


def _contextual_palette_names(
    entry_name: str,
    palettes: list[PaletteOption],
    *,
    archive_palette_names: tuple[str, ...] = (),
    shp_dimensions: tuple[int, int, int] | None = None,
) -> tuple[str, ...]:
    asset_stem = Path(entry_name).stem.casefold()
    local_palettes = [palette for palette in palettes if palette.group == "local"]
    game_palettes = [
        palette for palette in palettes if palette.group in {"game", "other"}
    ]

    for candidate_group in (local_palettes, game_palettes):
        exact_matches = tuple(
            dict.fromkeys(
                palette.name
                for palette in candidate_group
                if Path(palette.name).stem.casefold() == asset_stem
            )
        )
        if exact_matches:
            return exact_matches

    for archive_palette_name in archive_palette_names:
        archive_matches = tuple(
            dict.fromkeys(
                palette.name
                for candidate_group in (local_palettes, game_palettes)
                for palette in candidate_group
                if _palette_basename_matches(palette.name, archive_palette_name)
            )
        )
        if archive_matches:
            return archive_matches

    if shp_dimensions == (60, 48, 1):
        cameo_matches = tuple(
            dict.fromkeys(
                palette.name
                for candidate_group in (local_palettes, game_palettes)
                for palette in candidate_group
                if _palette_basename_matches(palette.name, "cameo.pal")
            )
        )
        if cameo_matches:
            return cameo_matches

    prefix_matches: dict[int, list[PaletteOption]] = {}
    for palette in local_palettes:
        palette_stem = Path(palette.name).stem.casefold()
        if (
            len(palette_stem) >= _MIN_PALETTE_PREFIX_STEM_LENGTH
            and asset_stem.startswith(palette_stem)
        ):
            prefix_matches.setdefault(len(palette_stem), []).append(palette)
    if prefix_matches:
        longest = max(prefix_matches)
        return tuple(
            dict.fromkeys(palette.name for palette in prefix_matches[longest])
        )

    prefix_matches = {}
    for palette in game_palettes:
        palette_stem = Path(palette.name).stem.casefold()
        if (
            len(palette_stem) >= _MIN_PALETTE_PREFIX_STEM_LENGTH
            and asset_stem.startswith(palette_stem)
        ):
            prefix_matches.setdefault(len(palette_stem), []).append(palette)
    if prefix_matches:
        longest = max(prefix_matches)
        return tuple(
            dict.fromkeys(palette.name for palette in prefix_matches[longest])
        )

    similar_local_palette = _best_similar_palette(asset_stem, local_palettes)
    if similar_local_palette is not None:
        return (similar_local_palette.name,)

    game_directory_palettes = [
        palette for palette in palettes if palette.group == "game"
    ]
    similar_game_palette = _best_similar_palette(
        asset_stem,
        game_directory_palettes,
    )
    if similar_game_palette is not None:
        return (similar_game_palette.name,)

    if local_palettes:
        selected_local = min(
            local_palettes,
            key=lambda palette: (
                palette.name.casefold(),
                palette.source.casefold(),
                palette.colors,
            ),
        )
        return (selected_local.name,)
    return ()


def _best_similar_palette(
    asset_stem: str,
    palettes: list[PaletteOption],
) -> PaletteOption | None:
    scored_palettes = [
        (
            SequenceMatcher(
                None,
                asset_stem,
                Path(palette.name).stem.casefold(),
                autojunk=False,
            ).ratio(),
            palette,
        )
        for palette in palettes
    ]
    if not scored_palettes:
        return None

    best_similarity = max(score for score, _ in scored_palettes)
    if best_similarity <= _MIN_PALETTE_NAME_SIMILARITY:
        return None

    return min(
        (
            palette
            for score, palette in scored_palettes
            if score == best_similarity
        ),
        key=lambda palette: (
            palette.name.casefold(),
            palette.source.casefold(),
            palette.colors,
        ),
    )


def _custom_palette_names(value: str, theater: str) -> tuple[str, ...]:
    normalized = value.strip().strip("\"'")
    if normalized.casefold() in {"", "none", "default"}:
        return ()
    if "~~~" in normalized:
        normalized = normalized.replace("~~~", theater)
    elif Path(normalized).suffix.casefold() != ".pal":
        normalized = f"{normalized}.pal"
    return (normalized.casefold(),)


def _palette_value_names(
    value: str,
    theater: str,
    *,
    expand_theater: bool = False,
) -> tuple[str, ...]:
    normalized = value.strip().strip("\"'")
    if normalized.casefold() in {"", "none", "default"}:
        return ()
    if Path(normalized).suffix.casefold() == ".pal":
        return (normalized.casefold(),)
    values = (
        [f"{normalized}{theater}.pal", f"{normalized}.pal"]
        if expand_theater
        else [f"{normalized}.pal"]
    )
    return tuple(value.casefold() for value in values)


def _linked_palette_names(
    entry_name: str,
    art_rules: dict[str, dict[str, str]],
) -> tuple[str, ...]:
    return _get_game_art_rule_index(art_rules).linked_palettes.get(
        Path(entry_name).stem.casefold(),
        (),
    )


def _references_resource(value: str, entry_stem: str) -> bool:
    return any(
        _resource_stem(candidate) == entry_stem
        for candidate in value.split(",")
    )


def _resource_stem(value: str) -> str:
    candidate = value.split(";", 1)[0].split(",", 1)[0]
    return Path(candidate.strip().strip("\"'")).stem.casefold()


def _palette_resource_stems(section_rules: dict[str, str]) -> tuple[str, ...]:
    stems = []
    for field in _PALETTE_RESOURCE_REFERENCE_FIELDS:
        for value in section_rules.get(field, "").split(","):
            stem = _resource_stem(value)
            if stem and stem not in {"default", "false", "none", "true", "yes"}:
                stems.append(stem)
    return tuple(dict.fromkeys(stems))


def _new_theater_variant_matches(value: str, entry_stem: str) -> bool:
    for value_part in value.split(","):
        candidate_stem = _resource_stem(value_part)
        candidate_stems = _new_theater_comparison_stems(candidate_stem)
        entry_stems = _new_theater_comparison_stems(entry_stem)

        for candidate_variant_stem in candidate_stems:
            for entry_variant_stem in entry_stems:
                if (
                    len(candidate_variant_stem) != len(entry_variant_stem)
                    or len(candidate_variant_stem) < 3
                ):
                    continue
                candidate_variant = candidate_variant_stem[1]
                entry_variant = entry_variant_stem[1]
                if (
                    candidate_variant_stem[0] == entry_variant_stem[0]
                    and candidate_variant != entry_variant
                    and (
                        candidate_variant in _THEATER_LETTER_TO_CODE
                        or candidate_variant in _NEW_THEATER_PLACEHOLDER_LETTERS
                    )
                    and (
                        entry_variant in _THEATER_LETTER_TO_CODE
                        or entry_variant in _NEW_THEATER_PLACEHOLDER_LETTERS
                    )
                    and candidate_variant_stem[2:] == entry_variant_stem[2:]
                ):
                    return True
    return False


def _new_theater_comparison_stems(stem: str) -> tuple[str, ...]:
    normalized = stem.replace("_", "")
    stems = [normalized]
    # Building buildup and damaged assets conventionally append MK and DM.
    for suffix in ("mk", "dm"):
        if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 3:
            stems.append(normalized[: -len(suffix)])
    return tuple(dict.fromkeys(stems))


def _new_theater_variant_signatures(stem: str) -> tuple[tuple[str, str], ...]:
    stems = _new_theater_comparison_stems(stem)
    return tuple(
        dict.fromkeys(
            (candidate[0], candidate[2:])
            for candidate in stems
            if len(candidate) >= 3
        )
    )


def _infer_asset_palette_kind(
    entry_name: str,
    rules: dict[str, str],
    asset_type: str,
) -> str | None:
    stem = Path(entry_name).stem.casefold()
    if _is_enabled(rules.get("firerspalette", "")):
        return "unit"
    if _is_enabled(rules.get("newtheater", "")):
        return "unit"
    if _is_building_buildup_shp(entry_name, asset_type):
        return "unit"
    if stem.endswith("wall"):
        return "unit"
    configured_kind = rules.get("_asset_kind")
    if configured_kind == "animation":
        return "animation"
    if configured_kind == "terrain":
        return "terrain"
    if configured_kind in {"unit", "projectile"}:
        return "unit"
    if any(
        rules.get(field)
        for field in (
            "layer",
            "rate",
            "loopstart",
            "loopend",
            "loopcount",
            "start",
            "end",
        )
    ):
        return "animation"
    if rules.get("foundation"):
        return "building"
    if rules.get("cameo") or rules.get("altcameo"):
        return "unit"
    if any(
        rules.get(field)
        for field in ("sequence", "rotates", "rotcount", "turretoffset", "barrellength")
    ) or _is_enabled(rules.get("voxel", "")):
        return "unit"
    if asset_type.casefold() == "vxl":
        return "unit"
    if Path(entry_name).suffix.casefold().lstrip(".") in _THEATER_SUFFIXES:
        return "terrain"
    if "smk" in stem or stem.endswith(("wake", "leak")) or stem.startswith("chrono"):
        return "animation"
    return None


def _theater_code(entry_name: str, configured_theater: str = "auto") -> str:
    suffix = Path(entry_name).suffix.casefold().lstrip(".")
    if suffix in _THEATER_SUFFIXES:
        return suffix
    configured = configured_theater.casefold()
    if configured in _THEATER_SUFFIXES:
        return configured
    return "tem"


def _is_building_buildup_shp(entry_name: str, asset_type: str) -> bool:
    suffix = Path(entry_name).suffix.casefold()
    normalized_type = asset_type.casefold()
    is_shp = suffix == ".shp" or normalized_type in {"shp", "shp-ts"}
    return is_shp and Path(entry_name).stem.casefold().endswith("mk")


def _is_standard_cameo_shp(
    entry: MixEntry,
    *,
    archive: MixArchiveIndex | None = None,
    path: Path | None = None,
) -> bool:
    if archive is not None:
        header = read_mix_entry_prefix(archive, entry, max_bytes=8)
    elif path is not None:
        try:
            with path.open("rb") as source:
                header = source.read(8)
        except OSError:
            return False
    else:
        return False
    if header is None or len(header) != 8:
        return False
    zero, width, height, frame_count = struct.unpack("<HHHH", header)
    return zero == 0 and (width, height, frame_count) == (60, 48, 1)


def _archive_context_palette_names(
    palette_context: tuple[str, ...],
    asset_type: str,
    palette_theater: str,
) -> tuple[str, ...]:
    if asset_type.casefold() not in {"shp", "shp-ts"}:
        return ()
    has_generic_iso_archive = False
    for part in reversed(palette_context):
        archive_path = Path(part)
        if archive_path.suffix.casefold() != ".mix":
            continue
        archive_stem = archive_path.stem.casefold()
        if archive_stem == "cameo":
            return ("cameo.pal",)
        if not archive_stem.startswith("iso"):
            theater = _THEATER_ARCHIVE_THEATERS.get(archive_stem)
            if theater is not None:
                return (_THEATER_SUFFIXES[theater][0],)
            continue
        theater_name = archive_stem[3:]
        if theater_name.endswith("md"):
            theater_name = theater_name[:-2]
        if theater_name == "gen":
            has_generic_iso_archive = True
            continue
        theater = _ISO_ARCHIVE_THEATERS.get(theater_name)
        if theater is not None:
            return (_THEATER_SUFFIXES[theater][1],)
    if has_generic_iso_archive:
        theater = _theater_code("", palette_theater)
        return (_THEATER_SUFFIXES[theater][1],)
    return ()


def _is_enabled(value: str) -> bool:
    return value.strip().casefold() in {"yes", "true", "1"}


def _rgb_triplets(data: bytes) -> tuple[tuple[int, int, int], ...]:
    return tuple(tuple(data[offset : offset + 3]) for offset in range(0, len(data) - 2, 3))


def _palette_with_fallback(
    colors: tuple[tuple[int, int, int], ...],
    name: str,
) -> PaletteOption:
    if not colors:
        colors = tuple((index, index, index) for index in range(256))
    return PaletteOption(name, _pad_colors(colors), len(colors))


def _pad_colors(colors: tuple[tuple[int, int, int], ...]) -> tuple[tuple[int, int, int], ...]:
    if len(colors) >= 256:
        return colors[:256]
    return (*colors, *((0, 0, 0),) * (256 - len(colors)))


def _grayscale_palette() -> PaletteOption:
    colors = tuple((value, value, value) for value in range(256))
    return PaletteOption("Grayscale", colors, 256, group="fallback")
