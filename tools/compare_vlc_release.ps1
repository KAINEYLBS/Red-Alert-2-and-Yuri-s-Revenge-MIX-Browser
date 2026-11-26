param(
    [Parameter(Mandatory = $true)]
    [string]$CurrentVersion,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "release-artifacts")).TrimEnd('\')
$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
if (-not $outputFullPath.StartsWith($releaseRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "The VLC comparison report must be written inside the project release-artifacts directory."
}

$versionUpdates = Get-Content -LiteralPath (Join-Path $projectRoot "mix_browser\features\browser\version_updates_dialog.py") -Raw
$previousVersionMatch = [regex]::Match($versionUpdates, '(?m)^_PREVIOUS_RELEASE_VERSION\s*=\s*"([^"]+)"')
if (-not $previousVersionMatch.Success) {
    throw "Could not determine the previous release version from the release history."
}
$previousVersion = $previousVersionMatch.Groups[1].Value
$baselineBranch = "archive/RA2AYRMB-release-v$previousVersion"
$baselineCommit = (& git -C $projectRoot rev-parse --verify ($baselineBranch + "^{commit}") 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $baselineCommit) {
    throw "The previous release archive branch was not found: $baselineBranch"
}

function Read-GitFile([string]$branch, [string]$relativePath) {
    $spec = "${branch}:$relativePath"
    $contents = & git -C $projectRoot show $spec 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read $relativePath from $branch."
    }
    return ($contents -join "`n")
}

function Get-RuntimeIdentity([string]$contents) {
    $versionMatch = [regex]::Match($contents, '(?m)^\$version\s*=\s*"([^"]+)"')
    $hashMatch = [regex]::Match($contents, '(?m)^\$expectedSha256\s*=\s*"([0-9a-fA-F]{64})"')
    if (-not $versionMatch.Success -or -not $hashMatch.Success) {
        throw "Could not parse the VLC runtime version and checksum."
    }
    return [pscustomobject]@{
        Version = $versionMatch.Groups[1].Value
        Sha256 = $hashMatch.Groups[1].Value.ToLowerInvariant()
    }
}

function Get-PluginList([string]$contents) {
    return @(
        $contents -split "`r?`n" |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and -not $_.StartsWith("#") }
    )
}

function Get-TextSha256([string]$contents) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($contents)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

function Get-ReviewedComponentVersions([string]$contents) {
    $sectionMatch = [regex]::Match($contents, '(?s)## Reviewed Build Components\s*(?<table>.*?)(?=\r?\n## |\z)')
    if (-not $sectionMatch.Success) {
        throw "Could not find the reviewed VLC build component table."
    }
    $values = @{}
    foreach ($line in ($sectionMatch.Groups["table"].Value -split "`r?`n")) {
        $rowMatch = [regex]::Match($line, '^\|\s*(?<component>[^|]+?)\s*\|\s*(?<version>[^|]+?)\s*\|')
        $componentName = if ($rowMatch.Success) { $rowMatch.Groups["component"].Value.Trim() } else { "" }
        if ($rowMatch.Success -and $componentName -notin @("Component", "---")) {
            $values[$componentName] = $rowMatch.Groups["version"].Value.Trim()
        }
    }
    if ($values.Count -lt 5) {
        throw "The reviewed VLC build component table is incomplete."
    }
    return $values
}

function Get-FfmpegCommit([string]$contents) {
    $match = [regex]::Match($contents, 'pins FFmpeg to commit `(?<commit>[0-9a-fA-F]{40})`')
    if ($match.Success) {
        return $match.Groups["commit"].Value.ToLowerInvariant()
    }
    return ""
}

function Get-SourceAsset([string]$contents) {
    $match = [regex]::Match($contents, 'https://github\.com/KAINEYLBS/Red-Alert-2-and-Yuri-s-Revenge-MIX-Browser/releases/download/[^\s)]+/RA2AYRMB-vlc-source-[^\s)]+\.7z')
    if ($match.Success) {
        return $match.Value
    }
    return ""
}

