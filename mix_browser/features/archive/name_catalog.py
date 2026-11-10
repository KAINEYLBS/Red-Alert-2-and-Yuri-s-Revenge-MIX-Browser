from __future__ import annotations

import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path

from mix_browser.features.archive.domain import (
    MixArchiveIndex,
    MixNameCandidate,
    is_readable_mix_name,
    _prewarm_mix_file_hashes,
)
from mix_browser.features.archive.dat_format import parse_xcc_dat_contents
from mix_browser.shared.application_settings import application_directory


_MAX_CANDIDATE_NAMES = 100_000
_MAX_SOURCES_PER_NAME = 4
_MAX_NAME_SOURCE_BYTES = 8 * 1024 * 1024
_COMMUNITY_DATABASE_DOWNLOAD_URL = (
    "https://forums.cncnet.org/applications/core/interface/file/attachment.php?id=40719"
)
_COMMUNITY_DATABASE_RELATIVE_PATH = Path(
    "name-sources/community/global_mix_database.dat.zip"
)
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
GameNameMap = dict[str, tuple[str, ...]]
NameSourceSnapshot = tuple[str, ...] | GameNameMap

XCC_NAME_SOURCE = "XCC MIX name list (GPL-3.0)"
COMMUNITY_NAME_SOURCE = "CnCNet Forums: Blade (2015-04-13)"
DEFAULT_MIX_NAME_GAME = "ra2yr"
MIX_NAME_GAME_GROUPS = (
    ("td", "Tiberian Dawn (TD)", "Database 1"),
    ("ra", "Red Alert (RA)", "Database 2"),
    ("ts", "Tiberian Sun (TS)", "Database 3"),
    ("ra2yr", "Red Alert 2 and Yuri's Revenge (RA2/YR)", "Database 4"),
)
MIX_NAME_GAME_KEYS = tuple(key for key, _label, _group in MIX_NAME_GAME_GROUPS)
_MIX_NAME_GAME_GROUP_BY_KEY = {
    key: (label, database_group)
    for key, label, database_group in MIX_NAME_GAME_GROUPS
}


def validate_mix_name_game(game: str) -> str:
    if game not in _MIX_NAME_GAME_GROUP_BY_KEY:
        choices = ", ".join(MIX_NAME_GAME_KEYS)
        raise ValueError(f"Unsupported MIX name database game: {game}. Choose from: {choices}")
    return game

_NAME_SOURCE_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "name_sources"
_XCC_NAME_LIST_PATHS = {
    "td": _NAME_SOURCE_DIRECTORY / "xcc" / "td mix description.txt",
    "ts": _NAME_SOURCE_DIRECTORY / "xcc" / "ts mix description.txt",
    "ra2yr": _NAME_SOURCE_DIRECTORY / "xcc" / "ra2 mix description.txt",
}
XCC_NAME_GAME_KEYS = frozenset(_XCC_NAME_LIST_PATHS)


# @arch mix-browser.community-name-database-path utility | en: Resolves the optional community database location beside the application | zh: 解析程序目录旁可选社区数据库的存储位置
def community_name_database_path() -> Path:
    return application_directory() / _COMMUNITY_DATABASE_RELATIVE_PATH


