from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from mix_browser.app.api import MixBrowserApplication
from mix_browser.features.archive.name_catalog import (
    DEFAULT_MIX_NAME_GAME,
    MIX_NAME_GAME_KEYS,
)
from mix_browser.shared.application_errors import ApplicationApiError


_USAGE_ERROR_CODES = frozenset(
    {
        "invalid_input",
        "invalid_output",
        "invalid_regex",
        "invalid_mix",
        "invalid_nested_mix",
        "invalid_entry",
        "not_found",
        "not_directory",
        "entry_not_found",
        "entry_exists",
        "output_exists",
        "output_required",
        "invalid_palette_library",
        "unsupported_root",
        "unsupported_platform",
    }
)


def _entry_id(value: str) -> int:
    try:
        parsed = int(value, 16 if value.casefold().startswith("0x") else 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("entry ID must be decimal or 0x-prefixed hexadecimal") from exc
    if not 0 <= parsed <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("entry ID must fit in an unsigned 32-bit integer")
    return parsed


# @arch mix-browser.cli-parser utility | en: Defines the structured command-line contract | zh: 定义结构化命令行接口
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mix-browser-cli")
    parser.add_argument(
        "--game",
        choices=MIX_NAME_GAME_KEYS,
        default=DEFAULT_MIX_NAME_GAME,
        help="Select the game name database for MIX name inference",
    )
    parser.add_argument("--no-xcc-names", action="store_true", help="Disable the bundled XCC name source")
    community_names = parser.add_mutually_exclusive_group()
    community_names.add_argument(
        "--community-names",
        dest="community_names_enabled",
        action="store_true",
        help="Enable the downloaded community name source",
    )
    community_names.add_argument(
        "--no-community-names",
        dest="community_names_enabled",
        action="store_false",
        help="Disable the downloaded community name source",
    )
    parser.set_defaults(community_names_enabled=False)
    commands = parser.add_subparsers(dest="command", required=True)

    name_source_parser = commands.add_parser(
        "name-source",
        help="Manage optional MIX name databases",
    )
    name_source_commands = name_source_parser.add_subparsers(
        dest="name_source_command",
        required=True,
    )
    name_source_commands.add_parser(
        "download-community",
        help="Download the optional CnCNet community name database",
    )

    directory_parser = commands.add_parser("directory", help="List filesystem directories")
    directory_commands = directory_parser.add_subparsers(dest="directory_command", required=True)
    directory_list = directory_commands.add_parser("list", help="List one directory level")
    directory_list.add_argument("path", type=Path)
    directory_add = directory_commands.add_parser("add", help="Copy files into a directory")
    directory_add.add_argument("path", type=Path)
    directory_add.add_argument("sources", nargs="+", type=Path)
    directory_add.add_argument("--overwrite", action="store_true", help="Replace files with matching names")
    directory_create = directory_commands.add_parser("create", help="Create one directory")
    directory_create.add_argument("path", type=Path)
    directory_create.add_argument("name")
    directory_file_create = directory_commands.add_parser("file-create", help="Create one empty file")
    directory_file_create.add_argument("path", type=Path)
    directory_file_create.add_argument("name")
    directory_rename = directory_commands.add_parser("rename", help="Rename one filesystem item")
    directory_rename.add_argument("path", type=Path)
    directory_rename.add_argument("name")
    directory_delete = directory_commands.add_parser("delete", help="Delete filesystem items")
    directory_delete.add_argument("paths", nargs="+", type=Path)
    directory_transfer = directory_commands.add_parser("transfer", help="Copy or move items into a directory")
    directory_transfer.add_argument("destination", type=Path)
    directory_transfer.add_argument("sources", nargs="+", type=Path)
    directory_transfer.add_argument("--move", action="store_true", help="Move instead of copy")
    directory_transfer.add_argument("--overwrite", action="store_true", help="Replace matching destination items")

    archive_parser = commands.add_parser("archive", help="Inspect and modify MIX archives")
    archive_commands = archive_parser.add_subparsers(dest="archive_command", required=True)
    archive_create = archive_commands.add_parser("create", help="Create an empty MIX archive")
    archive_create.add_argument("path", type=Path)
    archive_create.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing output path",
    )

    archive_inspect = archive_commands.add_parser("inspect", help="List entries in a MIX archive")
    archive_inspect.add_argument("path", type=Path)
    archive_inspect.add_argument("--parent-entry-id", action="append", type=_entry_id, default=[])

    archive_extract = archive_commands.add_parser("extract", help="Extract one MIX entry")
    archive_extract.add_argument("path", type=Path)
    archive_extract.add_argument("entry_id", type=_entry_id)
    archive_extract.add_argument("output", type=Path)
    archive_extract.add_argument("--parent-entry-id", action="append", type=_entry_id, default=[])

    archive_replace = archive_commands.add_parser("replace", help="Replace one MIX entry")
    archive_replace.add_argument("path", type=Path)
    archive_replace.add_argument("entry_id", type=_entry_id)
    archive_replace.add_argument("replacement", type=Path)
    archive_replace.add_argument("--parent-entry-id", action="append", type=_entry_id, default=[])

    archive_add = archive_commands.add_parser("add", help="Add files to a MIX archive")
    archive_add.add_argument("path", type=Path)
    archive_add.add_argument("sources", nargs="+", type=Path)
    archive_add.add_argument("--parent-entry-id", action="append", type=_entry_id, default=[])
    archive_add.add_argument("--overwrite", action="store_true", help="Replace entries with matching names or IDs")

    archive_edit = archive_commands.add_parser("edit", help="Delete, rename, or copy MIX entries")
    archive_edit.add_argument("path", type=Path)
    archive_edit.add_argument("--parent-entry-id", action="append", type=_entry_id, default=[])
    archive_edit.add_argument("--remove-entry-id", action="append", type=_entry_id, default=[])
    archive_edit.add_argument("--rename", action="append", default=[], metavar="ID=NAME")
    archive_edit.add_argument("--source-archive", type=Path)
    archive_edit.add_argument("--source-parent-entry-id", action="append", type=_entry_id, default=[])
    archive_edit.add_argument("--copy-entry-id", action="append", type=_entry_id, default=[])

    search_parser = commands.add_parser("search", help="Search a directory tree or MIX archive")
    search_parser.add_argument("root", type=Path)
    search_parser.add_argument("query")
    search_parser.add_argument("--regex", action="store_true", help="Interpret the query as a regular expression")
    search_parser.add_argument("--max-results", type=int, default=1000)
    search_parser.add_argument("--parent-entry-id", action="append", type=_entry_id, default=[])

    type_parser = commands.add_parser("type", help="Detect a file's content type")
    type_parser.add_argument("path", type=Path)

    preview_parser = commands.add_parser("preview", help="Preview a file or MIX entry")
    preview_parser.add_argument("path", type=Path)
    preview_parser.add_argument("--entry-id", type=_entry_id)
    preview_parser.add_argument("--parent-entry-id", action="append", type=_entry_id, default=[])
    preview_parser.add_argument("--game-directory", type=Path)
    preview_parser.add_argument(
        "--palette-theater",
        choices=("auto", "tem", "sno", "urb", "des", "lun", "ubn"),
        default="auto",
    )
    preview_parser.add_argument("--palette-library", type=Path)
    preview_parser.add_argument("--frame-index", type=int, default=0)
    preview_parser.add_argument("--palette-index", type=int)
    preview_parser.add_argument("--encoding")
    preview_parser.add_argument("--output", type=Path, help="Output path for rendered image or media data")

    integration_parser = commands.add_parser(
        "system-integration",
        help="Inspect and manage Windows Explorer integration",
    )
    integration_commands = integration_parser.add_subparsers(
        dest="integration_command",
        required=True,
    )
    integration_commands.add_parser("status", help="Show current Windows registrations")
    integration_configure = integration_commands.add_parser(
        "configure",
        help="Register or remove Windows shell integration",
    )
    for option, help_text in (
        ("--directory-context-menu", "Directory context menu registration"),
        ("--mix-context-menu", ".mix context menu registration"),
        ("--mix-new-menu", ".mix New menu registration"),
        ("--mix-file-association", ".mix file handler registration"),
    ):
        integration_configure.add_argument(
            option,
            choices=("register", "unregister"),
            help=help_text,
        )
    integration_configure.add_argument(
        "--container-file-association",
        action="append",
        metavar="EXTENSION=register|unregister",
        help="Register or remove a container extension open handler; repeat per extension",
    )
    integration_configure.add_argument(
        "--container-context-menu",
        action="append",
        metavar="EXTENSION=register|unregister",
        help="Register or remove a container extension context menu; repeat per extension",
    )
    return parser