$currentRuntime = Get-RuntimeIdentity (Get-Content -LiteralPath (Join-Path $projectRoot "tools\prepare_vlc_runtime.ps1") -Raw)
$baselineRuntime = Get-RuntimeIdentity (Read-GitFile $baselineBranch "tools/prepare_vlc_runtime.ps1")
$currentPlugins = Get-PluginList (Get-Content -LiteralPath (Join-Path $projectRoot "tools\vlc_runtime_plugins.txt") -Raw)
$baselinePlugins = Get-PluginList (Read-GitFile $baselineBranch "tools/vlc_runtime_plugins.txt")
$currentPluginHash = Get-TextSha256 ([string]::Join("`n", $currentPlugins))
$baselinePluginHash = Get-TextSha256 ([string]::Join("`n", $baselinePlugins))
$currentReview = Get-Content -LiteralPath (Join-Path $projectRoot "docs\vlc_runtime_licenses.md") -Raw
$baselineReview = Read-GitFile $baselineBranch "docs/vlc_runtime_licenses.md"
$currentComponents = Get-ReviewedComponentVersions $currentReview
$baselineComponents = Get-ReviewedComponentVersions $baselineReview
$currentFfmpegCommit = Get-FfmpegCommit $currentReview
$baselineFfmpegCommit = Get-FfmpegCommit $baselineReview
$previousSourceAsset = Get-SourceAsset $baselineReview

$changes = [Collections.Generic.List[string]]::new()
if ($currentRuntime.Version -ne $baselineRuntime.Version) {
    $changes.Add("VLC runtime version: $($baselineRuntime.Version) -> $($currentRuntime.Version)")
}
if ($currentRuntime.Sha256 -ne $baselineRuntime.Sha256) {
    $changes.Add("VLC runtime SHA-256 changed: $($baselineRuntime.Sha256) -> $($currentRuntime.Sha256)")
}
if (([string]::Join("`n", $currentPlugins)) -cne ([string]::Join("`n", $baselinePlugins))) {
    $changes.Add("The selected VLC plugin list changed.")
}
foreach ($component in ($currentComponents.Keys + $baselineComponents.Keys | Sort-Object -Unique)) {
    $currentValue = [string]$currentComponents[$component]
    $baselineValue = [string]$baselineComponents[$component]
    if ($currentValue -ne $baselineValue) {
        $changes.Add("Reviewed component version changed: $component ($baselineValue -> $currentValue)")
    }
}
if ($currentFfmpegCommit -and $baselineFfmpegCommit -and $currentFfmpegCommit -ne $baselineFfmpegCommit) {
    $changes.Add("FFmpeg source commit changed: $baselineFfmpegCommit -> $currentFfmpegCommit")
}

$commitComparison = if ($currentFfmpegCommit -and $baselineFfmpegCommit) {
    if ($currentFfmpegCommit -eq $baselineFfmpegCommit) { "unchanged: $currentFfmpegCommit" } else { "changed: $baselineFfmpegCommit -> $currentFfmpegCommit" }
} elseif ($currentFfmpegCommit) {
    "current review records $currentFfmpegCommit; previous review did not record a commit"
} elseif ($baselineFfmpegCommit) {
    "current review does not record the previous pin $baselineFfmpegCommit"
} else {
    "not recorded by either review"
}
$comparisonUncertain = -not $currentFfmpegCommit -or -not $baselineFfmpegCommit
$runtimeChanged = $changes.Count -gt 0
$uploadRequired = $runtimeChanged -or $comparisonUncertain -or -not $previousSourceAsset

