param(
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path -LiteralPath $Source).Path
$destinationRoot = [System.IO.Path]::GetFullPath($Destination)
$pluginManifest = Join-Path $PSScriptRoot "vlc_runtime_plugins.txt"
$requiredRootFiles = @("libvlc.dll", "libvlccore.dll")

New-Item -ItemType Directory -Force -Path $destinationRoot | Out-Null
$destinationPlugins = Join-Path $destinationRoot "plugins"
New-Item -ItemType Directory -Force -Path $destinationPlugins | Out-Null

foreach ($name in $requiredRootFiles) {
    $sourcePath = Join-Path $sourceRoot $name
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Required VLC runtime file is missing: $sourcePath"
    }
    Copy-Item -LiteralPath $sourcePath -Destination $destinationRoot -Force
}

foreach ($line in Get-Content -LiteralPath $pluginManifest) {
    $relativePath = $line.Trim()
    if (-not $relativePath -or $relativePath.StartsWith("#")) {
        continue
    }
    $relativePath = $relativePath.Replace('/', '\')
    $sourcePath = Join-Path (Join-Path $sourceRoot "plugins") $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "Required VLC playback plugin is missing: $sourcePath"
    }
    $destinationPath = Join-Path $destinationPlugins $relativePath
    $destinationDirectory = Split-Path -Parent $destinationPath
    New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
}

$copiedPluginCount = (Get-Content -LiteralPath $pluginManifest | Where-Object {
    $_.Trim() -and -not $_.Trim().StartsWith("#")
}).Count
Write-Host "Copied VLC core and $copiedPluginCount preview plugins."
