@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_vlc_runtime.ps1"
if errorlevel 1 (
    pause
    exit /b 1
)
exit /b 0
