# VLC Runtime License Review

This review covers the 29 plugin DLL paths in `tools/vlc_runtime_plugins.txt` and the corresponding VLC 3.0.24 source modules. The runtime is copied from the verified VideoLAN 3.0.24 Windows archive by `tools/copy_vlc_runtime.ps1`.

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
| `text_renderer/libfreetype_plugin.dll` | [`modules/text_renderer/freetype/`](https://code.videolan.org/videolan/vlc/-/tree/3.0.24/modules/text_renderer/freetype) | VLC module sources declare LGPL-2.1-or-later. VLC's FreeType contrib recipe requires a GPL build, so this plugin is part of the GPL-enabled VLC runtime. |
| `video_chroma/libswscale_plugin.dll` | [`modules/video_chroma/swscale.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_chroma/swscale.c) | LGPL-2.1-or-later; links FFmpeg libswscale. The binary archive does not expose the exact FFmpeg build options; the license review considers the VLC contribution rules for this plugin. |
| `video_chroma/libyuvp_plugin.dll` | [`modules/video_chroma/yuvp.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_chroma/yuvp.c) | LGPL-2.1-or-later |
| `video_output/libdirect3d11_plugin.dll` | [`modules/video_output/win32/direct3d11.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/direct3d11.c) | LGPL-2.1-or-later |
| `video_output/libdirect3d9_plugin.dll` | [`modules/video_output/win32/direct3d9.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/direct3d9.c) | LGPL-2.1-or-later |
| `video_output/libdirectdraw_plugin.dll` | [`modules/video_output/win32/directdraw.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/directdraw.c) | LGPL-2.1-or-later |
| `video_output/libdrawable_plugin.dll` | [`modules/video_output/drawable.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/drawable.c) | LGPL-2.1-or-later |
| `video_output/libwingdi_plugin.dll` | [`modules/video_output/win32/wingdi.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/wingdi.c) | LGPL-2.1-or-later |
| `video_output/libwinhibit_plugin.dll` | [`modules/video_output/win32/inhibit.c`](https://code.videolan.org/videolan/vlc/-/blob/3.0.24/modules/video_output/win32/inhibit.c) | LGPL-2.1-or-later |

## Package-Level Findings

- The copied VLC runtime contains the `libsamplerate` and FreeType plugins. VLC 3.0.24's source/build rules therefore identify it as a GPL-enabled build; the archive's `COPYING.txt` is the GPL-2.0 text.
- VLC module headers retain their LGPL-2.1-or-later declarations. The package also includes the upstream `COPYING.LIB` text so the LGPL terms are present alongside the GPL notice.
- VLC's contribution rules specify static FFmpeg 8.1.2 plus zlib 1.3.2, GSM 1.0.13, OpenJPEG 2.5.4, and MinGW-w64 14.0.0 winpthreads for the Windows FFmpeg build. The selected VLC plugins also use libsamplerate 0.1.9 and FreeType 2.14.3; the rules require GPL mode for these dependencies.
- The VLC runtime archive is pinned and hash-verified by `tools/prepare_vlc_runtime.ps1`. The Windows package includes the runtime license texts and this plugin license review.

## Reviewed Build Components

| Component | Version | License notes |
| --- | --- | --- |
| VLC | 3.0.24 | GPL-2.0 for the selected runtime build; VLC source also contains LGPL-2.1-or-later modules. |
| FFmpeg | 8.1.2 | The VLC contribution rules identify the static FFmpeg build and its LGPLv2.1 and GPL license terms. |
| zlib | 1.3.2 | zlib license. |
| GSM | 1.0.13 | VLC's Windows FFmpeg contribution rules identify GSM as a build dependency. |
| OpenJPEG | 2.5.4 | BSD-2-Clause. |
| libsamplerate | 0.1.9 | The library source uses BSD-3-Clause terms; VLC's samplerate plugin declares the linked VLC module GPL-2.0-or-later. |
| FreeType | 2.14.3 | Dual-licensed under the FreeType License and GPL; VLC's contribution rule requires its GPL build mode. |
| MinGW-w64 / winpthreads | 14.0.0 | VLC's Windows FFmpeg contribution rules identify winpthreads; it uses MIT-style terms. |

The review is based on the [VLC 3.0.24 source tree](https://code.videolan.org/videolan/vlc/-/tree/3.0.24), its module license headers, the FFmpeg, zlib, GSM, OpenJPEG, MinGW-w64, libsamplerate, and FreeType contribution rules, and the SHA-256-pinned VideoLAN Windows runtime archive.
