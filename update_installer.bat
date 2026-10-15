@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\build.ps1"
if errorlevel 1 exit /b %errorlevel%

set "INSTALLER=%~dp0release\seoul2line-toolbox-setup.exe"
if not exist "%INSTALLER%" exit /b 1
start "" /wait "%INSTALLER%"
exit /b %errorlevel%