$changeResult = if ($runtimeChanged) {
    "YES"
} elseif ($comparisonUncertain) {
    "NO CONFIRMED CHANGE (INCOMPLETE BASELINE PIN)"
} else {
    "NO"
}
$comparisonCompleteness = if ($comparisonUncertain) { "INCOMPLETE" } else { "COMPLETE" }
$uploadResult = if ($uploadRequired) { "Upload the VLC source archive with this release." } else { "Do not upload another VLC source archive; reuse the previous release asset." }
$reason = if ($runtimeChanged) {
    "At least one tracked VLC runtime or build component changed."
} elseif ($comparisonUncertain) {
    if (-not $previousSourceAsset) {
        "The previous release does not link a separate VLC source asset, and its review does not record the FFmpeg commit pin. This is the first source asset; the runtime and reviewed dependency versions match."
    } else {
        "The previous release review does not record the FFmpeg commit pin, so exact source-input identity cannot be confirmed."
    }
} elseif (-not $previousSourceAsset) {
    "The previous release branch does not point to a separate VLC source archive."
} else {
    "The tracked runtime identity, selected plugins, dependency versions, and FFmpeg commit match the previous release."
}

$currentVersionText = Get-Content -LiteralPath (Join-Path $projectRoot "mix_browser\__init__.py") -Raw
if ($currentVersionText -notmatch ('(?m)^__version__\s*=\s*"' + [regex]::Escape($CurrentVersion) + '"')) {
    throw "The requested report version does not match mix_browser.__version__."
}
$componentNames = @($currentComponents.Keys + $baselineComponents.Keys | Sort-Object -Unique)
$componentRows = @(
    foreach ($component in $componentNames) {
        "| $component | $($baselineComponents[$component]) | $($currentComponents[$component]) |"
    }
)
$changeLines = if ($changes.Count) { $changes | ForEach-Object { "- $_" } } else { @("- No tracked runtime or dependency version changes.") }
$previousAssetLine = if ($previousSourceAsset) { $previousSourceAsset } else { "No separate VLC source asset is documented on the previous release branch." }
$reportLines = [Collections.Generic.List[string]]::new()
@(
    "# VLC Source Comparison",
    "",
    "- Candidate release: v$CurrentVersion",
    "- Previous release baseline: $baselineBranch ($($baselineCommit.Substring(0, 12)))",
    "- VLC runtime and reviewed dependency versions changed: **$changeResult**",
    "- Source pin comparison completeness: **$comparisonCompleteness**",
    "- FFmpeg source pin comparison: $commitComparison",
    "- VLC source archive upload decision: **$uploadResult**",
    "- Decision reason: $reason",
    "",
    "## Compared Inputs",
    "",
    "| Input | Previous release | Candidate |",
    "| --- | --- | --- |",
    "| VLC runtime version | $($baselineRuntime.Version) | $($currentRuntime.Version) |",
    "| VLC runtime SHA-256 | $($baselineRuntime.Sha256) | $($currentRuntime.Sha256) |",
    "| Selected plugins | $($baselinePlugins.Count) | $($currentPlugins.Count) |",
    "| Plugin list SHA-256 | $baselinePluginHash | $currentPluginHash |",
    "| FFmpeg commit pin | $(if ($baselineFfmpegCommit) { $baselineFfmpegCommit } else { 'not recorded' }) | $(if ($currentFfmpegCommit) { $currentFfmpegCommit } else { 'not recorded' }) |",
    "",
    "### Reviewed Dependency Versions",
    "",
    "| Component | Previous release | Candidate |",
    "| --- | --- | --- |"
) | ForEach-Object { $reportLines.Add($_) }
foreach ($componentRow in $componentRows) { $reportLines.Add($componentRow) }
@(
    "",
    "## VLC Source Asset",
    "",
    "Previous source asset: $previousAssetLine",
    "",
    "Changes found:"
) | ForEach-Object { $reportLines.Add($_) }
foreach ($changeLine in $changeLines) { $reportLines.Add($changeLine) }
@(
    "",
    "This report compares the candidate worktree with the previous archived release branch. It does not inspect a GitHub release's uploaded binary files."
) | ForEach-Object { $reportLines.Add($_) }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputFullPath) | Out-Null
[IO.File]::WriteAllLines($outputFullPath, $reportLines.ToArray(), [Text.UTF8Encoding]::new($false))
Write-Host "VLC source comparison report written to $outputFullPath" -ForegroundColor Green
