from __future__ import annotations

from pathlib import Path
from threading import RLock

from mix_browser.features.archive.domain import (
    MixArchiveIndex,
    MixArchiveParent,
    MixEntry,
    MixNameCandidateIndex,
    open_mix_archive,
)
from mix_browser.features.archive.name_catalog import (
    MixNameCatalog,
    validate_mix_name_game,
)


# @arch mix-browser.archive-loader service | en: Loads MIX archives with configured name sources and game selection | zh: 使用已配置名称来源与游戏选择加载 MIX 归档
class MixArchiveLoader:
    def __init__(self, *, xcc_names_enabled: bool = True, community_names_enabled: bool = False) -> None:
        self._lock = RLock()
        self._name_sources_enabled = {
            "xcc": xcc_names_enabled,
            "community": community_names_enabled,
        }
        self._name_catalog = MixNameCatalog(
            xcc_enabled=xcc_names_enabled,
            community_enabled=community_names_enabled,
        )

    def prewarm_name_sources(self) -> None:
        self._name_catalog.prewarm_name_sources()

    def set_name_sources(self, *, xcc: bool, community: bool) -> None:
        with self._lock:
            self._name_sources_enabled = {"xcc": xcc, "community": community}
            self._name_catalog.set_enabled_sources(xcc=xcc, community=community)

    def set_active_name_game(self, game: str) -> None:
        with self._lock:
            self._name_catalog.set_active_game(game)

    def reload_name_sources(self, *, xcc: bool = False, community: bool = False) -> None:
        with self._lock:
            self._name_catalog.reload_name_sources(xcc=xcc, community=community)

    @property
    def name_sources_enabled(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._name_sources_enabled)

    def create_session(self, *, name_game: str | None = None) -> MixArchiveLoadSession:
        with self._lock:
            selected_game = (
                self._name_catalog.active_game
                if name_game is None
                else validate_mix_name_game(name_game)
            )
            return MixArchiveLoadSession(self, selected_game)

    def load(
        self,
        path: Path,
        *,
        source_offset: int = 0,
        source_size: int | None = None,
        parents: tuple[MixArchiveParent, ...] = (),
        discover_names: bool = True,
    ) -> MixArchiveIndex:
        return self._load(
            path,
            source_offset=source_offset,
            source_size=source_size,
            parents=parents,
            candidate_index=None,
            include_candidate_snapshot=discover_names,
        )

    def _load(
        self,
        path: Path,
        *,
        source_offset: int = 0,
        source_size: int | None = None,
        parents: tuple[MixArchiveParent, ...] = (),
        candidate_index: MixNameCandidateIndex | None,
        name_game: str | None = None,
        include_candidate_snapshot: bool = True,
        candidate_names_override: tuple[MixNameCandidate, ...] | None = None,
    ) -> MixArchiveIndex:
        with self._lock:
            if candidate_names_override is not None:
                candidate_names = candidate_names_override
            else:
                candidate_names = (
                    self._name_catalog.candidates_for(
                        name_game=name_game,
                    )
                    if include_candidate_snapshot
                    else ()
                )
            archive = open_mix_archive(
                path,
                candidate_names=candidate_names,
                candidate_index=candidate_index,
                source_offset=source_offset,
                source_size=source_size,
                parents=parents,
            )
            learned_candidates = self._name_catalog.remember_archive(
                archive,
                name_game=name_game,
            )
            if candidate_index is not None:
                candidate_index.add_candidates(learned_candidates)
            return archive

    def load_nested(self, parent: MixArchiveIndex, entry: MixEntry) -> MixArchiveIndex:
        return self._load_nested(
            parent,
            entry,
            candidate_index=None,
        )

    def _load_nested(
        self,
        parent: MixArchiveIndex,
        entry: MixEntry,
        *,
        candidate_index: MixNameCandidateIndex | None,
        name_game: str | None = None,
        include_candidate_snapshot: bool = True,
        candidate_names_override: tuple[MixNameCandidate, ...] | None = None,
    ) -> MixArchiveIndex:
        source_offset = parent.data_start + entry.offset
        source_end = source_offset + entry.size
        parent_end = parent.source_offset + parent.source_size
        if source_offset < parent.source_offset or source_end > parent_end:
            raise ValueError("The nested MIX entry extends beyond its parent archive range.")
        return self._load(
            parent.path,
            source_offset=source_offset,
            source_size=entry.size,
            parents=(
                *parent.parents,
                MixArchiveParent(parent.source_offset, parent.source_size, entry.file_id),
            ),
            candidate_index=candidate_index,
            name_game=name_game,
            include_candidate_snapshot=include_candidate_snapshot,
            candidate_names_override=candidate_names_override,
        )


# @arch mix-browser.archive-load-session service | en: Reuses name candidates learned during one archive browsing session | zh: 在单次归档浏览会话中复用已识别的名称候选
class MixArchiveLoadSession:
    def __init__(self, loader: MixArchiveLoader, name_game: str | None = None) -> None:
        self._loader = loader
        self._name_game = name_game or loader._name_catalog.active_game
        self._candidate_index = MixNameCandidateIndex()
        self._candidate_snapshot: tuple[MixNameCandidate, ...] | None = None
        self._candidate_snapshot_initialized = False

    def load(
        self,
        path: Path,
        *,
        source_offset: int = 0,
        source_size: int | None = None,
        parents: tuple[MixArchiveParent, ...] = (),
        discover_names: bool = True,
        refresh_candidates: bool = False,
    ) -> MixArchiveIndex:
        with self._loader._lock:
            candidate_names = self._candidate_names(
                discover_names=discover_names,
                refresh_candidates=refresh_candidates,
            )
            archive = self._loader._load(
                path,
                source_offset=source_offset,
                source_size=source_size,
                parents=parents,
                candidate_index=self._candidate_index,
                name_game=self._name_game,
                include_candidate_snapshot=False,
                candidate_names_override=candidate_names,
            )
            return archive

    def load_nested(
        self,
        parent: MixArchiveIndex,
        entry: MixEntry,
        *,
        refresh_candidates: bool = False,
    ) -> MixArchiveIndex:
        with self._loader._lock:
            candidate_names = self._candidate_names(
                discover_names=True,
                refresh_candidates=refresh_candidates,
            )
            archive = self._loader._load_nested(
                parent,
                entry,
                candidate_index=self._candidate_index,
                name_game=self._name_game,
                include_candidate_snapshot=False,
                candidate_names_override=candidate_names,
            )
            return archive

    def _candidate_names(
        self,
        *,
        discover_names: bool,
        refresh_candidates: bool,
    ) -> tuple[MixNameCandidate, ...]:
        if not discover_names or (
            self._candidate_snapshot_initialized and not refresh_candidates
        ):
            return ()
        candidate_names = self._loader._name_catalog.candidates_for(
            name_game=self._name_game,
        )
        if candidate_names is not self._candidate_snapshot:
            self._candidate_index = MixNameCandidateIndex()
            self._candidate_snapshot = candidate_names
        self._candidate_snapshot_initialized = True
        return candidate_names
