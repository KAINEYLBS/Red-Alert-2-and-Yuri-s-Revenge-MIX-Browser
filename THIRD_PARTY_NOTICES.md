# Third-Party Notices

This notice covers third-party material included with or directly used by RA2AYRMB. Project-authored source code and assets remain under the root [MIT License](LICENSE); that license does not replace the terms listed here.

## Bundled Data and Assets

- The XCC Tiberian Dawn, Tiberian Sun, and Red Alert 2/Yuri's Revenge MIX name lists in `mix_browser/data/name_sources/xcc/` are identified as GPL-3.0. Their license text is included as `mix_browser/data/name_sources/xcc/COPYING` and in Python package license metadata. The project MIT license does not cover these lists.
- `mix_browser/data/icons/github.svg` is the GitHub mark from Simple Icons, available under CC0 1.0. The hand-drawn `MIX-EXE.ico`, `MIX-FILE.ico`, `MMX-FILE.ico`, and `YRO-FILE.ico` icons are project-authored assets.
- The optional CnCNet Global MIX Database is not included. Users may request it from the original forum attachment; the source does not state a separate license, so redistribution permission remains unconfirmed. See [MIX name data sources](docs/mix_name_data_sources.md).

## Technical References

- The palette guide cites Ares documentation for palette behavior. It contains project-authored descriptions and links to the references; no Ares-derived metadata files are included.
- The guide cites ModEnc pages for game rules. ModEnc's [copyright policy](https://modenc.renegadeprojects.com/ModEnc:Copyrights) says its information may be reused as public domain and asks that reuse be attributed. The related pages are linked where those rules are described; no page captures or offline site copy are included.
- The SHP and VXL parsers were implemented for this project. OpenRA readers are cited as binary-layout references only; no OpenRA code or game assets are included. See [preview references](docs/mix_browser_previews.md).

## Direct Dependencies

| Component | Use | License and source |
| --- | --- | --- |
| CPython runtime | Python runtime included by the Windows application build | The package copies `LICENSE.txt` from the base Python installation selected by `.venv` into `licenses/Python/`. The exact Python version follows the packaging environment. Source: [Python license](https://docs.python.org/3/license.html). |
| PySide6 Essentials, shiboken6, and Qt | Desktop UI, image, and OpenGL APIs | This application package uses Qt's LGPL-3.0-only distribution option. Qt's alternative commercial terms are not used. The binary package includes `licenses/Qt/LGPL-3.0-only.txt`. See the [Qt for Python license overview](https://doc.qt.io/qtforpython-6/licenses.html). |
| `python-vlc` | Python bindings for libVLC | LGPL-2.1-or-later. The Windows package includes the dependency's `COPYING` file under `licenses/python-vlc/`. Source: [python-vlc](https://github.com/oaubert/python-vlc). |
| VLC 3.0.24 Windows runtime | WAV audio and Bink video playback through libVLC | The prepared archive supplies libVLC and the 29 plugins listed in `tools/vlc_runtime_plugins.txt`. Their source-module mapping and license findings are recorded in [VLC runtime license review](docs/vlc_runtime_licenses.md). The binary package includes VLC's GPL `COPYING.txt`, LGPL `COPYING.LIB`, and the plugin license review. VLC's selected `libsamplerate` and FreeType plugins require the GPL build. See [VideoLAN downloads](https://get.videolan.org/vlc/3.0.24/win64/) and the [VLC 3.0.24 source](https://code.videolan.org/videolan/vlc/-/tree/3.0.24). |
| pycryptodomex | Blowfish support for encrypted MIX archives | BSD-2-Clause and public-domain portions. The package's `LICENSE.rst` is copied from the build environment into the Windows application distribution. Source: [PyCryptodome](https://github.com/Legrandin/pycryptodome/). |
| MCP Python SDK (`mcp`) | CLI/MCP server implementation | MIT. It is installed as a Python dependency and is not bundled by the desktop-only `package.bat` build. Source: [Python SDK](https://github.com/modelcontextprotocol/python-sdk). |
| PyInstaller | Build tool only | Used to create the Windows application directory; it is not included in the application runtime distribution. |

The application license and third-party notices are placed in the visible `licenses` directory beside the executable. `package.bat` also collects the Python runtime, pycryptodomex, and python-vlc license files from the resolved build environment. The open-source export does not include a Python environment or VLC binaries. `tools/prepare_vlc_runtime.bat` downloads and verifies the VLC runtime once; `package.bat` copies the cached runtime and license notices without downloading it again. The active VLC plugin and dependency review is documented in [VLC runtime license review](docs/vlc_runtime_licenses.md).
