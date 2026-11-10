$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeRoot = Join-Path $projectRoot ".runtime"
$target = Join-Path $runtimeRoot "vlc"
$version = "3.0.24"
$archiveName = "vlc-$version-win64.zip"
$archivePath = Join-Path $runtimeRoot $archiveName
$runtimeExtractionDirectory = Join-Path $runtimeRoot "vlc-$version"
$expectedSha256 = "fcf30850371ad10c9373cc4f0f4501e7dee49e3e9ae9f20c72fb2661a1ca6323"
$downloadBase = "https://mirror.nju.edu.cn/videolan-ftp/vlc/$version/win64"

if (Test-Path -LiteralPath $target) {
    $existingVersion = (Get-Item -LiteralPath (Join-Path $target "libvlc.dll")).VersionInfo.FileVersion
    if ($existingVersion -eq $version -and (Test-Path -LiteralPath (Join-Path $target "plugins\codec\libavcodec_plugin.dll"))) {
        Write-Host "VLC $version runtime is already prepared."
    } else {
        throw "The existing VLC runtime directory is incomplete or has a different version: $target"
    }
} else {
    New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
    if (-not (Test-Path -LiteralPath $archivePath)) {
        Write-Host "Downloading the official VLC $version 64-bit runtime archive..."
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 600 "$downloadBase/$archiveName" -OutFile $archivePath
    }

    $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $expectedSha256) {
        throw "VLC archive SHA-256 mismatch. Expected $expectedSha256, got $actualSha256."
    }

    Write-Host "Extracting the verified VLC runtime..."
    Expand-Archive -LiteralPath $archivePath -DestinationPath $runtimeRoot -Force
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeExtractionDirectory "libvlc.dll"))) {
        throw "The VLC archive did not contain the expected runtime directory."
    }
    Move-Item -LiteralPath $runtimeExtractionDirectory -Destination $target
}
Write-Host "VLC $version runtime prepared at .runtime\vlc."
