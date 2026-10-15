@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0seoul2line Toolbox.exe" (
    start "" "%~dp0seoul2line Toolbox.exe"
    exit /b 0
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\run_source.ps1"
exit /b %errorlevel%
