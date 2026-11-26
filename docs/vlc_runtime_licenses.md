# VLC Runtime License Review

This review covers the 28 plugin DLL paths in `tools/vlc_runtime_plugins.txt` and the corresponding VLC 3.0.24 source modules. The runtime is copied from the verified VideoLAN 3.0.24 Windows archive by `tools/copy_vlc_runtime.ps1`.

## Plugin Mapping

| Runtime plugin | VLC 3.0.24 source module | Source license finding |
| --- | --- | --- |
| `access/libimem_plugin.dll` | [`modules/access/imem-access.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/access/imem-access.c) | LGPL-2.1-or-later |
| `access/libaccess_imem_plugin.dll` | [`modules/access/imem.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/access/imem.c) | LGPL-2.1-or-later |
| `audio_filter/libaudio_format_plugin.dll` | [`modules/audio_filter/converter/format.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/audio_filter/converter/format.c) | LGPL-2.1-or-later |
| `audio_filter/libsamplerate_plugin.dll` | [`modules/audio_filter/resampler/src.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/audio_filter/resampler/src.c) | The module source says LGPL-2.1-or-later, and explicitly says linking libsamplerate makes the resulting module subject to GPL-2.0-or-later. VLC's contrib recipe enables libsamplerate only in GPL mode. |
| `audio_filter/libscaletempo_plugin.dll` | [`modules/audio_filter/scaletempo.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/audio_filter/scaletempo.c) | LGPL-2.1-or-later |
| `audio_filter/libtrivial_channel_mixer_plugin.dll` | [`modules/audio_filter/channel_mixer/trivial.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/audio_filter/channel_mixer/trivial.c) | LGPL-2.1-or-later |
| `audio_mixer/libfloat_mixer_plugin.dll` | [`modules/audio_mixer/float.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/audio_mixer/float.c) | LGPL-2.1-or-later |
| `audio_output/libdirectsound_plugin.dll` | [`modules/audio_output/directsound.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/audio_output/directsound.c) | LGPL-2.1-or-later |
| `audio_output/libmmdevice_plugin.dll` | [`modules/audio_output/mmdevice.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/audio_output/mmdevice.c) | LGPL-2.1-or-later |
| `audio_output/libwasapi_plugin.dll` | [`modules/audio_output/wasapi.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/audio_output/wasapi.c) | LGPL-2.1-or-later |
| `audio_output/libwaveout_plugin.dll` | [`modules/audio_output/waveout.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/audio_output/waveout.c) | LGPL-2.1-or-later |
| `codec/libavcodec_plugin.dll` | [`modules/codec/avcodec/`](https://code.videolan.org/videolan/vlc/-/tree/3.0.24/modules/codec/avcodec) | VLC module sources declare LGPL-2.1-or-later and use the FFmpeg version and dependencies specified by the VLC 3.0.24 contribution rules. |
| `codec/libadpcm_plugin.dll` | [`modules/codec/adpcm.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/codec/adpcm.c) | LGPL-2.1-or-later |
| `codec/libaraw_plugin.dll` | [`modules/codec/araw.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/codec/araw.c) | LGPL-2.1-or-later |
| `demux/libwav_plugin.dll` | [`modules/demux/wav.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/demux/wav.c) | LGPL-2.1-or-later |
| `d3d11/libdirect3d11_filters_plugin.dll` | [`modules/hw/d3d11/d3d11_filters.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/hw/d3d11/d3d11_filters.c) | LGPL-2.1-or-later |
| `keystore/libmemory_keystore_plugin.dll` | [`modules/keystore/memory.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/keystore/memory.c) | LGPL-2.1-or-later |
| `logger/libconsole_logger_plugin.dll` | [`modules/logger/console.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/logger/console.c) | LGPL-2.1-or-later |
| `stream_filter/libprefetch_plugin.dll` | [`modules/stream_filter/prefetch.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/stream_filter/prefetch.c) | LGPL-2.1-or-later |
| `stream_filter/librecord_plugin.dll` | [`modules/stream_filter/record.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/stream_filter/record.c) | LGPL-2.1-or-later |
| `video_chroma/libswscale_plugin.dll` | [`modules/video_chroma/swscale.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_chroma/swscale.c) | LGPL-2.1-or-later; links FFmpeg libswscale. The binary archive does not expose the exact FFmpeg build options; the license review considers the VLC contribution rules for this plugin. |
| `video_chroma/libyuvp_plugin.dll` | [`modules/video_chroma/yuvp.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_chroma/yuvp.c) | LGPL-2.1-or-later |
| `video_output/libdirect3d11_plugin.dll` | [`modules/video_output/win32/direct3d11.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/direct3d11.c) | LGPL-2.1-or-later |
| `video_output/libdirect3d9_plugin.dll` | [`modules/video_output/win32/direct3d9.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/direct3d9.c) | LGPL-2.1-or-later |
| `video_output/libdirectdraw_plugin.dll` | [`modules/video_output/win32/directdraw.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/directdraw.c) | LGPL-2.1-or-later |
| `video_output/libdrawable_plugin.dll` | [`modules/video_output/drawable.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/drawable.c) | LGPL-2.1-or-later |
| `video_output/libwingdi_plugin.dll` | [`modules/video_output/win32/wingdi.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/wingdi.c) | LGPL-2.1-or-later |
| `video_output/libwinhibit_plugin.dll` | [`modules/video_output/win32/inhibit.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/inhibit.c) | LGPL-2.1-or-later |

## Package-Level Findings

- The packaged VLC runtime contains the `libsamplerate` plugin and excludes `libfreetype_plugin.dll`. VLC 3.0.24's source/build rules identify the retained samplerate plugin as GPL-2.0-or-later; `COPYING.txt` supplies the GPL-2.0 license text.
- VLC module headers retain their LGPL-2.1-or-later declarations. The package also includes the upstream `COPYING.LIB` text so the LGPL terms are present alongside the GPL notice.
- VLC's contribution rules specify static FFmpeg 8.1.2 plus zlib 1.3.2, GSM 1.0.13, OpenJPEG 2.5.4, and MinGW-w64 14.0.0 winpthreads for the Windows FFmpeg build. The selected VLC plugins also use libsamplerate 0.1.9. FreeType 2.14.3 is not a VLC runtime dependency in this package.
- VLC 3.0.24's `contrib/src/ffmpeg/rules.mak` pins FFmpeg to commit `71fb6132637a2a430375c24afc381fff8b854fe7` and applies the patches in `contrib/src/ffmpeg/`. A corresponding-source response must include that revision and patch set, not only the generic FFmpeg 8.1.2 release archive.
- The VLC runtime archive is pinned and hash-verified by `tools/prepare_vlc_runtime.ps1`. The Windows package includes the runtime license texts and this plugin license review.

## Corresponding Source

The corresponding VLC 3.0.24 source is based on the versioned [VideoLAN source tree](https://code.videolan.org/videolan/vlc/-/tree/3.0.24) and the dependency versions recorded below. This review maps each selected plugin to its upstream module and is included in the binary package as `licenses/VLC/PLUGIN_LICENSES.md`.

Each Windows executable package built from this revision includes `licenses/VLC/SOURCE_CODE_OFFER.txt`. The offer covers the GPL-enabled VLC runtime and its incorporated dependencies. Their source is a separate asset in the v1.2.1 release at [RA2AYRMB-vlc-source-3.0.24.7z](https://github.com/KAINEYLBS/Red-Alert-2-and-Yuri-s-Revenge-MIX-Browser/releases/download/v1.2.1/RA2AYRMB-vlc-source-3.0.24.7z). The archive includes the VLC 3.0.24 source tree, source archives for the dependencies used by the selected runtime plugins, and the build rules and patches maintained in the VLC source tree. Keep the linked asset available for at least three years after distributing each executable package containing this offer. If the asset is unavailable, recipients can request a free copy through the project's public GitHub issue tracker. A later release may continue to point to this source asset while the bundled VLC components and their build inputs remain unchanged.

## Reviewed Build Components

| Component | Version | License notes |
| --- | --- | --- |
| VLC | 3.0.24 | GPL-2.0-or-later for the selected runtime build; VLC source also contains LGPL-2.1-or-later modules. |
| FFmpeg | 8.1.2 | The VLC contribution rules identify the static FFmpeg build and its LGPLv2.1 and GPL license terms. |
| zlib | 1.3.2 | zlib license. |
| GSM | 1.0.13 | VLC's Windows FFmpeg contribution rules identify GSM as a build dependency. |
| OpenJPEG | 2.5.4 | BSD-2-Clause. |
| libsamplerate | 0.1.9 | The library source uses BSD-3-Clause terms; VLC's samplerate plugin declares the linked VLC module GPL-2.0-or-later. |
| MinGW-w64 / winpthreads | 14.0.0 | VLC's Windows FFmpeg contribution rules identify winpthreads; it uses MIT-style terms. |

The review is based on the [VLC 3.0.24 source tree](https://code.videolan.org/videolan/vlc/-/tree/3.0.24), its module license headers, the FFmpeg, zlib, GSM, OpenJPEG, MinGW-w64, and libsamplerate contribution rules, and the SHA-256-pinned VideoLAN Windows runtime archive. The final package audit checks that the excluded FreeType plugin is absent.
