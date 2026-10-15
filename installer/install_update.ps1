param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [Parameter(Mandatory=$true)][string]$AppExe,
    [Parameter(Mandatory=$true)][int]$ParentProcessId,
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$Sha256
)
$ErrorActionPreference = 'Stop'
$logPath = Join-Path (Split-Path -Parent $Installer) 'install-update.log'
try {
    if ((Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash -ine $Sha256) { throw 'Installer SHA-256 verification failed.' }
    if (Get-Process -Id $ParentProcessId -ErrorAction SilentlyContinue) { Wait-Process -Id $ParentProcessId -Timeout 120 -ErrorAction Stop }
    $installDirectory = Split-Path -Parent $AppExe
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCLOSEAPPLICATIONS',
                   ('/DIR="{0}"' -f $installDirectory), ('/LOG="{0}"' -f $logPath))
    $installation = Start-Process -FilePath $Installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($installation.ExitCode -ne 0) { throw "Installer exited with code $($installation.ExitCode). See $logPath" }
    Start-Process -FilePath $AppExe -WorkingDirectory $installDirectory -WindowStyle Hidden
} catch {
    $_ | Out-String | Add-Content -LiteralPath $logPath -Encoding UTF8
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("Update failed. Your saved data is unchanged.`n$($_.Exception.Message)", 'seoul2line Toolbox') | Out-Null
    exit 1
}
