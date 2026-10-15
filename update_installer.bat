@echo off
setlocal
cd /d "%~dp0"
if /I "%~1"=="--build" goto build
if exist "%~dp0installer\download_latest.ps1" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\download_latest.ps1"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_latest.ps1"
)
exit /b %errorlevel%
:build
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\build.ps1" -InstallDependencies
if errorlevel 1 exit /b %errorlevel%
echo Build complete: %~dp0release\seoul2line-toolbox-setup.exe
exit /b 0
