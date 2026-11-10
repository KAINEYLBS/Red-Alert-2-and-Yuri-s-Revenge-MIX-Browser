# CLI and MCP Interfaces

RA2AYRMB exposes its archive and browser use cases through a JSON command-line interface and a local stdio MCP server. Both adapters call `MixBrowserApplication`; neither contains archive, search, or preview logic. The desktop UI continues to use the same feature services through its presentation workflows.

## Install

From the project directory, install the declared dependencies into the worktree environment:

```powershell
.venv\Scripts\python.exe -m pip install -e .
```

The project scripts are `mix-browser` for the desktop UI, `mix-browser-cli` for commands, and `mix-browser-mcp` for the MCP server. The modules can also be launched directly with the worktree interpreter:

```powershell
.venv\Scripts\python.exe -m mix_browser.cli --help
.venv\Scripts\python.exe -m mix_browser.cli name-source download-community
.venv\Scripts\python.exe -m mix_browser.mcp_server
```

The MCP server uses stdio. It does not start an HTTP listener.

## CLI

Successful commands write one JSON object to stdout. Failures write `{"error":{"code":"...","message":"..."}}` to stderr. Exit codes are `0` for success, `1` for an operation or I/O failure, and `2` for invalid input or an unsupported operation.

```powershell
.venv\Scripts\python.exe -m mix_browser.cli directory list "C:\Games\RA2"
.venv\Scripts\python.exe -m mix_browser.cli --game td archive inspect "C:\Games\TD\main.mix"
.venv\Scripts\python.exe -m mix_browser.cli directory add "C:\Games\RA2" .\new.ini
.venv\Scripts\python.exe -m mix_browser.cli directory create "C:\Games\RA2" NewFolder
.venv\Scripts\python.exe -m mix_browser.cli directory file-create "C:\Games\RA2" new.ini
.venv\Scripts\python.exe -m mix_browser.cli directory rename "C:\Games\RA2\old.ini" new.ini
.venv\Scripts\python.exe -m mix_browser.cli directory transfer "C:\Games\RA2" .\new.ini --move
.venv\Scripts\python.exe -m mix_browser.cli directory delete "C:\Games\RA2\old.ini"
.venv\Scripts\python.exe -m mix_browser.cli archive create .\new.mix
.venv\Scripts\python.exe -m mix_browser.cli archive inspect "C:\Games\RA2\ra2.mix"
.venv\Scripts\python.exe -m mix_browser.cli archive extract "C:\Games\RA2\ra2.mix" 305419896 .\extracted.bin
.venv\Scripts\python.exe -m mix_browser.cli archive replace "C:\Games\RA2\ra2.mix" 305419896 .\edited.bin
.venv\Scripts\python.exe -m mix_browser.cli archive add "C:\Games\RA2\ra2.mix" .\new.shp
.venv\Scripts\python.exe -m mix_browser.cli archive edit "C:\Games\RA2\ra2.mix" --rename 305419896=new-name.shp
.venv\Scripts\python.exe -m mix_browser.cli archive edit "C:\Games\RA2\ra2.mix" --remove-entry-id 305419896
.venv\Scripts\python.exe -m mix_browser.cli archive edit "C:\Games\RA2\ra2.mix" --source-archive .\source.mix --copy-entry-id 305419896
.venv\Scripts\python.exe -m mix_browser.cli search "C:\Games\RA2" cameo --max-results 500
.venv\Scripts\python.exe -m mix_browser.cli search "C:\Games\RA2" "^unit.*\.shp$" --regex
.venv\Scripts\python.exe -m mix_browser.cli type .\asset.dat
.venv\Scripts\python.exe -m mix_browser.cli preview .\asset.shp --game-directory "C:\Games\RA2" --output .\asset.png
.venv\Scripts\python.exe -m mix_browser.cli system-integration status
.venv\Scripts\python.exe -m mix_browser.cli system-integration configure --directory-context-menu register --mix-context-menu register --mix-new-menu register --mix-file-association register
.venv\Scripts\python.exe -m mix_browser.cli system-integration configure --container-file-association .mmx=register --container-context-menu .yro=register
```

`archive create` makes a zero-entry standard MIX archive and refuses to overwrite an existing path unless `--overwrite` is supplied. Nested MIX archives use `--parent-entry-id` once per nesting level, from outermost to innermost. IDs accept decimal or `0x`-prefixed hexadecimal. `archive extract` refuses to overwrite an existing output. `archive replace` and `archive add` rewrite the source MIX atomically and reject archive changes detected during the operation. Add commands refuse existing names by default; pass `--overwrite` to replace them. MIX additions update the embedded local name database with the supplied filenames.

`directory create` creates one child folder, and `directory file-create` creates one empty file. `directory rename`, `directory delete`, and `directory transfer` rename, remove, copy, or move filesystem entries; transfers refuse to replace existing items unless `--overwrite` is supplied. `archive edit` deletes entries, renames entries by recalculating their MIX hash IDs, or copies entries from another archive. Use repeated `--parent-entry-id` values to edit nested MIX archives; use `--source-parent-entry-id` to select a nested source archive.

`--game` selects the name list for archive inspection, recursive search, and MIX-entry preview. Supported values are `td`, `ra`, `ts`, and `ra2yr`; the default is `ra2yr`. XCC's bundled lists cover TD, TS, and RA2/YR. RA names are available from the optional CnCNet community database. Regex search uses the Qt `QRegularExpression` syntax and matches case-insensitively against relative paths. Search defaults to 1,000 results; the output's `truncated` field indicates when additional matching results were found. `--no-xcc-names` disables the bundled XCC source. The downloaded community source is disabled by default; after downloading it with `name-source download-community`, pass `--community-names` before a command to enable it, or `--no-community-names` to disable it explicitly.

