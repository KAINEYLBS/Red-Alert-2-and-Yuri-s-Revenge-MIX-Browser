from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Audio, FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError

from mix_browser.app.api import MixBrowserApplication
from mix_browser.shared.application_identity import APPLICATION_DISPLAY_NAME
from mix_browser.shared.application_errors import ApplicationApiError

_MAX_INLINE_MEDIA_BYTES = 8 * 1024 * 1024


def _tool_call(operation):
    try:
        return operation()
    except ApplicationApiError as exc:
        raise ToolError(f"{exc.code}: {exc.message}") from exc
    except OSError as exc:
        raise ToolError(f"io_error: {exc}") from exc
    except ValueError as exc:
        raise ToolError(f"invalid_input: {exc}") from exc


# @arch mix-browser.mcp-server adapter | en: Registers application API operations as MCP tools | zh: 将应用 API 操作注册为 MCP 工具
def create_server(application: MixBrowserApplication | None = None) -> FastMCP:
    api = application or MixBrowserApplication()
    server = FastMCP(APPLICATION_DISPLAY_NAME)

    # @arch mix-browser.mcp-download-community-name-database tool | en: Downloads the optional CnCNet MIX name database through the archive API | zh: 通过归档应用 API 下载可选的 CnCNet MIX 名称数据库
    @server.tool()
    def download_community_name_database() -> dict[str, object]:
        """Download the optional community name database from its CnCNet attachment."""
        return _tool_call(api.download_community_name_database)

    # @arch mix-browser.mcp-list-directory tool | en: Lists and classifies direct filesystem children | zh: 列出并识别文件系统的直接子项
    @server.tool()
    def list_directory(path: str) -> dict[str, object]:
        """List one directory level with type, size, and modification time."""
        return _tool_call(lambda: api.list_directory(Path(path)))

    # @arch mix-browser.mcp-add-directory-files tool | en: Copies local files into a filesystem directory | zh: 将本地文件复制到文件系统目录
    @server.tool()
    def add_files_to_directory(
        path: str,
        source_paths: list[str],
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Copy local files into a directory, optionally replacing same-named files."""
        return _tool_call(
            lambda: api.add_files_to_directory(
                Path(path),
                tuple(Path(source) for source in source_paths),
                overwrite=overwrite,
            )
        )

    # @arch mix-browser.mcp-create-directory tool | en: Creates one directory inside a filesystem folder | zh: 在文件系统目录中创建一个子目录
    @server.tool()
    def create_directory(path: str, name: str) -> dict[str, object]:
        """Create one child directory without replacing an existing item."""
        return _tool_call(lambda: api.create_directory(Path(path), name))

    # @arch mix-browser.mcp-create-file tool | en: Creates an empty file in a filesystem folder | zh: 在文件系统目录中创建空文件
    @server.tool()
    def create_file(path: str, name: str) -> dict[str, object]:
        """Create one empty file without replacing an existing item."""
        return _tool_call(lambda: api.create_file(Path(path), name))

    # @arch mix-browser.mcp-rename-directory-entry tool | en: Renames one filesystem entry without replacement | zh: 重命名单个文件系统对象且不覆盖目标
    @server.tool()
    def rename_directory_entry(path: str, new_name: str) -> dict[str, object]:
        """Rename one filesystem file or folder without replacing another item."""
        return _tool_call(lambda: api.rename_directory_entry(Path(path), new_name))

    # @arch mix-browser.mcp-delete-directory-entries tool | en: Deletes filesystem entries by path | zh: 按路径删除文件系统对象
    @server.tool()
    def delete_directory_entries(paths: list[str]) -> dict[str, object]:
        """Permanently delete the specified filesystem files or folders."""
        return _tool_call(lambda: api.delete_directory_entries(tuple(Path(path) for path in paths)))

    # @arch mix-browser.mcp-transfer-directory-entries tool | en: Copies or moves filesystem entries into a folder | zh: 将文件系统对象复制或移动到目录中
    @server.tool()
    def transfer_directory_entries(
        destination: str,
        source_paths: list[str],
        move: bool = False,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Copy or move files and folders into a directory, optionally replacing matching items."""
        return _tool_call(
            lambda: api.transfer_directory_entries(
                Path(destination),
                tuple(Path(path) for path in source_paths),
                move=move,
                overwrite=overwrite,
            )
        )

    # @arch mix-browser.mcp-create-empty-mix tool | en: Creates an empty standard MIX archive and optionally replaces an existing path | zh: 创建标准空 MIX 归档并可选择替换现有路径
    @server.tool()
    def create_empty_mix_archive(
        path: str,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Create an empty standard MIX archive, optionally replacing an existing path."""
        return _tool_call(lambda: api.create_empty_mix(Path(path), overwrite=overwrite))

    # @arch mix-browser.mcp-inspect-mix tool | en: Lists the entries and resolved names of a MIX archive | zh: 列出 MIX 归档条目与解析出的名称
    @server.tool()
    def inspect_mix_archive(
        path: str,
        parent_entry_ids: list[int] | None = None,
        game: str | None = None,
    ) -> dict[str, object]:
        """Inspect a MIX archive using td, ra, ts, or ra2yr name inference."""
        return _tool_call(
            lambda: api.inspect_mix(
                Path(path),
                parent_entry_ids=tuple(parent_entry_ids or ()),
                name_game=game,
            )
        )

    # @arch mix-browser.mcp-extract-entry tool | en: Extracts one MIX entry to a local path | zh: 将一个 MIX 条目提取到本地路径
    @server.tool()
    def extract_mix_entry(
        path: str,
        entry_id: int,
        output_path: str,
        parent_entry_ids: list[int] | None = None,
    ) -> dict[str, object]:
        """Extract one entry, refusing to overwrite an existing output file."""
        return _tool_call(
            lambda: api.extract_mix_entry(
                Path(path),
                entry_id,
                Path(output_path),
                parent_entry_ids=tuple(parent_entry_ids or ()),
            )
        )

    # @arch mix-browser.mcp-replace-entry tool | en: Replaces one MIX entry using guarded atomic write-back | zh: 使用带校验的原子写回替换一个 MIX 条目
    @server.tool()
    def replace_mix_entry(
        path: str,
        entry_id: int,
        replacement_path: str,
        parent_entry_ids: list[int] | None = None,
    ) -> dict[str, object]:
        """Replace a MIX entry; the source archive is modified atomically."""
        return _tool_call(
            lambda: api.replace_mix_entry(
                Path(path),
                entry_id,
                Path(replacement_path),
                parent_entry_ids=tuple(parent_entry_ids or ()),
            )
        )

    # @arch mix-browser.mcp-add-mix-files tool | en: Adds local files to a MIX archive using atomic rewrite | zh: 通过原子重写将本地文件加入 MIX 归档
    @server.tool()
    def add_files_to_mix_archive(
        path: str,
        source_paths: list[str],
        parent_entry_ids: list[int] | None = None,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Add local files to a MIX archive or nested MIX, optionally replacing matching entries."""
        return _tool_call(
            lambda: api.add_files_to_mix(
                Path(path),
                tuple(Path(source) for source in source_paths),
                parent_entry_ids=tuple(parent_entry_ids or ()),
                overwrite=overwrite,
            )
        )

    # @arch mix-browser.mcp-edit-mix-entries tool | en: Deletes, renames, or copies entries using the MIX archive edit API | zh: 通过 MIX 归档编辑 API 删除、重命名或复制条目
    @server.tool()
    def edit_mix_entries(
        path: str,
        parent_entry_ids: list[int] | None = None,
        remove_entry_ids: list[int] | None = None,
        rename_entries: dict[str, str] | None = None,
        source_archive_path: str | None = None,
        source_parent_entry_ids: list[int] | None = None,
        copy_entry_ids: list[int] | None = None,
    ) -> dict[str, object]:
        """Delete, rename, or copy entries in a MIX archive or nested archive."""
        try:
            renames = {
                int(entry_id, 16 if entry_id.casefold().startswith("0x") else 10): name
                for entry_id, name in (rename_entries or {}).items()
            }
        except (TypeError, ValueError) as exc:
            raise ToolError("invalid_input: rename entry IDs must be decimal or 0x-prefixed strings") from exc
        return _tool_call(
            lambda: api.edit_mix_entries(
                Path(path),
                parent_entry_ids=tuple(parent_entry_ids or ()),
                remove_entry_ids=tuple(remove_entry_ids or ()),
                rename_entries=renames,
                source_archive_path=Path(source_archive_path) if source_archive_path else None,
                source_parent_entry_ids=tuple(source_parent_entry_ids or ()),
                copy_entry_ids=tuple(copy_entry_ids or ()),
            )
        )

    # @arch mix-browser.mcp-search tool | en: Searches recursively through directories and nested MIX archives | zh: 递归搜索目录与嵌套 MIX 归档
    @server.tool()
    def search_from_root(
        root_path: str,
        query: str,
        regular_expression: bool = False,
        parent_entry_ids: list[int] | None = None,
        max_results: int = 1000,
        game: str | None = None,
    ) -> dict[str, object]:
        """Search names and paths using td, ra, ts, or ra2yr name inference."""
        return _tool_call(
            lambda: api.search(
                Path(root_path),
                query,
                regular_expression=regular_expression,
                parent_entry_ids=tuple(parent_entry_ids or ()),
                max_results=max_results,
                name_game=game,
            )
        )

    # @arch mix-browser.mcp-detect-type tool | en: Detects a file's content type from its data | zh: 根据文件内容识别其类型
    @server.tool()
    def detect_file_type(path: str) -> dict[str, object]:
        """Detect a file's content type without relying only on its extension."""
        return _tool_call(lambda: api.detect_file_type(Path(path)))

    # @arch mix-browser.mcp-preview tool | en: Previews text and game assets without opening the desktop interface | zh: 不打开桌面界面预览文本与游戏资源
    @server.tool()
    def preview_entry(
        path: str,
        entry_id: int | None = None,
        parent_entry_ids: list[int] | None = None,
        game_directory: str | None = None,
        palette_theater: str = "auto",
        palette_library: list[dict[str, str]] | None = None,
        frame_index: int = 0,
        palette_index: int | None = None,
        encoding: str | None = None,
        game: str | None = None,
    ) -> Any:
        """Return document and palette data, plus PNG or WAV content when available."""
        library_rules = []
        for rule in palette_library or ():
            if not rule.get("path"):
                raise ToolError("invalid_input: each palette library item requires a path")
            library_rules.append(
                (Path(rule["path"]), rule.get("asset_pattern", ""))
            )
        result = _tool_call(
            lambda: api.preview(
                Path(path),
                entry_id=entry_id,
                parent_entry_ids=tuple(parent_entry_ids or ()),
                game_directory=Path(game_directory) if game_directory else None,
                palette_theater=palette_theater,
                palette_library=tuple(library_rules),
                frame_index=frame_index,
                palette_index=palette_index,
                encoding=encoding,
                name_game=game,
            )
        )
        image_data = result.pop("image_png", None)
        media_data = result.pop("media_data", None)
        content: list[Any] = [result]
        if isinstance(image_data, bytes):
            if len(image_data) <= _MAX_INLINE_MEDIA_BYTES:
                content.append(Image(data=image_data, format="png"))
            else:
                result["inline_content_omitted"] = "PNG exceeds the MCP inline content limit; use the CLI preview output instead."
        elif isinstance(media_data, bytes) and result.get("media", {}).get("suffix") == ".wav":
            if len(media_data) <= _MAX_INLINE_MEDIA_BYTES:
                content.append(Audio(data=media_data, format="wav"))
            else:
                result["inline_content_omitted"] = "WAV exceeds the MCP inline content limit; extract the MIX entry instead."
        return content

    # @arch mix-browser.mcp-system-integration-state tool | en: Reports per-user Windows shell registration and container extension state | zh: 返回当前用户的 Windows 外壳注册与容器扩展名状态
    @server.tool()
    def get_system_integration_state() -> dict[str, object]:
        """Return directory, MIX New menu, and per-extension integration state."""
        return _tool_call(api.get_system_integration_state)

    # @arch mix-browser.mcp-configure-system-integration tool | en: Registers or removes per-user Windows shell integration | zh: 注册或移除当前用户的 Windows 外壳集成
    @server.tool()
    def configure_system_integration(
        directory_context_menu: bool | None = None,
        mix_context_menu: bool | None = None,
        mix_new_menu: bool | None = None,
        mix_file_association: bool | None = None,
        container_file_associations: dict[str, bool] | None = None,
        container_file_context_menus: dict[str, bool] | None = None,
    ) -> dict[str, object]:
        """Register or remove Windows Explorer integrations for supported container extensions."""
        return _tool_call(
            lambda: api.configure_system_integration(
                directory_context_menu=directory_context_menu,
                mix_context_menu=mix_context_menu,
                mix_new_menu=mix_new_menu,
                mix_file_association=mix_file_association,
                container_file_associations=container_file_associations,
                container_file_context_menus=container_file_context_menus,
            )
        )

    return server


# @arch mix-browser.mcp-entrypoint entrypoint | en: Starts the local stdio MCP server | zh: 启动本地 stdio MCP 服务
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mix-browser-mcp")
    parser.add_argument("--no-xcc-names", action="store_true")
    community_names = parser.add_mutually_exclusive_group()
    community_names.add_argument(
        "--community-names",
        dest="community_names_enabled",
        action="store_true",
    )
    community_names.add_argument(
        "--no-community-names",
        dest="community_names_enabled",
        action="store_false",
    )
    parser.set_defaults(community_names_enabled=False)
    arguments = parser.parse_args(argv)
    application = MixBrowserApplication(
        xcc_names_enabled=not arguments.no_xcc_names,
        community_names_enabled=arguments.community_names_enabled,
    )
    create_server(application).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