def _dispatch(application: MixBrowserApplication, arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "name-source":
        return application.download_community_name_database()
    if arguments.command == "directory":
        if arguments.directory_command == "create":
            return application.create_directory(arguments.path, arguments.name)
        if arguments.directory_command == "file-create":
            return application.create_file(arguments.path, arguments.name)
        if arguments.directory_command == "rename":
            return application.rename_directory_entry(arguments.path, arguments.name)
        if arguments.directory_command == "delete":
            return application.delete_directory_entries(tuple(arguments.paths))
        if arguments.directory_command == "transfer":
            return application.transfer_directory_entries(
                arguments.destination,
                tuple(arguments.sources),
                move=arguments.move,
                overwrite=arguments.overwrite,
            )
        if arguments.directory_command == "add":
            return application.add_files_to_directory(
                arguments.path,
                tuple(arguments.sources),
                overwrite=arguments.overwrite,
            )
        return application.list_directory(arguments.path)
    if arguments.command == "archive":
        if arguments.archive_command == "create":
            return application.create_empty_mix(
                arguments.path,
                overwrite=arguments.overwrite,
            )
        if arguments.archive_command == "inspect":
            return application.inspect_mix(
                arguments.path,
                parent_entry_ids=tuple(arguments.parent_entry_id),
            )
        if arguments.archive_command == "extract":
            return application.extract_mix_entry(
                arguments.path,
                arguments.entry_id,
                arguments.output,
                parent_entry_ids=tuple(arguments.parent_entry_id),
            )
        if arguments.archive_command == "add":
            return application.add_files_to_mix(
                arguments.path,
                tuple(arguments.sources),
                parent_entry_ids=tuple(arguments.parent_entry_id),
                overwrite=arguments.overwrite,
            )
        if arguments.archive_command == "edit":
            rename_entries: dict[int, str] = {}
            for value in arguments.rename:
                raw_id, separator, name = value.partition("=")
                if not separator or not name:
                    raise ApplicationApiError("invalid_input", "Rename values must use ID=NAME format.")
                try:
                    entry_id = _entry_id(raw_id)
                except argparse.ArgumentTypeError as exc:
                    raise ApplicationApiError("invalid_input", str(exc)) from exc
                rename_entries[entry_id] = name
            return application.edit_mix_entries(
                arguments.path,
                parent_entry_ids=tuple(arguments.parent_entry_id),
                remove_entry_ids=tuple(arguments.remove_entry_id),
                rename_entries=rename_entries,
                source_archive_path=arguments.source_archive,
                source_parent_entry_ids=tuple(arguments.source_parent_entry_id),
                copy_entry_ids=tuple(arguments.copy_entry_id),
            )
        return application.replace_mix_entry(
            arguments.path,
            arguments.entry_id,
            arguments.replacement,
            parent_entry_ids=tuple(arguments.parent_entry_id),
        )
    if arguments.command == "search":
        return application.search(
            arguments.root,
            arguments.query,
            regular_expression=arguments.regex,
            parent_entry_ids=tuple(arguments.parent_entry_id),
            max_results=arguments.max_results,
        )
    if arguments.command == "preview":
        palette_library = ()
        if arguments.palette_library is not None:
            try:
                raw_rules = json.loads(arguments.palette_library.read_text(encoding="utf-8"))
                if not isinstance(raw_rules, list):
                    raise ValueError("Palette library JSON must contain a list.")
                palette_library = tuple(
                    (Path(item["path"]), str(item.get("asset_pattern", "")))
                    for item in raw_rules
                )
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ApplicationApiError("invalid_palette_library", str(exc)) from exc
        return application.preview(
            arguments.path,
            entry_id=arguments.entry_id,
            parent_entry_ids=tuple(arguments.parent_entry_id),
            game_directory=arguments.game_directory,
            palette_theater=arguments.palette_theater,
            palette_library=palette_library,
            frame_index=arguments.frame_index,
            palette_index=arguments.palette_index,
            encoding=arguments.encoding,
        )
    if arguments.command == "system-integration":
        if arguments.integration_command == "status":
            return application.get_system_integration_state()
        return application.configure_system_integration(
            directory_context_menu=_registration_choice(
                arguments.directory_context_menu
            ),
            mix_context_menu=_registration_choice(arguments.mix_context_menu),
            mix_new_menu=_registration_choice(arguments.mix_new_menu),
            mix_file_association=_registration_choice(
                arguments.mix_file_association
            ),
            container_file_associations=_container_registration_choices(
                arguments.container_file_association
            ),
            container_file_context_menus=_container_registration_choices(
                arguments.container_context_menu
            ),
        )
    return application.detect_file_type(arguments.path)


def _registration_choice(value: str | None) -> bool | None:
    if value is None:
        return None
    return value == "register"


def _container_registration_choices(
    values: list[str] | None,
) -> dict[str, bool] | None:
    if values is None:
        return None
    choices: dict[str, bool] = {}
    for value in values:
        extension, separator, choice = value.partition("=")
        extension = extension.casefold()
        if not separator or not extension.startswith(".") or choice not in {
            "register",
            "unregister",
        }:
            raise ApplicationApiError(
                "invalid_input",
                "Container integration values must use EXTENSION=register|unregister.",
            )
        choices[extension] = choice == "register"
    return choices


# @arch mix-browser.cli entrypoint | en: Runs automation-friendly RA2AYRMB commands | zh: 执行适用于自动化的 RA2AYRMB 命令
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    application = MixBrowserApplication(
        xcc_names_enabled=not arguments.no_xcc_names,
        community_names_enabled=arguments.community_names_enabled,
        mix_name_game=arguments.game,
    )
    try:
        result = _dispatch(application, arguments)
        output_path = arguments.output if arguments.command == "preview" else None
        if isinstance(result.get("image_png"), bytes):
            if output_path is None:
                raise ApplicationApiError(
                    "output_required",
                    "Rendered image previews require --output so the PNG can be saved.",
                )
            _write_binary_output(output_path, result["image_png"])
            result = dict(result)
            result.pop("image_png", None)
            result["output_path"] = str(output_path.resolve())
        elif isinstance(result.get("media_data"), bytes):
            if output_path is None:
                raise ApplicationApiError(
                    "output_required",
                    "Audio and video previews require --output so the source data can be saved.",
                )
            _write_binary_output(output_path, result["media_data"])
            result = dict(result)
            result.pop("media_data", None)
            result["output_path"] = str(output_path.resolve())
    except ApplicationApiError as exc:
        _write_error(exc.code, exc.message)
        return 2 if exc.code in _USAGE_ERROR_CODES else 1
    except FileExistsError as exc:
        _write_error("output_exists", str(exc))
        return 2
    except OSError as exc:
        _write_error("io_error", str(exc))
        return 1
    except ValueError as exc:
        _write_error("invalid_input", str(exc))
        return 2
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def _write_error(code: str, message: str) -> None:
    json.dump({"error": {"code": code, "message": message}}, sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")


def _write_binary_output(path: Path, data: bytes) -> None:
    output = path.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with output.open("xb") as destination:
            created = True
            destination.write(data)
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