# @arch mix-browser.community-name-database-size service | en: Reads the remote CnCNet attachment size without downloading its content | zh: 读取 CnCNet 远程附件大小而不下载文件内容
def community_name_database_size_bytes() -> int:
    request = urllib.request.Request(
        _COMMUNITY_DATABASE_DOWNLOAD_URL,
        headers={"User-Agent": "RA2AYRMB"},
        method="HEAD",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if urllib.parse.urlsplit(response.geturl()).scheme.casefold() != "https":
                raise OSError("The community database size request redirected to a non-HTTPS URL.")
            total = int(response.headers.get("Content-Length", ""))
    except (TypeError, ValueError) as exc:
        raise OSError("The community database size was not provided by CnCNet.") from exc
    except urllib.error.URLError as exc:
        raise OSError(f"The community database size could not be retrieved: {exc.reason}") from exc

    if total <= 0 or total > _MAX_NAME_SOURCE_BYTES:
        raise OSError("CnCNet returned an invalid community database size.")
    return total


# @arch mix-browser.download-community-name-database service | en: Downloads and validates the optional CnCNet MIX name database | zh: 下载并验证可选的 CnCNet MIX 名称数据库
def download_community_name_database(
    *,
    progress: Callable[[int, int], None] | None = None,
    cancellation_requested: Callable[[], bool] | None = None,
) -> Path:
    if cancellation_requested is not None and cancellation_requested():
        raise InterruptedError("The community database download was cancelled.")
    destination = community_name_database_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    request = urllib.request.Request(
        _COMMUNITY_DATABASE_DOWNLOAD_URL,
        headers={"User-Agent": "RA2AYRMB"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if urllib.parse.urlsplit(response.geturl()).scheme.casefold() != "https":
                raise OSError("The community database download redirected to a non-HTTPS URL.")
            raw_total = response.headers.get("Content-Length", "")
            try:
                total = int(raw_total)
            except (TypeError, ValueError):
                total = 0
            if total < 0:
                total = 0
            if total > _MAX_NAME_SOURCE_BYTES:
                raise ValueError("The community database download exceeds the size limit.")
            if progress is not None:
                progress(0, total)

            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".community-name-database-",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                downloaded = 0
                while True:
                    if cancellation_requested is not None and cancellation_requested():
                        raise InterruptedError("The community database download was cancelled.")
                    chunk = response.read(
                        min(_DOWNLOAD_CHUNK_BYTES, _MAX_NAME_SOURCE_BYTES + 1 - downloaded)
                    )
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > _MAX_NAME_SOURCE_BYTES:
                        raise ValueError("The community database download exceeds the size limit.")
                    output.write(chunk)
                    if progress is not None:
                        progress(downloaded, total)

        if total > 0 and downloaded != total:
            raise OSError("The community database download was incomplete.")
        if cancellation_requested is not None and cancellation_requested():
            raise InterruptedError("The community database download was cancelled.")
        assert temporary_path is not None
        _validate_community_database_archive(temporary_path)
        os.replace(temporary_path, destination)
        temporary_path = None
        return destination
    except urllib.error.URLError as exc:
        raise OSError(f"The community database could not be downloaded: {exc.reason}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _validate_community_database_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as source_zip:
            info = source_zip.getinfo("global mix database.dat")
            if info.file_size <= 0 or info.file_size > _MAX_NAME_SOURCE_BYTES:
                raise ValueError("The community database file has an invalid size.")
            with source_zip.open(info) as source_file:
                data = source_file.read(_MAX_NAME_SOURCE_BYTES + 1)
    except (OSError, KeyError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        raise ValueError("The downloaded community database is not a valid XCC ZIP archive.") from exc
    if len(data) != info.file_size or len(data) > _MAX_NAME_SOURCE_BYTES:
        raise ValueError("The downloaded community database is incomplete or oversized.")
    if not _community_names_by_game(data).get(DEFAULT_MIX_NAME_GAME):
        raise ValueError("The downloaded archive does not contain a readable RA2 name database.")


# @arch mix-browser.mix-name-catalog service | en: Discovers readable MIX entry names from configured sources | zh: 从配置的数据源发现可读的 MIX 条目名
class MixNameCatalog:
    def __init__(self, *, xcc_enabled: bool = True, community_enabled: bool = False) -> None:
        self._learned_sources: dict[str, dict[str, list[str]]] = {}
        self._enabled_sources = {
            "xcc": xcc_enabled,
            "community": community_enabled,
        }
        self._source_names: dict[
            str,
            NameSourceSnapshot | None,
        ] = {
            "xcc": None,
            "community": None,
        }
        self._active_game = DEFAULT_MIX_NAME_GAME
        self._candidate_cache: tuple[
            tuple[bool, bool, str, int],
            tuple[MixNameCandidate, ...],
        ] | None = None
        self._learned_generation = 0

    def prewarm_name_sources(self) -> None:
        names: list[str] = []
        for source_key in ("xcc", "community"):
            if not self._enabled_sources[source_key]:
                continue
            source_names = _load_name_source(source_key)
            if isinstance(source_names, dict):
                names.extend(
                    name
                    for game_names in source_names.values()
                    for name in game_names
                )
            elif source_names is not None:
                names.extend(source_names)
        _prewarm_mix_file_hashes(names)

    def set_active_game(self, game: str) -> None:
        validate_mix_name_game(game)
        if game == self._active_game:
            return
        self._active_game = game
        self._learned_sources.clear()
        self._candidate_cache = None
        self._learned_generation += 1

    @property
    def active_game(self) -> str:
        return self._active_game

    def set_enabled_sources(self, *, xcc: bool, community: bool) -> None:
        enabled_sources = {"xcc": xcc, "community": community}
        if enabled_sources == self._enabled_sources:
            return
        self._enabled_sources = enabled_sources
        self._learned_sources.clear()
        self._candidate_cache = None
        self._learned_generation += 1

    def reload_name_sources(self, *, xcc: bool = False, community: bool = False) -> None:
        if xcc:
            self._source_names["xcc"] = None
        if community:
            self._source_names["community"] = None
        if xcc or community:
            self._candidate_cache = None
            self._learned_generation += 1

    def candidates_for(
        self,
        *,
        name_game: str | None = None,
    ) -> tuple[MixNameCandidate, ...]:
        active_game = (
            self._active_game
            if name_game is None
            else validate_mix_name_game(name_game)
        )
        cache_key = (
            self._enabled_sources["xcc"],
            self._enabled_sources["community"],
            active_game,
            self._learned_generation,
        )
        if self._candidate_cache is not None and self._candidate_cache[0] == cache_key:
            return self._candidate_cache[1]

        sources_by_name: dict[str, list[str]] = {}
        for source_key, source_label in (
            ("xcc", XCC_NAME_SOURCE),
            ("community", COMMUNITY_NAME_SOURCE),
        ):
            if not self._enabled_sources[source_key]:
                continue
            if self._source_names[source_key] is None:
                self._source_names[source_key] = _load_name_source(source_key)
            source_names = self._source_names[source_key]
            if isinstance(source_names, dict):
                game_label, _database_group = _MIX_NAME_GAME_GROUP_BY_KEY[
                    active_game
                ]
                names = source_names.get(active_game, ())
                if names:
                    source_label = f"{source_label}: {game_label}"
            else:
                names = source_names or ()
            for name in names:
                _add_candidate(sources_by_name, name, source_label)
        for name, sources in self._learned_sources.get(active_game, {}).items():
            if name not in sources_by_name and len(sources_by_name) >= _MAX_CANDIDATE_NAMES:
                break
            target = sources_by_name.setdefault(name, [])
            for source in sources:
                _append_source(target, source)
        candidates = tuple(
            MixNameCandidate(name, source)
            for name in sorted(sources_by_name, key=str.casefold)
            for source in sources_by_name[name]
        )
        self._candidate_cache = (cache_key, candidates)
        return candidates

    def remember_archive(
        self,
        archive: MixArchiveIndex,
        *,
        name_game: str | None = None,
    ) -> tuple[MixNameCandidate, ...]:
        active_game = (
            self._active_game
            if name_game is None
            else validate_mix_name_game(name_game)
        )
        learned_sources = self._learned_sources.setdefault(active_game, {})
        fallback = f"Previously identified in {archive.path.name}"
        learned: list[MixNameCandidate] = []
        for entry in archive.entries:
            if not entry.name:
                continue
            if (
                entry.name not in learned_sources
                and len(learned_sources) >= _MAX_CANDIDATE_NAMES
            ):
                continue
            sources = learned_sources.setdefault(entry.name, [])
            for source in entry.name_sources or (fallback,):
                if source in sources or len(sources) >= _MAX_SOURCES_PER_NAME:
                    continue
                sources.append(source)
                learned.append(MixNameCandidate(entry.name, source))
        if learned:
            self._learned_generation += 1
            self._candidate_cache = None
        return tuple(learned)


def _load_name_source(source_key: str) -> NameSourceSnapshot:
    if source_key == "xcc":
        names_by_game: GameNameMap = {}
        for game_key, path in _XCC_NAME_LIST_PATHS.items():
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if len(data) > _MAX_NAME_SOURCE_BYTES:
                continue
            try:
                text = data.decode("ascii")
            except UnicodeDecodeError:
                continue
            names_by_game[game_key] = tuple(
                name
                for line in text.splitlines()
                if is_readable_mix_name(name := line.partition("\t")[0].strip())
            )
        return names_by_game

    if source_key == "community":
        community_path = community_name_database_path()
        try:
            with zipfile.ZipFile(community_path) as source_zip:
                info = source_zip.getinfo("global mix database.dat")
                if info.file_size > _MAX_NAME_SOURCE_BYTES:
                    return {}
                with source_zip.open(info) as source_file:
                    data = source_file.read(_MAX_NAME_SOURCE_BYTES + 1)
        except (OSError, KeyError, zipfile.BadZipFile, RuntimeError):
            return ()
        if len(data) > _MAX_NAME_SOURCE_BYTES:
            return {}
        return _community_names_by_game(data)

    return ()


def _community_names_by_game(data: bytes) -> GameNameMap:
    contents = parse_xcc_dat_contents(data)
    if contents is None or contents.format_name != "Global MIX name database":
        return {}
    return {
        game_key: tuple(
            record.name
            for record in contents.records
            if record.group == database_group and is_readable_mix_name(record.name)
        )
        for game_key, _game_label, database_group in MIX_NAME_GAME_GROUPS
    }


def _add_candidate(
    sources_by_name: dict[str, list[str]],
    raw_name: str,
    source: str,
) -> None:
    name = raw_name.strip()
    if not _is_candidate_name(name):
        return
    if name not in sources_by_name and len(sources_by_name) >= _MAX_CANDIDATE_NAMES:
        return
    sources = sources_by_name.setdefault(name, [])
    _append_source(sources, source)


def _append_source(sources: list[str], source: str) -> None:
    if source not in sources and len(sources) < _MAX_SOURCES_PER_NAME:
        sources.append(source)


def _is_candidate_name(name: str) -> bool:
    if not name or len(name) > 260 or name != name.strip():
        return False
    return name.isascii() and all(character.isprintable() for character in name) and not any(
        character in '<>:"/\\|?*' for character in name
    )
