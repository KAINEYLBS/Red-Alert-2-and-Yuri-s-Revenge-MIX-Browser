# Qt 6.11.1 Third-Party Notices

The Windows package contains PySide6 6.11.1, shiboken6 6.11.1, and Qt 6.11.1 under the LGPL-3.0-only distribution option. It includes the full LGPL text at `licenses/Qt/LGPL-3.0-only.txt`; the Qt DLLs and plugins remain separate files under `_internal/PySide6` and can be replaced with compatible builds.

The shipped Qt components include QtCore, QtGui, QtNetwork, QtOpenGL, QtOpenGLWidgets, QtSvg, and QtWidgets, plus the Windows, ICO, and modern Windows style plugins. Their Qt 6.11.1 source tag and `qt_attribution.json` files are at [qtbase v6.11.1](https://code.qt.io/cgit/qt/qtbase.git/tree/?h=v6.11.1). PySide and shiboken sources are at [pyside-setup 6.11.1](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=6.11.1). Qt for Python's attribution catalogue is at [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html).

These third-party components are used by the shipped Qt modules:

| Qt component | Third-party code | License |
| --- | --- | --- |
| QtCore | double-conversion 3.4.0 | BSD-3-Clause |
| QtCore | PCRE2 10.47 and SLJIT | BSD-3-Clause with Qt's binary-like package exception; BSD-2-Clause |
| QtCore | zlib 1.3.2; BLAKE2; MD4; MD5; SHA-1; SHA-2; SHA-3; SipHash; tinycbor 7.0; easing equations | Zlib; CC0-1.0 or Apache-2.0; public domain; BSD-3-Clause; BSD-2-Clause; MIT |
| QtGui | FreeType 2.14.3 and its BDF, PCF, and zlib portions | FreeType Project License; MIT; MIT and MIT Open Group; Zlib |
| QtGui | HarfBuzz-NG 14.2.0; sRGB ICC profile; libjpeg-turbo 3.1.4; libpng 1.6.58; emoji-segmenter 0.4.0 | MIT; ICC License; IJG and BSD-3-Clause; Libpng and libpng-2.0; Apache-2.0 |
| QtNetwork | libpsl and Public Suffix List data | BSD-3-Clause; Mozilla Public License 2.0 |

FreeType is dual-licensed upstream as `FTL OR GPL-2.0-only`. The Qt 6.11.1 LGPL distribution uses the FreeType Project License option. The separate VLC FreeType text-renderer plugin, whose VLC build recipe requires GPL mode and whose FreeType dependency permits GPL-2.0-only, is excluded from this application package. The retained VLC GPL component is the samplerate plugin, whose VLC source explicitly permits GPL-2.0-or-later; this is compatible with the application's GPL-3.0 distribution option.

The matching license texts are included in this directory. Mesa and LLVM notices for `opengl32sw.dll` are in `licenses/Mesa/` and `licenses/LLVM/`. The Qt commercial license metadata is not used.
