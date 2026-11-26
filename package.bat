@echo off
setlocal
set "EXIT_CODE=0"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
cd /d "%~dp0"
if errorlevel 1 (
    call :write_status Red "Could not change to the project directory: %~dp0"
    set "EXIT_CODE=1"
    goto :finish
)

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    call :write_status Red "The project Python environment was not found at %PYTHON%."
    call :write_status Red "Create the environment using README instructions, or run the local link helper from your separate source checkout."
    set "EXIT_CODE=1"
    goto :finish
)

set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%~dp0.venv\Scripts"
if not exist "%POWERSHELL%" (
    call :write_status Red "Windows PowerShell was not found at %POWERSHELL%."
    set "EXIT_CODE=1"
    goto :finish
)

"%PYTHON%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    call :write_status Red "PyInstaller is not installed in the project Python environment."
    set "EXIT_CODE=1"
    goto :finish
)
"%PYTHON%" -c "import platform, ssl; from importlib.metadata import version; from tools.release_console import write_status; expected={'PySide6-Essentials':'6.11.1','shiboken6':'6.11.1','python-vlc':'3.0.21203','pyinstaller':'6.20.0','pycryptodomex':'3.23.0','cffi':'2.1.1','pycparser':'3.12','setuptools':'84.0.0','packaging':'26.3','typing-extensions':'4.16.0'}; actual={name:version(name) for name in expected}; failures=[name + ': expected ' + wanted + ', found ' + actual[name] for name,wanted in expected.items() if actual[name] != wanted]; failures += [] if platform.python_version() == '3.14.7' else ['CPython: expected 3.14.7, found ' + platform.python_version()]; failures += [] if ssl.OPENSSL_VERSION.startswith('OpenSSL 3.5.7 ') else ['OpenSSL: expected 3.5.7, found ' + ssl.OPENSSL_VERSION]; write_status('Reviewed package versions matched.' if not failures else '; '.join(failures), 'green' if not failures else 'red'); raise SystemExit(bool(failures))"
if errorlevel 1 (
    call :write_status Red "The Python environment does not match the reviewed component versions in THIRD_PARTY_NOTICES.md."
    set "EXIT_CODE=1"
    goto :finish
)
"%POWERSHELL%" -NoProfile -Command "function Get-Sha256([string]$Path) { $sha = [Security.Cryptography.SHA256]::Create(); $stream = [IO.File]::OpenRead($Path); try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() } finally { $stream.Dispose(); $sha.Dispose() } }; $expected = '1aa1bf54f96ac3f335cafcf6672f6474590d6bcee5903b04eea81df828841fc9'; $installed = Get-Sha256 '.venv\Lib\site-packages\vlc.py'; $source = Get-Sha256 'third_party\python-vlc\vlc.py'; if ($installed -ne $expected -or $source -ne $expected) { Write-Error ('python-vlc source hash mismatch: installed=' + $installed + ', repository=' + $source); exit 1 }"
if errorlevel 1 (
    call :write_status Red "The replaceable python-vlc source does not match the reviewed 3.0.21203 file."
    set "EXIT_CODE=1"
    goto :finish
)

