param([string]$Python = '', [switch]$InstallDependencies)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not $Python) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command -and $command.Source -notlike '*WindowsApps*') { $Python = $command.Source }
        if (-not $Python) {
            $candidates = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue
            $Python = $candidates | Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
        }
        if (-not $Python -and (Get-Command py -ErrorAction SilentlyContinue)) {
            $Python = & py -3 -c 'import sys; print(sys.executable)'
            if ($LASTEXITCODE -ne 0) { $Python = '' }
        }
    }
    if (-not $Python) { throw 'Python 3.11+ is required. Pass -Python with the python.exe path.' }
    function Invoke-Python([string[]]$Arguments) {
        & $Python @Arguments
        if ($LASTEXITCODE -ne 0) { throw "Python command failed (exit $LASTEXITCODE): $Arguments" }
    }
    if ($InstallDependencies) { Invoke-Python @('-m', 'pip', 'install', '-r', 'requirements.txt', 'pyinstaller') }
    $versionLine = Get-Content -LiteralPath 'app/version.py' | Where-Object { $_ -match '^VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$' }
    if (-not $versionLine) { throw 'app/version.py must contain a stable x.y.z VERSION.' }
    $appVersion = [regex]::Match($versionLine, '"([0-9]+\.[0-9]+\.[0-9]+)"').Groups[1].Value
    if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -ne "v$appVersion") { throw 'Tag must match app/version.py.' }
    Invoke-Python @('-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
        '--name', 'seoul2line Toolbox', '--add-data', 'app/assets;app/assets',
        '--add-data', 'installer/install_update.ps1;updater',
        '--add-data', 'app/games/starsystem/renderer/shaders;app/games/starsystem/renderer/shaders', '--collect-submodules', 'app',
        '--hidden-import', 'uuid', '--hidden-import', 'keyword', 'main.py')
    if (-not (Test-Path -LiteralPath 'dist/seoul2line Toolbox/seoul2line Toolbox.exe')) { throw 'PyInstaller output missing.' }
    foreach ($pluginName in @('developer_tools', 'example_plugin')) {
        $pluginSource = Join-Path $projectRoot "plugins/$pluginName"
        foreach ($file in (Get-ChildItem -LiteralPath $pluginSource -Recurse -File)) {
            if ($file.FullName -match '[\\/]__pycache__[\\/]' -or $file.Extension -eq '.pyc') { continue }
            $relative = $file.FullName.Substring($pluginSource.Length).TrimStart([IO.Path]::DirectorySeparatorChar)
            $target = Join-Path $projectRoot "dist/seoul2line Toolbox/plugins/$pluginName/$relative"
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $target
        }
    }
    $previousLocalData = $env:LOCALAPPDATA
    try {
        $env:LOCALAPPDATA = Join-Path $projectRoot 'user_data/build-smoke'
        New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA | Out-Null
        $reportPath = Join-Path $projectRoot 'build/frozen-smoke.json'
        if (Test-Path -LiteralPath $reportPath) { Remove-Item -LiteralPath $reportPath }
        $smoke = Start-Process -FilePath (Join-Path $projectRoot 'dist/seoul2line Toolbox/seoul2line Toolbox.exe') -ArgumentList @('--self-test-report', ('"{0}"' -f $reportPath)) -WindowStyle Hidden -PassThru
        if (-not $smoke.WaitForExit(60000)) { $smoke.Kill(); throw 'Frozen smoke test timed out.' }
        if ($smoke.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) { throw 'Frozen smoke test failed. Check build/frozen-smoke.json.' }
        $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
        if (-not $report.ok) { throw $report.error }
    } finally { $env:LOCALAPPDATA = $previousLocalData }
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    $isccPath = if ($iscc) { $iscc.Source } else { @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1 }
    if (-not $isccPath) { throw 'Inno Setup 6 (ISCC.exe) is required.' }
    & $isccPath "/DAppVersion=$appVersion" 'installer/seoul2line.iss'
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed with exit code $LASTEXITCODE." }
    $installerPath = Join-Path $projectRoot 'release/seoul2line-toolbox-setup.exe'
    if (-not (Test-Path -LiteralPath $installerPath)) { throw 'Installer output missing.' }
    $manifest = @{ version = $appVersion; installer = 'seoul2line-toolbox-setup.exe';
        sha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant();
        size = (Get-Item -LiteralPath $installerPath).Length }
    [System.IO.File]::WriteAllText((Join-Path $projectRoot 'release/update.json'), ($manifest | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Installer and verified update manifest created in $projectRoot\release"
} finally { Pop-Location }
