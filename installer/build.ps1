$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher (py) is required to build the application."
}

py -m pip install -r requirements.txt
py -m pip install pyinstaller

py -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name "seoul2line Toolbox" `
    --add-data "app/assets;app/assets" `
    --collect-submodules app.tools `
    --collect-submodules app.games `
    main.py

if (-not (Test-Path "dist\seoul2line Toolbox\seoul2line Toolbox.exe")) {
    throw "PyInstaller output was not created."
}

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    $isccPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
} else {
    $isccPath = $iscc.Source
}

if (-not $isccPath) {
    throw "Inno Setup 6 (ISCC.exe) is required to build the installer."
}

& $isccPath "installer\seoul2line.iss"
