# RA2AYRMB

**Red Alert 2 and Yuri's Revenge MIX Browser** is a desktop application for browsing and managing Westwood MIX archives alongside ordinary game files and folders.

Version: **1.1.0**

README: English | [简体中文](README.zh-CN.md)  
Interface languages: English and Simplified Chinese

## Features

- Browse folders, MIX archives, and nested MIX archives.
- Create and save MIX archives; add, extract, replace, copy, rename, and delete entries.
- Search recursively from a folder or archive root, with regular-expression matching and relative-path results.
- Preview supported text, image, animation, model, palette, name-database, audio, and video formats.
- Use the bundled XCC name list and optionally download the CnCNet community MIX name database.
- Choose palettes automatically from archive contents, INI rules, user-defined rules, and an optional RA2/YR game directory.
- Use the desktop interface, JSON CLI, or local stdio MCP server.
- Optionally register Windows Explorer context-menu commands and file handlers for `.mix`, `.mmx`, and `.yro` containers for the current user.

## Preview Support

The desktop app's **Help > Preview Support...** dialog lists these formats and limits:

| Category | Formats |
| --- | --- |
| Text documents | `.bat`, `.cfg`, `.csv`, `.glsl`, `.htm`, `.html`, `.ini`, `.json`, `.lcf`, `.log`, `.map`, `.md`, `.mpr`, `.txt`, `.xml`, `.yrm` |
| SHP animations | `.shp`, `.shp-ts` |
| PCX images | `.pcx`, `.mmp`* |
| Palettes | `.pal` |
| Voxel models | `.vxl`, `.hva` |
| XCC name data | `.dat` |
| Audio | `.wav` |
| Video | `.bik`, `.bk2`, `.bink` |
| Browsable MIX containers | `.mix`, `.mmx`, `.yro` |

`*` An `.mmp` file is previewed as PCX only when its contents have a valid PCX signature. `.dat` preview is limited to recognized XCC MIX name databases. PAL previews accept Westwood raw, JASC, and RIFF palettes. Selecting a VXL previews its static geometry. Selecting an HVA previews the same-name VXL with the HVA poses from the same MIX or folder; HVA frames can be selected manually. An HVA without a valid pair cannot be previewed. Directories and MIX containers are browsed rather than previewed as documents.

Preview limits: text entries are truncated at 2 MiB; DAT entries larger than 64 MiB are not previewed; SHP and PCX images are limited to 33,554,432 decoded pixels; SHP, PCX, and VXL entries larger than 64 MiB are not previewed; HVA entries larger than 16 MiB or with more than 1,024 frames are not applied; WAV and Bink entries larger than 128 MiB are not previewed.

### VLC Playback Startup on Windows

Audio and video previews use VLC. First playback may take longer while VLC initializes the media pipeline. Windows Defender real-time protection may scan VLC runtime files on first access; during a scan, the application can appear temporarily unresponsive. NVIDIA Instant Replay may also monitor VLC playback and cause a similar delay, usually less noticeably. These are possible system-side contributors, not a confirmed explanation for every delay; startup delays are typically most noticeable on first use.

Game files are not included. Select an existing RA2/YR game directory in **Edit > Preferences > Palette Sources** to use its palettes and art rules for previews. The game directory is stored as a setting; its contents are read in place.

## User Data

The portable `user-data` folder beside the executable contains user-specific application data:

- `RA2AYRMB.ini`: preferences and startup choices.
- `user-palettes/`: imported PAL files and custom palette rules.
- `name-sources/community/`: the optional downloaded community database.
- `system-integration/default-app-samples/`: persistent samples used by Windows default-app selection.
- `cache/palette-catalog/`: generated palette and art-rule cache for the configured game directory; it can be deleted and rebuilt.

The application reads user data only from `user-data/`; it does not automatically import files from the executable folder. To migrate from version 1.0.0 beta 1 or earlier, before the first launch copy these items from beside the old executable to beside the new executable:

- `RA2AYRMB.ini` to `user-data/RA2AYRMB.ini`.
- `user-palettes/` to `user-data/user-palettes/`.
- `name-sources/` to `user-data/name-sources/`.
- `system-integration/` to `user-data/system-integration/`.

For later updates, copy the entire `user-data/` folder beside the new executable. Windows Explorer registrations are stored separately in the current user's registry; re-register them in **Preferences > System Integration** if the executable's location changes.

If the in-app community database download fails, click the hyperlink next to the download button to get `global_mix_database.dat.zip`. Copy it to `user-data/name-sources/community/global_mix_database.dat.zip` beside the executable, creating the folders if needed, then restart RA2AYRMB.

## Run From Source

Requirements: Python 3.10 or newer. Supported Windows desktop builds require Windows 10 or later. On Windows, create the project environment and install the application:

```powershell
py -3.10 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .
```

Launch the desktop application with:

```powershell
run.bat
```

## Build for Windows

If `.runtime\vlc` is still missing, prepare the VLC runtime once:

```powershell
tools\prepare_vlc_runtime.bat
```

Then install PyInstaller into the project environment and run the packaging script:

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
package.bat
```

The onedir build is created at `dist/RA2AYRMB/RA2AYRMB.exe`. Settings, imported palettes, and the optional community database are stored under `dist/RA2AYRMB/user-data/`.

## CLI

The CLI writes structured JSON for successful operations and stable error objects to stderr. See [CLI and MCP documentation](docs/cli_mcp.md) for the complete command reference.

```powershell
.venv\Scripts\python.exe -m mix_browser.cli --help
.venv\Scripts\python.exe -m mix_browser.cli archive inspect "C:\Games\RA2\ra2.mix"
.venv\Scripts\python.exe -m mix_browser.cli search "C:\Games\RA2" "^unit.*\.shp$" --regex
.venv\Scripts\python.exe -m mix_browser.cli preview .\asset.shp --game-directory "C:\Games\RA2" --output .\asset.png
.venv\Scripts\python.exe -m mix_browser.cli name-source download-community
```

## MCP

RA2AYRMB provides an MCP server over local stdio; it does not open a network listener. Configure your MCP client to launch:

```text
Command: C:\path\to\RA2AYRMB\.venv\Scripts\python.exe
Arguments: -m mix_browser.mcp_server
Working directory: C:\path\to\RA2AYRMB
```

See [CLI and MCP documentation](docs/cli_mcp.md) for the available tools and client setup details.

## Documentation

- [CLI and MCP reference](docs/cli_mcp.md)
- [Preview and palette-selection behavior](docs/mix_browser_previews.md)
- [MIX name data sources](docs/mix_name_data_sources.md)
- [Licensing details](docs/licensing.md)

## Licensing

Project-authored source code, documentation, and original assets (including the hand-drawn `MIX-EXE.ico`, `MIX-FILE.ico`, `MMX-FILE.ico`, and `YRO-FILE.ico` icons) are licensed under the [MIT License](LICENSE). This license does not automatically cover separately sourced datasets, game files, Qt/PySide, `python-vlc`, libVLC, FFmpeg, or their codecs. Binary-package notices are described in [third-party notices](THIRD_PARTY_NOTICES.md).

The bundled XCC MIX name lists for Tiberian Dawn, Tiberian Sun, and Red Alert 2/Yuri's Revenge are identified as GPL-3.0 and include the accompanying license text. The optional CnCNet community Global MIX Database is downloaded on request from its original forum attachment and is not bundled with the repository or application releases. It also supplies the Red Alert name list. The project MIT license applies to project-authored material and does not relicense separately sourced data. See [licensing details](docs/licensing.md) and [third-party notices](THIRD_PARTY_NOTICES.md) for more information.
