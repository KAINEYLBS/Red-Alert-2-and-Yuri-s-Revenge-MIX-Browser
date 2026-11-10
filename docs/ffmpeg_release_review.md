# FFmpeg Binary Release Review

This document is a historical review of the FFmpeg runtime included by the PySide6 Qt Multimedia backend in an earlier build. WAV and video preview now use the VLC runtime, so this record does not describe the current playback runtime or its codec plugins. It remains a reference for the exact older Qt Multimedia build; `package.bat` does not download or check these FFmpeg source archives.

## Reviewed Build

The current record covers the Windows PySide6 6.11.1 / Qt Multimedia 6.11.1.0 payload. The installed DLLs report FFmpeg 7.1.3, with these file versions: avcodec 61.19.101, avformat 61.7.100, avutil 59.39.100, swresample 5.3.100, and swscale 8.3.100.

The `avcodec-61.dll` exports report `LGPL version 2.1 or later`. Its build configuration identifies the `n7.1.3` MSVC build, uses shared libraries (`--enable-shared --disable-static`), enables zlib 1.3.1, and contains no `--enable-gpl` or `--enable-nonfree` option. The FFmpeg DLL import table has no separate zlib DLL, so zlib is statically included. This supports the LGPL route for this exact build. Qt's current backend documentation explains dynamic linking and the feature licensing policy, but now describes FFmpeg 9.0.1; the installed DLL exports and version resources were used for this PySide6 wheel's version and configuration.

The reviewed sources are the upstream FFmpeg `n7.1.3` tag archive at `https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/refs/tags/n7.1.3` and zlib 1.3.1 at `https://zlib.net/fossils/zlib-1.3.1.tar.gz`. Their SHA-256 values and the hashes of `COPYING.LGPLv2.1` and zlib's `LICENSE` are recorded in `ffmpeg-release-review.json`. The full DLL hashes are also in that record. These source archives are not downloaded as part of source export or ordinary packaging.

This review covers copyright licensing and the source materials for this FFmpeg build. FFmpeg's copyright license does not grant patent rights that may apply to particular codec implementations.

## Review a Changed Build

1. Print the FFmpeg-related DLL hashes from the build environment:

   ```bat
   .venv\Scripts\python.exe tools\ffmpeg_release_audit.py report .venv\Lib\site-packages\PySide6
   ```

2. Inspect the exact FFmpeg DLL metadata and exported license/configuration for the new build. Confirm the Qt Multimedia plugin and codec configuration, including whether GPL or nonfree features are enabled.
3. Identify the corresponding source archives and license files for that build and its linked dependencies. Verify their origin and SHA-256, then update `source_archives` in `ffmpeg-release-review.json`.
4. Update the review date, runtime version, sources, review flags, notes, and the complete `binaries_sha256` mapping from the report. Do not approve a build whose source or license material is unavailable.
5. For a binary release, separately verify that its exact FFmpeg build and source materials satisfy the applicable redistribution obligations. `package.bat` builds the application but does not perform this review or collect FFmpeg source archives.

Any FFmpeg-related DLL change requires a new review. The audit tool confirms that files match the reviewed hashes; it cannot decide the legal interpretation or determine patent obligations.