set "VLC_RUNTIME=%~dp0.runtime\vlc"
if not exist "%VLC_RUNTIME%\libvlc.dll" (
    call :write_status Red "The VLC runtime is missing at %VLC_RUNTIME%."
    call :write_status Red "Prepare VLC using README instructions, or run the local link helper from your separate source checkout."
    set "EXIT_CODE=1"
    goto :finish
)
"%POWERSHELL%" -NoProfile -Command "$ErrorActionPreference = 'Stop'; try { $version = (Get-Item -LiteralPath (Join-Path $env:VLC_RUNTIME 'libvlc.dll')).VersionInfo.FileVersion; if ($version -ne '3.0.24') { throw ('Expected VLC 3.0.24, found ' + $version + '.') }; exit 0 } catch { Write-Error $_; exit 1 }"
if errorlevel 1 (
    call :write_status Red "The prepared VLC runtime does not match the reviewed VLC 3.0.24 package."
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\codec\libavcodec_plugin.dll" (
    call :write_status Red "The VLC runtime is incomplete. Run tools\prepare_vlc_runtime.bat again."
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\codec\libadpcm_plugin.dll" (
    call :write_status Red "The VLC runtime is missing its ADPCM audio decoder. Run tools\prepare_vlc_runtime.bat again."
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\codec\libaraw_plugin.dll" (
    call :write_status Red "The VLC runtime is missing its PCM audio decoder. Run tools\prepare_vlc_runtime.bat again."
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\demux\libwav_plugin.dll" (
    call :write_status Red "The VLC runtime is missing its WAV demuxer. Run tools\prepare_vlc_runtime.bat again."
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\audio_filter\libaudio_format_plugin.dll" (
    call :write_status Red "The VLC runtime is missing its audio format plugin. Run tools\prepare_vlc_runtime.bat again."
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\audio_filter\libtrivial_channel_mixer_plugin.dll" (
    call :write_status Red "The VLC runtime is missing its audio channel converter. Run tools\prepare_vlc_runtime.bat again."
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\COPYING.txt" (
    call :write_status Red "The VLC GPL license file is missing from the prepared runtime."
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\README.txt" (
    call :write_status Red "The VLC runtime README is missing from the prepared runtime."
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "dist" goto :dist_cleaned
call :write_status Yellow "The entire dist directory will be deleted before packaging: %CD%\dist"
set "CLEAN_CONFIRM="
set /p "CLEAN_CONFIRM=Enter Y to continue: "
if /I not "%CLEAN_CONFIRM%"=="Y" goto :package_cancelled
rmdir /s /q "dist"
if exist "dist" (
    call :write_status Red "Could not clear the existing dist directory. Close files using it and retry."
    set "EXIT_CODE=1"
    goto :finish
)

:dist_cleaned

"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name RA2AYRMB ^
    --icon "%~dp0mix_browser\data\icons\MIX-EXE.ico" ^
    --additional-hooks-dir "%~dp0tools\pyinstaller_hooks" ^
    --exclude-module vlc ^
    --exclude-module PySide6.QtMultimedia ^
    --exclude-module PySide6.QtMultimediaWidgets ^
    --exclude-module PySide6.QtPdf ^
    --exclude-module PySide6.QtPdfWidgets ^
    --exclude-module PySide6.QtQml ^
    --exclude-module PySide6.QtQuick ^
    --distpath dist ^
    --workpath .pyinstaller-work\build ^
    --specpath .pyinstaller-work ^
    --add-data "%~dp0mix_browser\data\icons;mix_browser\data\icons" ^
    --add-data "%~dp0mix_browser\data\name_sources\xcc\ra2 mix description.txt;mix_browser\data\name_sources\xcc" ^
    --add-data "%~dp0mix_browser\data\name_sources\xcc\td mix description.txt;mix_browser\data\name_sources\xcc" ^
    --add-data "%~dp0mix_browser\data\name_sources\xcc\ts mix description.txt;mix_browser\data\name_sources\xcc" ^
    --add-data "%~dp0mix_browser\translations\ra2ayrmb_zh_CN.qm;mix_browser\translations" ^
    main.py
if errorlevel 1 (
    call :write_status Red "Packaging failed. See the PyInstaller output above."
    set "EXIT_CODE=1"
    goto :finish
)

if not exist "dist\RA2AYRMB\RA2AYRMB.exe" (
    call :write_status Red "Packaging completed without the expected executable: dist\RA2AYRMB\RA2AYRMB.exe"
    set "EXIT_CODE=1"
    goto :finish
)

if not exist "dist\RA2AYRMB\python-vlc" mkdir "dist\RA2AYRMB\python-vlc"
if errorlevel 1 goto :python_vlc_copy_failed
copy /b "%~dp0third_party\python-vlc\vlc.py" "dist\RA2AYRMB\python-vlc\vlc.py" >nul
if errorlevel 1 goto :python_vlc_copy_failed
if not exist "dist\RA2AYRMB\python-vlc\vlc.py" goto :python_vlc_copy_failed

if not exist "dist\RA2AYRMB\_internal\PySide6\plugins\styles\qmodernwindowsstyle.dll" (
    call :write_status Red "Packaging omitted the Qt Windows 11 style plugin required to match source UI rendering."
    set "EXIT_CODE=1"
    goto :finish
)
if exist "dist\RA2AYRMB\_internal\setuptools\_vendor\jaraco\text\Lorem ipsum.txt" (
    call :write_status Red "Packaging included an unused setuptools Lorem ipsum sample file."
    set "EXIT_CODE=1"
    goto :finish
)

set "VLC_DIST=%~dp0dist\RA2AYRMB\vlc"
set "VLC_COPY_SCRIPT=%~dp0tools\copy_vlc_runtime.ps1"
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%VLC_COPY_SCRIPT%" -Source "%VLC_RUNTIME%" -Destination "%VLC_DIST%"
if errorlevel 1 goto :vlc_copy_failed
if not exist "%VLC_DIST%\libvlc.dll" goto :vlc_copy_failed
if not exist "%VLC_DIST%\plugins\codec\libavcodec_plugin.dll" goto :vlc_copy_failed
if not exist "%VLC_DIST%\plugins\codec\libadpcm_plugin.dll" goto :vlc_copy_failed
if not exist "%VLC_DIST%\plugins\codec\libaraw_plugin.dll" goto :vlc_copy_failed
if not exist "%VLC_DIST%\plugins\demux\libwav_plugin.dll" goto :vlc_copy_failed
if not exist "%VLC_DIST%\plugins\audio_filter\libaudio_format_plugin.dll" goto :vlc_copy_failed
if not exist "%VLC_DIST%\plugins\audio_filter\libtrivial_channel_mixer_plugin.dll" goto :vlc_copy_failed
if not exist "%VLC_DIST%\plugins\plugins.dat" goto :vlc_copy_failed

set "LICENSE_ROOT=dist\RA2AYRMB\licenses"
if not exist "%LICENSE_ROOT%" mkdir "%LICENSE_ROOT%"
if errorlevel 1 goto :license_copy_failed

copy /b "%~dp0LICENSE" "%LICENSE_ROOT%\RA2AYRMB-MIT.txt" >nul
if errorlevel 1 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\RA2AYRMB-MIT.txt" goto :license_copy_failed
copy /b "%~dp0THIRD_PARTY_NOTICES.md" "%LICENSE_ROOT%\THIRD_PARTY_NOTICES.md" >nul
if errorlevel 1 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\THIRD_PARTY_NOTICES.md" goto :license_copy_failed

if not exist "%LICENSE_ROOT%\Qt" mkdir "%LICENSE_ROOT%\Qt"
if errorlevel 1 goto :license_copy_failed
copy /b "%~dp0LGPL-3.0-only.txt" "%LICENSE_ROOT%\Qt\LGPL-3.0-only.txt" >nul
if errorlevel 1 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\Qt\LGPL-3.0-only.txt" goto :license_copy_failed

if not exist "%LICENSE_ROOT%\XCC" mkdir "%LICENSE_ROOT%\XCC"
if errorlevel 1 goto :license_copy_failed
copy /b "%~dp0mix_browser\data\name_sources\xcc\COPYING" "%LICENSE_ROOT%\XCC\COPYING" >nul
if errorlevel 1 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\XCC\COPYING" goto :license_copy_failed

set "PYTHON_BASE="
for /f "delims=" %%P in ('%PYTHON% -c "import sys; print(sys.base_prefix)"') do set "PYTHON_BASE=%%P"
if not defined PYTHON_BASE goto :license_copy_failed
if not exist "%PYTHON_BASE%\LICENSE.txt" goto :license_copy_failed
if not exist "%LICENSE_ROOT%\Python" mkdir "%LICENSE_ROOT%\Python"
if errorlevel 1 goto :license_copy_failed
copy /b "%PYTHON_BASE%\LICENSE.txt" "%LICENSE_ROOT%\Python\LICENSE.txt" >nul
if errorlevel 1 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\Python\LICENSE.txt" goto :license_copy_failed

set "PYCRYPTODOMEX_LICENSE_FOUND="
for /d %%D in (.venv\Lib\site-packages\pycryptodomex-*.dist-info) do (
    if exist "%%D\LICENSE.rst" (
        copy /b "%%D\LICENSE.rst" "%LICENSE_ROOT%\pycryptodomex-LICENSE.rst" >nul
        if errorlevel 1 goto :license_copy_failed
        set "PYCRYPTODOMEX_LICENSE_FOUND=1"
    )
)
if not defined PYCRYPTODOMEX_LICENSE_FOUND goto :license_copy_failed
if not exist "%LICENSE_ROOT%\pycryptodomex-LICENSE.rst" goto :license_copy_failed

set "PYINSTALLER_LICENSE_FOUND="
for /d %%D in (.venv\Lib\site-packages\pyinstaller-*.dist-info) do (
    if exist "%%D\licenses\COPYING.txt" (
        if not exist "%LICENSE_ROOT%\PyInstaller" mkdir "%LICENSE_ROOT%\PyInstaller"
        if errorlevel 1 goto :license_copy_failed
        copy /b "%%D\licenses\COPYING.txt" "%LICENSE_ROOT%\PyInstaller\COPYING.txt" >nul
        if errorlevel 1 goto :license_copy_failed
        set "PYINSTALLER_LICENSE_FOUND=1"
    )
)
if not defined PYINSTALLER_LICENSE_FOUND goto :license_copy_failed
if not exist "%LICENSE_ROOT%\PyInstaller\COPYING.txt" goto :license_copy_failed

set "SETUPTOOLS_LICENSE_FOUND="
for /d %%D in (.venv\Lib\site-packages\setuptools-*.dist-info) do (
    if exist "%%D\licenses\LICENSE" (
        if not exist "%LICENSE_ROOT%\setuptools" mkdir "%LICENSE_ROOT%\setuptools"
        if errorlevel 1 goto :license_copy_failed
        copy /b "%%D\licenses\LICENSE" "%LICENSE_ROOT%\setuptools\LICENSE" >nul
        if errorlevel 1 goto :license_copy_failed
        set "SETUPTOOLS_LICENSE_FOUND=1"
    )
)
if not defined SETUPTOOLS_LICENSE_FOUND goto :license_copy_failed
if not exist "%LICENSE_ROOT%\setuptools\LICENSE" goto :license_copy_failed

robocopy "%~dp0.venv\Lib\site-packages\setuptools\_vendor" "%LICENSE_ROOT%\setuptools-vendor" LICENSE* /S /R:1 /W:1 >nul
if errorlevel 8 goto :license_copy_failed

if not exist "%LICENSE_ROOT%\VLC" mkdir "%LICENSE_ROOT%\VLC"
if errorlevel 1 goto :license_copy_failed
copy /b "%VLC_RUNTIME%\COPYING.txt" "%LICENSE_ROOT%\VLC\COPYING.txt" >nul
if errorlevel 1 goto :license_copy_failed
copy /b "%VLC_RUNTIME%\README.txt" "%LICENSE_ROOT%\VLC\README.txt" >nul
if errorlevel 1 goto :license_copy_failed
copy /b "%~dp0docs\licenses\VLC\SOURCE_CODE_OFFER.txt" "%LICENSE_ROOT%\VLC\SOURCE_CODE_OFFER.txt" >nul
if errorlevel 1 goto :license_copy_failed
robocopy "%~dp0docs\licenses" "%LICENSE_ROOT%" /E /R:1 /W:1 /XD __pycache__ PyInstaller /XF *.pyc *.pyo >nul
if errorlevel 8 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\GPL-3.0.txt" goto :license_copy_failed
if not exist "%LICENSE_ROOT%\RA2AYRMB-WINDOWS-DISTRIBUTION.txt" goto :license_copy_failed
if not exist "%LICENSE_ROOT%\CORRESPONDING_SOURCE_OFFER.txt" goto :license_copy_failed
for %%F in (Qt\THIRD-PARTY-NOTICES.md Qt\Apache-2.0.txt Qt\BLAKE2-COPYING.txt Qt\BSD-2-Clause.txt Qt\BSD-3-Clause.txt Qt\CC0-1.0.txt Qt\double-conversion-LICENSE.txt Qt\FTL.txt Qt\harfbuzz-COPYING.txt Qt\ICC-LICENSE.txt Qt\IJG.txt Qt\libjpeg-LICENSE.txt Qt\Libpng.txt Qt\libpng-2.0.txt Qt\MIT.txt Qt\MIT-open-group.txt Qt\MPL-2.0.txt Qt\PCRE2-BSD-3-Clause-Exception.txt Qt\SHA1-Public-Domain.txt Qt\Zlib.txt Microsoft\REDIST.txt Microsoft\Visual-C++-Redistributable.md Python\Expat-COPYING.txt Python\libmpdec-LICENSE.txt Python\Unicode-LICENSE.txt Python\zlib-ng-LICENSE.txt packaging\LICENSE packaging\LICENSE.APACHE packaging\LICENSE.BSD typing_extensions\LICENSE python-vlc\COPYING VLC\COPYING.LIB VLC\SOURCE_CODE_OFFER.txt Lucide\ISC.txt setuptools\LICENSE setuptools-vendor\backports.tarfile-1.2.0.dist-info\LICENSE setuptools-vendor\jaraco.text-4.0.0.dist-info\LICENSE setuptools-vendor\jaraco_context-6.1.0.dist-info\licenses\LICENSE setuptools-vendor\jaraco_functools-4.4.0.dist-info\licenses\LICENSE setuptools-vendor\more_itertools-10.8.0.dist-info\licenses\LICENSE setuptools-vendor\packaging-26.0.dist-info\licenses\LICENSE setuptools-vendor\packaging-26.0.dist-info\licenses\LICENSE.APACHE setuptools-vendor\packaging-26.0.dist-info\licenses\LICENSE.BSD setuptools-vendor\tomli-2.4.0.dist-info\licenses\LICENSE setuptools-vendor\wheel-0.46.3.dist-info\licenses\LICENSE.txt) do (
    if not exist "%LICENSE_ROOT%\%%F" goto :license_copy_failed
)
copy /b "%~dp0docs\vlc_runtime_licenses.md" "%LICENSE_ROOT%\VLC\PLUGIN_LICENSES.md" >nul
if errorlevel 1 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\VLC\PLUGIN_LICENSES.md" goto :license_copy_failed

call :write_status Green "Packaging completed: dist\RA2AYRMB\RA2AYRMB.exe"
set "EXIT_CODE=0"
goto :finish

:license_copy_failed
call :write_status Red "Packaging stopped after the executable was built because third-party license files could not be collected."
call :write_status Red "Do not distribute this application build until its license bundle is complete."
set "EXIT_CODE=1"
goto :finish

:vlc_copy_failed
call :write_status Red "Packaging stopped after the executable was built because the reduced VLC runtime could not be copied."
call :write_status Red "Required VLC files include %VLC_DIST%\libvlc.dll and %VLC_DIST%\plugins\audio_filter\libtrivial_channel_mixer_plugin.dll."
set "EXIT_CODE=1"
goto :finish

:python_vlc_copy_failed
call :write_status Red "Packaging stopped after the executable was built because the replaceable python-vlc binding could not be copied."
set "EXIT_CODE=1"
goto :finish

:package_cancelled
call :write_status Yellow "Packaging cancelled. The existing dist directory was kept."
set "EXIT_CODE=2"
goto :finish

:finish
if "%EXIT_CODE%"=="1" call :write_status Red "Packaging failed."
if not "%RA2AYRMB_RELEASE_ORCHESTRATOR%"=="1" pause
exit /b %EXIT_CODE%

:write_status
set "STATUS_COLOR=%~1"
set "STATUS_TEXT=%~2"
if exist "%POWERSHELL%" (
    "%POWERSHELL%" -NoProfile -Command "Write-Host $env:STATUS_TEXT -ForegroundColor $env:STATUS_COLOR"
) else (
    echo %STATUS_TEXT%
)
exit /b 0
