from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mix_browser.features.archive.api import MixArchiveApplication
from mix_browser.features.archive.loader import MixArchiveLoader
from mix_browser.features.archive.name_catalog import DEFAULT_MIX_NAME_GAME
from mix_browser.features.browser.api import MixBrowserFeatureApplication
from mix_browser.features.system_integration.api import SystemIntegrationApplication

__all__ = ["MixBrowserApplication"]


# @arch mix-browser.application-api component | en: Composes feature application APIs for desktop and automation adapters | zh: 为桌面与自动化适配器装配功能应用 API
class MixBrowserApplication:
    def __init__(
        self,
        *,
        xcc_names_enabled: bool = True,
        community_names_enabled: bool = False,
        mix_name_game: str = DEFAULT_MIX_NAME_GAME,
    ) -> None:
        loader = MixArchiveLoader(
            xcc_names_enabled=xcc_names_enabled,
            community_names_enabled=community_names_enabled,
        )
        loader.set_active_name_game(mix_name_game)
        self.archives = MixArchiveApplication(loader)
        self.browser = MixBrowserFeatureApplication(loader)
        self.system_integration = SystemIntegrationApplication()

    def get_system_integration_state(self) -> dict[str, object]:
        return self.system_integration.get_state()

    def configure_system_integration(
        self,
        *,
        directory_context_menu: bool | None = None,
        mix_context_menu: bool | None = None,
        mix_new_menu: bool | None = None,
        mix_file_association: bool | None = None,
        container_file_associations: dict[str, bool] | None = None,
        container_file_context_menus: dict[str, bool] | None = None,
    ) -> dict[str, object]:
        return self.system_integration.configure(
            directory_context_menu=directory_context_menu,
            mix_context_menu=mix_context_menu,
            mix_new_menu=mix_new_menu,
            mix_file_association=mix_file_association,
            container_file_associations=container_file_associations,
            container_file_context_menus=container_file_context_menus,
        )

    def list_directory(self, directory: Path) -> dict[str, object]:
        return self.browser.list_directory(directory)

    def inspect_mix(
        self,
        archive_path: Path,
        *,
        parent_entry_ids: tuple[int, ...] = (),
        name_game: str | None = None,
    ) -> dict[str, object]:
        return self.archives.inspect(
            archive_path,
            parent_entry_ids=parent_entry_ids,
            name_game=name_game,
        )

    def create_empty_mix(
        self,
        destination: Path,
        *,
        overwrite: bool = False,
    ) -> dict[str, object]:
        return self.archives.create_empty_mix(destination, overwrite=overwrite)

    def download_community_name_database(
        self,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        return self.archives.download_community_name_database(
            progress=progress,
            cancellation_requested=cancellation_requested,
        )

    def extract_mix_entry(
        self,
        archive_path: Path,
        entry_id: int,
        destination: Path,
        *,
        parent_entry_ids: tuple[int, ...] = (),
    ) -> dict[str, object]:
        return self.archives.extract(
            archive_path,
            entry_id,
            destination,
            parent_entry_ids=parent_entry_ids,
        )

    def replace_mix_entry(
        self,
        archive_path: Path,
        entry_id: int,
        replacement_path: Path,
        *,
        parent_entry_ids: tuple[int, ...] = (),
    ) -> dict[str, object]:
        return self.archives.replace(
            archive_path,
            entry_id,
            replacement_path,
            parent_entry_ids=parent_entry_ids,
        )

    def add_files_to_mix(
        self,
        archive_path: Path,
        source_paths: tuple[Path, ...],
        *,
        parent_entry_ids: tuple[int, ...] = (),
        overwrite: bool = False,
        expected_archive_signature: tuple[int, int] | None = None,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        return self.archives.add_files(
            archive_path,
            source_paths,
            parent_entry_ids=parent_entry_ids,
            overwrite=overwrite,
            expected_archive_signature=expected_archive_signature,
            progress=progress,
            cancellation_requested=cancellation_requested,
        )

    def add_files_to_directory(
        self,
        directory: Path,
        source_paths: tuple[Path, ...],
        *,
        overwrite: bool = False,
        approved_overwrites: frozenset[str] | None = None,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        return self.browser.add_files_to_directory(
            directory,
            source_paths,
            overwrite=overwrite,
            approved_overwrites=approved_overwrites,
            progress=progress,
            cancellation_requested=cancellation_requested,
        )

    def create_directory(self, directory: Path, name: str) -> dict[str, object]:
        return self.browser.create_directory(directory, name)

    def create_file(self, directory: Path, name: str) -> dict[str, object]:
        return self.browser.create_file(directory, name)

    def rename_directory_entry(self, path: Path, new_name: str) -> dict[str, object]:
        return self.browser.rename_directory_entry(path, new_name)

    def delete_directory_entries(
        self,
        paths: tuple[Path, ...],
        *,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        return self.browser.delete_directory_entries(
            paths,
            progress=progress,
            cancellation_requested=cancellation_requested,
        )

    def transfer_directory_entries(
        self,
        destination: Path,
        source_paths: tuple[Path, ...],
        *,
        move: bool = False,
        overwrite: bool = False,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        return self.browser.transfer_directory_entries(
            destination,
            source_paths,
            move=move,
            overwrite=overwrite,
            progress=progress,
            cancellation_requested=cancellation_requested,
        )

    def edit_mix_entries(
        self,
        archive_path: Path,
        *,
        parent_entry_ids: tuple[int, ...] = (),
        remove_entry_ids: tuple[int, ...] = (),
        rename_entries: dict[int, str] | None = None,
        source_archive_path: Path | None = None,
        source_parent_entry_ids: tuple[int, ...] = (),
        copy_entry_ids: tuple[int, ...] = (),
        expected_archive_signature: tuple[int, int] | None = None,
        progress: Callable[[int, int], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        return self.archives.edit_entries(
            archive_path,
            parent_entry_ids=parent_entry_ids,
            remove_entry_ids=remove_entry_ids,
            rename_entries=rename_entries,
            source_archive_path=source_archive_path,
            source_parent_entry_ids=source_parent_entry_ids,
            copy_entry_ids=copy_entry_ids,
            expected_archive_signature=expected_archive_signature,
            progress=progress,
            cancellation_requested=cancellation_requested,
        )

    def detect_file_type(self, path: Path) -> dict[str, object]:
        return self.archives.detect_type(path)

    def preview(
        self,
        path: Path,
        *,
        entry_id: int | None = None,
        parent_entry_ids: tuple[int, ...] = (),
        game_directory: Path | None = None,
        palette_theater: str = "auto",
        palette_library: tuple[tuple[Path, str], ...] = (),
        frame_index: int = 0,
        palette_index: int | None = None,
        encoding: str | None = None,
        name_game: str | None = None,
    ) -> dict[str, object]:
        return self.browser.preview(
            path,
            entry_id=entry_id,
            parent_entry_ids=parent_entry_ids,
            game_directory=game_directory,
            palette_theater=palette_theater,
            palette_library=palette_library,
            frame_index=frame_index,
            palette_index=palette_index,
            encoding=encoding,
            name_game=name_game,
        )

    def search(
        self,
        root_path: Path,
        query: str,
        *,
        regular_expression: bool = False,
        parent_entry_ids: tuple[int, ...] = (),
        max_results: int = 1000,
        name_game: str | None = None,
    ) -> dict[str, object]:
        return self.browser.search(
            root_path,
            query,
            regular_expression=regular_expression,
            parent_entry_ids=parent_entry_ids,
            max_results=max_results,
            name_game=name_game,
        )
