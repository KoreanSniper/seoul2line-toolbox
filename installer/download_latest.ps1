param([switch]$DownloadOnly, [string]$Destination = '')
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$repository = 'KoreanSniper/seoul2line-toolbox'
$headers = @{ 'User-Agent' = 'seoul2line-Toolbox-updater' }
$temporary = $null
try {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repository/releases/latest" -Headers $headers
    if ($release.tag_name -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$' -or $release.draft -or $release.prerelease) { throw 'No stable release is available.' }
    $baseUrl = "https://github.com/$repository/releases/download/$($release.tag_name)/"
    foreach ($name in @('update.json', 'seoul2line-toolbox-setup.exe')) {
        $asset = @($release.assets | Where-Object { $_.name -eq $name })
        if ($asset.Count -ne 1 -or $asset[0].browser_download_url -cne "$baseUrl$name") { throw "Missing verified release asset: $name" }
    }
    $manifest = Invoke-RestMethod -Uri ($baseUrl + 'update.json') -Headers $headers
    $installerAsset = $release.assets | Where-Object { $_.name -eq 'seoul2line-toolbox-setup.exe' }
    if ($manifest.version -cne $release.tag_name.Substring(1) -or $manifest.installer -cne 'seoul2line-toolbox-setup.exe' -or
        $manifest.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or $manifest.size -le 0 -or $manifest.size -gt 536870912 -or $manifest.size -ne $installerAsset.size) { throw 'Invalid release manifest.' }
    if (-not $Destination) { $Destination = Join-Path $env:LOCALAPPDATA 'seoul2line Toolbox\user_data\updates' }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $installerPath = Join-Path $Destination "setup-$($manifest.version).exe"
    $temporary = "$installerPath.part"
    Invoke-WebRequest -Uri ($baseUrl + 'seoul2line-toolbox-setup.exe') -Headers $headers -OutFile $temporary -UseBasicParsing
    if ((Get-Item -LiteralPath $temporary).Length -ne $manifest.size -or (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash -ine $manifest.sha256) { throw 'Downloaded installer verification failed.' }
    Move-Item -LiteralPath $temporary -Destination $installerPath -Force
    if ($DownloadOnly) { Write-Output $installerPath; exit 0 }
    $process = Start-Process -FilePath $installerPath -Wait -PassThru
    exit $process.ExitCode
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
} finally {
    if ($temporary -and (Test-Path -LiteralPath $temporary)) { Remove-Item -LiteralPath $temporary }
}
