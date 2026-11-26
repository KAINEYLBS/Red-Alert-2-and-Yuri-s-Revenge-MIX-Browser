param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseDirectory,
    [Parameter(Mandatory = $true)]
    [string]$ProjectVersion
)

$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "release-artifacts")).TrimEnd('\')
$releaseFullPath = [IO.Path]::GetFullPath($ReleaseDirectory).TrimEnd('\')
if ($releaseFullPath -ine $releaseRoot) {
    throw "The upload staging script only accepts the project release-artifacts directory."
}
if ($ProjectVersion -notmatch '^[A-Za-z0-9][A-Za-z0-9.+_-]*$') {
    throw "The project version contains characters that cannot be used in release filenames."
}

$inventory = Get-Content -LiteralPath (Join-Path $projectRoot "tools\release_component_inventory.json") -Raw | ConvertFrom-Json
$sourceName = $inventory.artifacts.source.filename.Replace('{version}', $ProjectVersion)
$executableName = $inventory.artifacts.executable.filename.Replace('{version}', $ProjectVersion)
$vlcSourceName = $inventory.artifacts.vlc_source.filename
$comparisonName = "VLC-source-comparison-v$ProjectVersion.md"
$releaseInfoName = "GitHub-release-v$ProjectVersion.md"
$reviewDirectory = Join-Path $releaseFullPath "review-v$ProjectVersion"
$reviewFiles = @(
    "Binary-component-audit-v$ProjectVersion.md",
    "License-artifact-check-v$ProjectVersion.md"
)
$comparisonPath = Join-Path $releaseFullPath $comparisonName
foreach ($requiredName in @($sourceName, $executableName, $comparisonName)) {
    if (-not (Test-Path -LiteralPath (Join-Path $releaseFullPath $requiredName) -PathType Leaf)) {
        throw "A required upload input is missing: $requiredName"
    }
}
foreach ($reviewFile in $reviewFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $reviewDirectory $reviewFile) -PathType Leaf)) {
        throw "A required release review report is missing: review-v$ProjectVersion/$reviewFile"
    }
}

$comparison = Get-Content -LiteralPath $comparisonPath -Raw
$decisionMatch = [regex]::Match($comparison, '(?m)^- VLC source archive upload decision: \*\*(?<decision>[^*]+)\*\*\s*$')
if (-not $decisionMatch.Success) {
    throw "The VLC source comparison report has no recognized upload decision."
}
$includeVlcSource = switch -Exact ($decisionMatch.Groups["decision"].Value) {
    "Upload the VLC source archive with this release." { $true }
    "Do not upload another VLC source archive; reuse the previous release asset." { $false }
    default { throw "Unrecognized VLC source upload decision: $($decisionMatch.Groups['decision'].Value)" }
}
if ($includeVlcSource -and -not (Test-Path -LiteralPath (Join-Path $releaseFullPath $vlcSourceName) -PathType Leaf)) {
    throw "The comparison report requires a VLC source archive, but it is missing: $vlcSourceName"
}

$uploadDirectory = Join-Path $releaseFullPath "upload-v$ProjectVersion"
$uploadFullPath = [IO.Path]::GetFullPath($uploadDirectory)
$releasePrefix = $releaseRoot + '\'
if (-not $uploadFullPath.StartsWith($releasePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The upload directory must remain inside release-artifacts."
}
$knownNames = @($sourceName, $executableName, $vlcSourceName, $comparisonName, $releaseInfoName)
if (Test-Path -LiteralPath $uploadFullPath) {
    $attributes = [IO.File]::GetAttributes($uploadFullPath)
    if (($attributes -band [IO.FileAttributes]::Directory) -eq 0 -or
        ($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "The upload output path exists but is not a regular directory: $uploadFullPath"
    }
    $unexpected = @(
        Get-ChildItem -LiteralPath $uploadFullPath -Force |
            Where-Object {
                $_.PSIsContainer -or
                $_.Name -notin $knownNames -or
                ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
            }
    )
    if ($unexpected.Count -gt 0) {
        $names = ($unexpected | ForEach-Object Name) -join ", "
        throw "The upload directory contains unexpected files; they were left untouched: $names"
    }
} else {
    New-Item -ItemType Directory -Path $uploadFullPath | Out-Null
}

$filesToStage = @($sourceName, $executableName, $comparisonName)
if ($includeVlcSource) {
    $filesToStage += $vlcSourceName
}
$copiedNames = @($filesToStage)
foreach ($name in $copiedNames) {
    Copy-Item -LiteralPath (Join-Path $releaseFullPath $name) -Destination (Join-Path $uploadFullPath $name) -Force
}
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "The project Python environment was not found: $python"
}
$releaseInfoScript = Join-Path $projectRoot "tools\write_github_release_info.py"
& $python $releaseInfoScript --output (Join-Path $uploadFullPath $releaseInfoName)
if ($LASTEXITCODE -ne 0) {
    throw "Could not generate the GitHub release information document."
}
$filesToStage += $releaseInfoName
if (-not $includeVlcSource) {
    $staleVlcPath = Join-Path $uploadFullPath $vlcSourceName
    if (Test-Path -LiteralPath $staleVlcPath -PathType Leaf) {
        Remove-Item -LiteralPath $staleVlcPath -Force
    }
}

$expectedNames = @($filesToStage | Sort-Object)
$actualNames = @((Get-ChildItem -LiteralPath $uploadFullPath -Force | ForEach-Object Name) | Sort-Object)
if (($expectedNames -join "`n") -cne ($actualNames -join "`n")) {
    throw "The upload directory does not contain exactly the files selected for this release."
}
foreach ($name in $copiedNames) {
    $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $releaseFullPath $name)).Hash
    $stagedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $uploadFullPath $name)).Hash
    if ($sourceHash -ine $stagedHash) {
        throw "The staged file does not match its release artifact: $name"
    }
}

foreach ($name in @($sourceName, $executableName, $vlcSourceName, $comparisonName)) {
    $temporaryArtifact = Join-Path $releaseFullPath $name
    if (Test-Path -LiteralPath $temporaryArtifact -PathType Leaf) {
        Remove-Item -LiteralPath $temporaryArtifact -Force
    }
}

Write-Host "Upload directory: $uploadFullPath" -ForegroundColor Green
foreach ($name in $filesToStage) {
    Write-Host "  $name" -ForegroundColor Green
}
