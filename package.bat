@echo off
setlocal
set "EXIT_CODE=0"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
cd /d "%~dp0"
if errorlevel 1 (
    echo Could not change to the project directory: "%~dp0"
    set "EXIT_CODE=1"
    goto :finish
)

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo The project Python environment was not found at %PYTHON%.
    echo Create the environment here using README instructions, or run the local link helper from your separate source checkout.
    set "EXIT_CODE=1"
    goto :finish
)

set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%~dp0.venv\Scripts"
if not exist "%POWERSHELL%" (
    echo Windows PowerShell was not found at "%POWERSHELL%".
    set "EXIT_CODE=1"
    goto :finish
)

"%PYTHON%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller is not installed in the project Python environment.
    set "EXIT_CODE=1"
    goto :finish
)

set "VLC_RUNTIME=%~dp0.runtime\vlc"
if not exist "%VLC_RUNTIME%\libvlc.dll" (
    echo The VLC runtime is missing at "%VLC_RUNTIME%".
    echo Prepare VLC here using README instructions, or run the local link helper from your separate source checkout.
    set "EXIT_CODE=1"
    goto :finish
)
"%POWERSHELL%" -NoProfile -Command "$ErrorActionPreference = 'Stop'; try { $version = (Get-Item -LiteralPath (Join-Path $env:VLC_RUNTIME 'libvlc.dll')).VersionInfo.FileVersion; if ($version -ne '3.0.24') { throw ('Expected VLC 3.0.24, found ' + $version + '.') }; exit 0 } catch { Write-Error $_; exit 1 }"
if errorlevel 1 (
    echo The prepared VLC runtime does not match the reviewed VLC 3.0.24 package.
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\codec\libavcodec_plugin.dll" (
    echo The VLC runtime is incomplete. Run tools\prepare_vlc_runtime.bat again.
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\codec\libadpcm_plugin.dll" (
    echo The VLC runtime is missing its ADPCM audio decoder. Run tools\prepare_vlc_runtime.bat again.
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\codec\libaraw_plugin.dll" (
    echo The VLC runtime is missing its PCM audio decoder. Run tools\prepare_vlc_runtime.bat again.
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\demux\libwav_plugin.dll" (
    echo The VLC runtime is missing its WAV demuxer. Run tools\prepare_vlc_runtime.bat again.
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\audio_filter\libaudio_format_plugin.dll" (
    echo The VLC runtime is missing its audio format plugin. Run tools\prepare_vlc_runtime.bat again.
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\plugins\audio_filter\libtrivial_channel_mixer_plugin.dll" (
    echo The VLC runtime is missing its audio channel converter. Run tools\prepare_vlc_runtime.bat again.
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\COPYING.txt" (
    echo The VLC GPL license file is missing from the prepared runtime.
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "%VLC_RUNTIME%\README.txt" (
    echo The VLC runtime README is missing from the prepared runtime.
    set "EXIT_CODE=1"
    goto :finish
)
if not exist "dist" goto :dist_cleaned
echo The entire dist directory will be deleted before packaging:
echo "%CD%\dist"
set "CLEAN_CONFIRM="
set /p "CLEAN_CONFIRM=Enter Y to continue: "
if /I not "%CLEAN_CONFIRM%"=="Y" goto :package_cancelled
rmdir /s /q "dist"
if exist "dist" (
    echo Could not clear the existing dist directory. Close files using it and retry.
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
    --hidden-import vlc ^
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
    --add-data "%~dp0mix_browser\data\name_sources\xcc;mix_browser\data\name_sources\xcc" ^
    --add-data "%~dp0mix_browser\translations\ra2ayrmb_zh_CN.qm;mix_browser\translations" ^
    --add-data "%~dp0THIRD_PARTY_NOTICES.md;licenses" ^
    --add-data "%~dp0LGPL-3.0-only.txt;licenses" ^
    --add-data "%~dp0mix_browser\data\name_sources\xcc\COPYING;licenses\XCC" ^
    --add-data "%~dp0LICENSE;." ^
    main.py
if errorlevel 1 (
    echo Packaging failed. See the PyInstaller output above.
    set "EXIT_CODE=1"
    goto :finish
)

if not exist "dist\RA2AYRMB\RA2AYRMB.exe" (
    echo Packaging completed without the expected executable: dist\RA2AYRMB\RA2AYRMB.exe
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

set "LICENSE_ROOT=dist\RA2AYRMB\licenses"
if not exist "%LICENSE_ROOT%" mkdir "%LICENSE_ROOT%"
if errorlevel 1 goto :license_copy_failed

set "PYTHON_BASE="
for /f "delims=" %%P in ('%PYTHON% -c "import sys; print(sys.base_prefix)"') do set "PYTHON_BASE=%%P"
if not defined PYTHON_BASE goto :license_copy_failed
if not exist "%PYTHON_BASE%\LICENSE.txt" goto :license_copy_failed
if not exist "%LICENSE_ROOT%\Python" mkdir "%LICENSE_ROOT%\Python"
if errorlevel 1 goto :license_copy_failed
copy /b "%PYTHON_BASE%\LICENSE.txt" "%LICENSE_ROOT%\Python\LICENSE.txt" >nul
if errorlevel 1 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\Python\LICENSE.txt" goto :license_copy_failed

set "PYSIDE_ESSENTIALS_LICENSES_FOUND="
for /d %%D in (.venv\Lib\site-packages\pyside6_essentials-*.dist-info) do (
    if not exist "%%D\licenses\*" goto :license_copy_failed
    robocopy "%%D\licenses" "%LICENSE_ROOT%\%%~nD" /E /R:1 /W:1 >nul
    if errorlevel 8 goto :license_copy_failed
    if not exist "%LICENSE_ROOT%\%%~nD\*" goto :license_copy_failed
    set "PYSIDE_ESSENTIALS_LICENSES_FOUND=1"
)
if not defined PYSIDE_ESSENTIALS_LICENSES_FOUND goto :license_copy_failed

set "SHIBOKEN_LICENSES_FOUND="
for /d %%D in (.venv\Lib\site-packages\shiboken6-*.dist-info) do (
    if not exist "%%D\licenses\*" goto :license_copy_failed
    robocopy "%%D\licenses" "%LICENSE_ROOT%\%%~nD" /E /R:1 /W:1 >nul
    if errorlevel 8 goto :license_copy_failed
    if not exist "%LICENSE_ROOT%\%%~nD\*" goto :license_copy_failed
    set "SHIBOKEN_LICENSES_FOUND=1"
)
if not defined SHIBOKEN_LICENSES_FOUND goto :license_copy_failed

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

set "PYTHON_VLC_LICENSE_FOUND="
for /d %%D in (.venv\Lib\site-packages\python_vlc-*.dist-info) do (
    if exist "%%D\COPYING" (
        if not exist "%LICENSE_ROOT%\python-vlc" mkdir "%LICENSE_ROOT%\python-vlc"
        if errorlevel 1 goto :license_copy_failed
        copy /b "%%D\COPYING" "%LICENSE_ROOT%\python-vlc\COPYING" >nul
        if errorlevel 1 goto :license_copy_failed
        set "PYTHON_VLC_LICENSE_FOUND=1"
    )
)
if not defined PYTHON_VLC_LICENSE_FOUND goto :license_copy_failed
if not exist "%LICENSE_ROOT%\python-vlc\COPYING" goto :license_copy_failed

if not exist "%LICENSE_ROOT%\VLC" mkdir "%LICENSE_ROOT%\VLC"
if errorlevel 1 goto :license_copy_failed
copy /b "%VLC_RUNTIME%\COPYING.txt" "%LICENSE_ROOT%\VLC\COPYING.txt" >nul
if errorlevel 1 goto :license_copy_failed
copy /b "%VLC_RUNTIME%\README.txt" "%LICENSE_ROOT%\VLC\README.txt" >nul
if errorlevel 1 goto :license_copy_failed
copy /b "%~dp0docs\licenses\VLC\COPYING.LIB" "%LICENSE_ROOT%\VLC\COPYING.LIB" >nul
if errorlevel 1 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\VLC\COPYING.LIB" goto :license_copy_failed
copy /b "%~dp0docs\vlc_runtime_licenses.md" "%LICENSE_ROOT%\VLC\PLUGIN_LICENSES.md" >nul
if errorlevel 1 goto :license_copy_failed
if not exist "%LICENSE_ROOT%\VLC\PLUGIN_LICENSES.md" goto :license_copy_failed

call :write_status Green "Packaging completed: dist\RA2AYRMB\RA2AYRMB.exe"
set "EXIT_CODE=0"
goto :finish

:license_copy_failed
echo Packaging stopped after the executable was built because third-party license files could not be collected.
echo Do not distribute this application build until its license bundle is complete.
set "EXIT_CODE=1"
goto :finish

:vlc_copy_failed
echo Packaging stopped after the executable was built because the reduced VLC runtime could not be copied.
echo Required VLC files include "%VLC_DIST%\libvlc.dll" and "%VLC_DIST%\plugins\audio_filter\libtrivial_channel_mixer_plugin.dll".
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
if exist "%POWERSHELL%" (
    "%POWERSHELL%" -NoProfile -Command "Write-Host '%~2' -ForegroundColor %~1"
) else (
    echo %~2
)
exit /b 0
