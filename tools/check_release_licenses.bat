@echo off
setlocal EnableExtensions
set "PROJECT_ROOT=%~dp0.."
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
set "SOURCE_TREE=%~1"
if not defined SOURCE_TREE set "SOURCE_TREE=%PROJECT_ROOT%"
for %%I in ("%SOURCE_TREE%") do set "SOURCE_TREE=%%~fI"
set "POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%POWERSHELL%" (
    if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" (
        "%PROJECT_ROOT%\.venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, sys.argv[1]); from release_console import write_status; write_status(sys.argv[2], 'red', stream=sys.stderr)" "%PROJECT_ROOT%\tools" "Windows PowerShell was not found at %POWERSHELL%."
        if errorlevel 1 (
            color 0C
            echo Windows PowerShell was not found at "%POWERSHELL%".
            color
        )
    ) else (
        color 0C
        echo Windows PowerShell was not found at "%POWERSHELL%".
        color
    )
    exit /b 1
)
"%POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\tools\check_release_licenses.ps1" -SourceTree "%SOURCE_TREE%" -ReleaseDirectory "%~2"
exit /b %ERRORLEVEL%
