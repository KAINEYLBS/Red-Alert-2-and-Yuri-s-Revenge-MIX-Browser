# Third-Party Notices

This notice covers third-party material included with or directly used by RA2AYRMB. Project-authored source code and assets remain under the root [MIT License](LICENSE); that license does not replace the terms listed here.

## Bundled Data and Assets

- The XCC Tiberian Dawn, Tiberian Sun, and Red Alert 2/Yuri's Revenge MIX name lists in `mix_browser/data/name_sources/xcc/` are identified as GPL-3.0. Their license text is included as `mix_browser/data/name_sources/xcc/COPYING` and in Python package license metadata. The project MIT license does not cover these lists.
- `mix_browser/data/icons/github.svg` is the GitHub mark from Simple Icons, available under CC0 1.0. The hand-drawn `MIX-EXE.ico`, `MIX-FILE.ico`, `MMX-FILE.ico`, and `YRO-FILE.ico` icons are project-authored assets.
- `mix_browser/data/icons/square-pen.svg` is the Square Pen icon from Lucide Icons (lucide-static v1.77.0), available under ISC. Its license text is included in `docs/licenses/Lucide/ISC.txt` and the Windows application license bundle. Source: [Lucide Square Pen](https://lucide.dev/icons/square-pen).
- The optional CnCNet Global MIX Database is downloaded on request from its original forum attachment and is not included in the repository or application release package. Its download location and use are described in [MIX name data sources](docs/mix_name_data_sources.md).
- `tools/pyinstaller_hooks/hook-setuptools._vendor.jaraco.text.py` adapts the corresponding PyInstaller hook to omit an unused sample file from the application package. It retains PyInstaller's GPL-2.0-or-later-with-bootloader-exception license notice, with the license text in `docs/licenses/PyInstaller/COPYING.txt`.

## Technical References

- The palette guide cites Ares documentation for palette behavior. It contains project-authored descriptions and links to the references; no Ares-derived metadata files are included.
- The guide cites ModEnc pages for game rules. ModEnc's [copyright policy](https://modenc.renegadeprojects.com/ModEnc:Copyrights) says its information may be reused as public domain and asks that reuse be attributed. The related pages are linked where those rules are described; no page captures or offline site copy are included.
- The SHP and VXL parsers were implemented for this project. OpenRA readers are cited as binary-layout references only; no OpenRA code or game assets are included. See [preview references](docs/mix_browser_previews.md).

## Direct Dependencies

| Component | Use | License and source |
| --- | --- | --- |
| CPython runtime | Python runtime included by the Windows application build | The reviewed Windows package uses CPython 3.14.7. The package copies `LICENSE.txt` from the base Python installation selected by `.venv` into `licenses/Python/`. Source: [Python license](https://docs.python.org/3/license.html). |
| OpenSSL | Hash and HTTPS backends loaded by CPython | The reviewed Windows package uses OpenSSL 3.5.7 through CPython's `_hashlib` and `_ssl` extensions. The app uses HTTPS when the user requests the optional CnCNet community database download. OpenSSL 3.x is Apache-2.0; the package includes `licenses/OpenSSL/LICENSE.txt`. Source: [OpenSSL 3.5.7](https://github.com/openssl/openssl/tree/openssl-3.5.7). |
| PySide6 Essentials 6.11.1, shiboken6 6.11.1, and Qt 6.11.1 | Desktop UI, image, and OpenGL APIs | This application package uses Qt's LGPL-3.0-only distribution option. Qt's alternative commercial terms are not used. The binary package includes `licenses/Qt/LGPL-3.0-only.txt`. See the [Qt for Python license overview](https://doc.qt.io/qtforpython-6/licenses.html). |
| `python-vlc` 3.0.21203 | Python bindings for libVLC | LGPL-2.1-or-later. The Windows package includes the dependency's `COPYING` file under `licenses/python-vlc/`. Source: [python-vlc](https://github.com/oaubert/python-vlc). |
| VLC 3.0.24 Windows runtime | WAV audio and Bink video playback through libVLC | The prepared archive supplies libVLC and the 29 plugins listed in `tools/vlc_runtime_plugins.txt`. Their source-module mapping and license findings are recorded in [VLC runtime license review](docs/vlc_runtime_licenses.md). The binary package includes VLC's GPL `COPYING.txt`, LGPL `COPYING.LIB`, and the plugin license review. VLC's selected `libsamplerate` and FreeType plugins require the GPL build. See [VideoLAN downloads](https://get.videolan.org/vlc/3.0.24/win64/) and the [VLC 3.0.24 source](https://code.videolan.org/videolan/vlc/-/tree/3.0.24). |
| pycryptodomex 3.23.0 | Blowfish support for encrypted MIX archives | BSD-2-Clause and public-domain portions. The package's `LICENSE.rst` is copied from the build environment into the Windows application distribution. Source: [PyCryptodome](https://github.com/Legrandin/pycryptodome/). |
| MCP Python SDK (`mcp`) | CLI/MCP server implementation | MIT. It is installed as a Python dependency and is not bundled by the desktop-only `package.bat` build. Source: [Python SDK](https://github.com/modelcontextprotocol/python-sdk). |
| PyInstaller 6.20.0 | Windows executable build tool | The PyInstaller package is a build-time dependency, but its bootloader and run-time hooks are embedded in the generated executable. The bootloader is GPL-2.0-or-later with the bootloader exception; run-time hooks are Apache-2.0. The binary package includes the exact build environment's `COPYING.txt` under `licenses/PyInstaller/`. Source: [PyInstaller](https://github.com/pyinstaller/pyinstaller). |

## Windows Package Components

| Component | Version observed | License and package notice |
| --- | --- | --- |
| Qt software OpenGL renderer (`opengl32sw.dll`) | PySide6/Qt 6.11.1; Mesa 11.2.2; LLVM 3.6.2 | Qt's 6.11 attribution identifies this DLL as Mesa llvmpipe and lists MIT, Khronos, and Boost Software License 1.0 texts. The DLL also contains LLVM 3.6.2 compiler, IR, and llvmpipe JIT markers. The package includes those Mesa notices and LLVM's University of Illinois/NCSA license under `licenses/Mesa/` and `licenses/LLVM/`. Sources: [Qt 6.11 component inventory](https://doc.qt.io/qt-6.11/licenses-used-in-qt.html), [Mesa llvmpipe attribution](https://doc.qt.io/qt-6.11/qt-attribution-llvmpipe.html), and [LLVM 3.6 release license](https://github.com/llvm-mirror/llvm/blob/release_36/LICENSE.TXT). |
| OpenSSL runtime (`libcrypto-3.dll`, `libssl-3.dll`) | OpenSSL 3.5.7 | Used through CPython for archive checksums and the optional CnCNet database download over HTTPS. The package includes Apache-2.0 at `licenses/OpenSSL/LICENSE.txt`. Source: [OpenSSL 3.5.7](https://github.com/openssl/openssl/tree/openssl-3.5.7). |
| PyInstaller bootloader and run-time hooks | PyInstaller 6.20.0 | Embedded in `RA2AYRMB.exe`; the package includes the exact PyInstaller distribution's `COPYING.txt` at `licenses/PyInstaller/COPYING.txt`, including the bootloader exception and run-time hook license. |
| CFFI and pycparser | CFFI 2.1.1; pycparser 3.12 | Both modules are present in the reviewed Windows executable. CFFI is MIT-0 and pycparser is BSD-3-Clause. `package.bat` copies their license texts to `licenses/CFFI/` and `licenses/pycparser/`. Sources: [CFFI](https://github.com/python-cffi/cffi) and [pycparser](https://github.com/eliben/pycparser). |

The application license and third-party notices are placed in the visible `licenses` directory beside the executable. `package.bat` collects the Python runtime, PyInstaller, pycryptodomex, and python-vlc license files from the resolved build environment, and copies the maintained OpenSSL, Mesa, LLVM, CFFI, and pycparser license texts from `docs/licenses/`. The open-source export does not include a Python environment or VLC binaries. `tools/prepare_vlc_runtime.bat` downloads and verifies the VLC runtime once; `package.bat` copies the cached runtime and license notices without downloading it again. The active VLC plugin and dependency review is documented in [VLC runtime license review](docs/vlc_runtime_licenses.md).
