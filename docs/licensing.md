# Licensing

## Project License

Original RA2AYRMB source code, project-authored documentation, and hand-drawn icons by KAINEYLB小卡 are licensed under the [MIT License](../LICENSE). This includes `mix_browser/data/icons/MIX-EXE.ico`, `MIX-FILE.ico`, `MMX-FILE.ico`, and `YRO-FILE.ico`. You may use, modify, distribute, sublicense, and sell those materials, provided copies or substantial portions retain the copyright and permission notices in `LICENSE`.

## Excluded Materials

The project license does not replace licenses or permissions that apply to separately sourced material:

- The bundled XCC TD, TS, and RA2/YR name lists under `mix_browser/data/name_sources/xcc/` are identified as GPL-3.0 in [MIX name data sources](mix_name_data_sources.md), with the license text in the adjacent `COPYING` file.
- The GitHub mark at `mix_browser/data/icons/github.svg` comes from [Simple Icons](https://github.com/simple-icons/simple-icons/blob/develop/icons/github.svg) and is available under [CC0 1.0](https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md). It is used only as the icon for the project link in About.
- The `mcp` Python SDK is an MIT-licensed direct dependency. `pycryptodomex`, used for encrypted MIX support, contains BSD-2-Clause and public-domain portions. The dependency sources and binary-package handling are listed in the root [third-party notices](../THIRD_PARTY_NOTICES.md).
- Palette-rule documentation cites Ares and ModEnc technical references. It contains project-authored explanations and links to those references; no Ares-derived metadata files or offline copies of the referenced sites are included. ModEnc attribution and source links are recorded in the [third-party notices](../THIRD_PARTY_NOTICES.md) and [preview documentation](mix_browser_previews.md).
- The optional CnCNet community database is downloaded from its original forum attachment into the user's application directory and is not bundled with releases. The cited post and attachment state no separate license. The project license does not grant permission to redistribute or modify that database; its redistribution permission remains unconfirmed.
- The Windows package includes the CPython runtime selected by the packaging environment. `package.bat` copies that base installation's `LICENSE.txt` into the application's `licenses/Python/` directory.
- PySide6 Essentials, shiboken6, Qt, `python-vlc`, libVLC, and their codecs, plugins, and binaries retain their own licenses. The application package uses Qt's LGPL-3.0-only distribution option; Qt's alternative commercial terms are not used. The package places the project MIT license and third-party notices in the visible `licenses` directory, and includes the selected Qt LGPL text at `licenses/Qt/LGPL-3.0-only.txt`. The Windows package includes the python-vlc `COPYING` file under `licenses/python-vlc/`. The open-source export does not bundle the Python environment or VLC runtime. `tools/prepare_vlc_runtime.bat` downloads and checksum-verifies the VLC 3.0.24 runtime once. The package includes VLC's GPL `COPYING.txt`, LGPL `COPYING.LIB`, and the plugin license review in [VLC runtime license review](vlc_runtime_licenses.md).
- Game files, archives, and other user-provided assets are not relicensed by this project.

Where a file has its own license or source notice, that notice takes precedence for that material. Inclusion in a source distribution or application package does not make excluded material subject to the project license.

## Copyright Notice

The MIT notice identifies KAINEYLB小卡 as the copyright holder for project-authored materials. Separately sourced materials retain their own copyright and license terms as described above.