`preview` accepts either a filesystem file path or a MIX archive path with `--entry-id`. Text results include detected encoding and line endings. Static image results are written as PNG; WAV and Bink data can also be written with `--output`. VXL results provide model and selected-palette metadata because the 3D renderer belongs to the desktop UI. `--frame-index`, `--palette-index`, `--palette-theater`, `--game-directory`, and `--palette-library` select preview inputs. The palette-library JSON file is a list of objects with `path` and optional `asset_pattern` fields.

`system-integration status` reports the current user's Explorer menus and registration state for each supported container extension: `.mix`, `.mmx`, and `.yro`. `system-integration configure` accepts any subset of `--directory-context-menu`, `--mix-context-menu`, `--mix-new-menu`, and `--mix-file-association`, each with `register` or `unregister`. The repeatable `--container-file-association EXTENSION=register|unregister` and `--container-context-menu EXTENSION=register|unregister` options configure handlers and context menus for individual container extensions. These settings only write under the current user's registry hive and require no administrator rights. Registering the MIX New menu adds a valid empty archive template to Explorer's New menu. Windows protects the default-app choice; after registering a handler, choose RA2AYRMB as the default app for the relevant extension in Windows Settings if double-click opening is desired.

Explorer registrations launch the desktop entry point with `--open-path <path>`. Directories and MIX archives open as browser tabs; other files continue to open through their default application.

## MCP

Configure the local MCP client with the project environment's interpreter as `command` and `-m mix_browser.mcp_server` as its argument. Set the project directory as the process working directory. For example:

```text
command: C:\path\to\RA2AYRMB\.venv\Scripts\python.exe
args: ["-m", "mix_browser.mcp_server"]
```

Available tools:

- `download_community_name_database`: download and validate the optional CnCNet community name database into the application directory.
- `list_directory`: list and classify one directory level.
- `add_files_to_directory`: copy local files into a directory, optionally replacing same-named files.
- `create_directory`: create one child directory without replacing an existing item.
- `create_file`: create one empty file without replacing an existing item.
- `rename_directory_entry`: rename one filesystem item without replacing another item.
- `delete_directory_entries`: permanently delete filesystem files or folders by path.
- `transfer_directory_entries`: copy or move files and folders into a directory, optionally replacing same-named items.
- `create_empty_mix_archive`: create a zero-entry standard MIX archive; set `overwrite` to replace an existing path.
- `inspect_mix_archive`: inspect a MIX archive or a nested archive addressed by `parent_entry_ids`; optional `game` selects `td`, `ra`, `ts`, or `ra2yr` name inference.
- `extract_mix_entry`: extract an entry to a new local file without overwriting an existing file.
- `replace_mix_entry`: replace an entry through the existing guarded atomic write-back service.
- `add_files_to_mix_archive`: add local files to a MIX archive or nested MIX, optionally replacing matching entries.
- `edit_mix_entries`: delete, rename, or copy entries in a MIX archive or nested MIX.
- `search_from_root`: search a directory tree or MIX archive, including nested MIX archives; results include relative paths and archive entry IDs. Optional `game` selects the name database for the request.
- `detect_file_type`: detect a file type from its content.
- `preview_entry`: return text, palette data, static PNG image content, WAV audio content, or VXL model metadata. Optional `game` selects name inference for archive entries. PNG and WAV data above 8 MiB are omitted inline; use CLI output or extraction for larger data.
- `get_system_integration_state`: report the current user's Windows Explorer menus and per-extension container handler and context-menu state.
- `configure_system_integration`: register or unregister the directory menu, MIX New menu, or per-extension container handlers and context menus. `container_file_associations` and `container_file_context_menus` accept maps from `.mix`, `.mmx`, or `.yro` to booleans. Windows still requires the user to choose a default app for any extension they want to open by double-clicking.

MCP failures include a stable application error code. The server uses the bundled XCC source by default. The community database is not bundled and is disabled by default; call `download_community_name_database` to download it, then launch the server with `--community-names` to enable it. `--no-xcc-names` and `--no-community-names` explicitly disable their respective sources. Per-call `game` values are scoped to the individual inspection, search, or preview request.

## Capability Boundaries

Directory listing, filesystem file and folder operations, file addition, MIX creation, archive inspection, extraction, replacement, addition and entry editing, recursive search, content-type detection, preview data, and Windows shell registration state/configuration have non-interactive contracts and are exposed through both interfaces. Preview options such as game directory, theater, user palette rules, frame, palette, and encoding are explicit inputs; CLI and MCP do not silently read the desktop window's transient state. Windows default-app selection remains an operating-system UI decision and cannot be set by these interfaces.

Tab navigation, drag-and-drop, hover and pointer gestures, zoom/pan/rotation controls, playback controls, launching a file in the operating system's default GUI application, and modal settings dialogs remain UI interactions. They depend on the desktop event loop, active widget state, or direct user input. Audio preview data is returned to MCP as audio content; Bink video is represented by metadata and can be extracted through `extract_mix_entry`. The `ra2ayrcfre.rules.catalog` package currently defines rule metadata contracts but registers no concrete catalog, so it has no query capability to expose yet.
