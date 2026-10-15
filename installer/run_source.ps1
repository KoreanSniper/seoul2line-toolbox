$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$pythonPath = $env:TOOLBOX_PYTHON
if (-not $pythonPath) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*WindowsApps*') { $pythonPath = $command.Source }
}
if (-not $pythonPath) {
    $pythonPath = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if ($pythonPath) { & $pythonPath -B main.py }
else { & py -3 -B main.py }
exit $LASTEXITCODE
