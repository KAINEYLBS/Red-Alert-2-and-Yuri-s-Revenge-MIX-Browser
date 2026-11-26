@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_vlc_runtime.ps1"
if errorlevel 1 (
    powershell -NoProfile -Command "Write-Host 'VLC runtime preparation failed.' -ForegroundColor Red"
    pause
    exit /b 1
)
exit /b 0
