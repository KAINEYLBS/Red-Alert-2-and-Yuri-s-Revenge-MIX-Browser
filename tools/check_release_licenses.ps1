param(
    [string]$SourceTree,
    [string]$ReleaseDirectory
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
function Get-Sha256File([string]$path) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($path)
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "")
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

if (-not $SourceTree) {
    $SourceTree = $projectRoot
}
if (-not $ReleaseDirectory) {
    $ReleaseDirectory = Join-Path $projectRoot "release-artifacts"
}
$SourceTree = [IO.Path]::GetFullPath($SourceTree)
$ReleaseDirectory = [IO.Path]::GetFullPath($ReleaseDirectory)
$versionText = Get-Content -LiteralPath (Join-Path $projectRoot "mix_browser\__init__.py") -Raw
$versionMatch = [regex]::Match($versionText, '(?m)^__version__\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) {
    throw "Could not read the project version."
}
$version = $versionMatch.Groups[1].Value
$uploadDirectory = Join-Path $ReleaseDirectory "upload-v$version"
$reviewDirectory = Join-Path $ReleaseDirectory "review-v$version"

function Resolve-ReleaseArtifactPath([string]$filename) {
    $rootPath = Join-Path $ReleaseDirectory $filename
    if (Test-Path -LiteralPath $rootPath -PathType Leaf) {
        return $rootPath
    }
    $uploadPath = Join-Path $uploadDirectory $filename
    if (Test-Path -LiteralPath $uploadPath -PathType Leaf) {
        return $uploadPath
    }
    return $rootPath
}

$inventoryPath = Join-Path $SourceTree "tools\release_component_inventory.json"
if (-not (Test-Path -LiteralPath $inventoryPath -PathType Leaf)) {
    throw "The source tree is missing tools/release_component_inventory.json."
}
$projectInventoryPath = Join-Path $projectRoot "tools\release_component_inventory.json"
if ((Get-Sha256File $inventoryPath) -ine (Get-Sha256File $projectInventoryPath)) {
    throw "The exported source tree has a different component inventory from the release checker."
}
$inventory = Get-Content -LiteralPath $inventoryPath -Raw | ConvertFrom-Json

$sevenZip = Get-Command 7z.exe -ErrorAction SilentlyContinue
if ($sevenZip) {
    $sevenZipPath = $sevenZip.Source
} else {
    $candidates = @(
        (Join-Path $env:ProgramW6432 "7-Zip\7z.exe"),
        (Join-Path $env:ProgramFiles "7-Zip\7z.exe")
    )
    $sevenZipPath = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}
if (-not $sevenZipPath) {
    throw "7-Zip was not found. Install it or add 7z.exe to PATH."
}

$findings = [Collections.Generic.List[object]]::new()
function Add-Finding([string]$status, [string]$message) {
    $script:findings.Add([pscustomobject]@{ Status = $status; Message = $message })
}

function Test-RequiredFile([string]$root, [string]$relativePath, [string]$label) {
    $path = Join-Path $root ($relativePath -replace '/', '\')
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Add-Finding "PASS" "$label file exists: $relativePath"
    } else {
        Add-Finding "BLOCKED" "$label file is missing: $relativePath"
    }
}

function Get-ArchivePaths([string]$archivePath) {
    & $sevenZipPath t $archivePath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Archive integrity check failed: $archivePath"
    }
    $listing = & $sevenZipPath l -slt $archivePath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not list archive: $archivePath"
    }
    $archiveFull = [IO.Path]::GetFullPath($archivePath)
    return @(
        foreach ($line in $listing) {
            if ($line -match '^Path = (.*)$') {
                $entry = $Matches[1].Trim() -replace '\\', '/'
                if ($entry -and $entry -ne ($archiveFull -replace '\\', '/')) {
                    $entry
                }
            }
        }
    )
}

function Test-Archive([string]$artifactKey, [string]$label) {
    $artifact = $inventory.artifacts.$artifactKey
    $filename = $artifact.filename.Replace('{version}', $version)
    $path = Resolve-ReleaseArtifactPath $filename
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Add-Finding "BLOCKED" "$label archive is missing: $filename"
        return @()
    }
    try {
        $paths = @(Get-ArchivePaths $path)
        Add-Finding "PASS" "$label archive exists and passes 7-Zip integrity check: $filename"
        foreach ($required in $artifact.required_paths) {
            if ($paths -contains $required) {
                Add-Finding "PASS" "$label contains $required"
            } else {
                Add-Finding "BLOCKED" "$label is missing required file: $required"
            }
        }
        foreach ($pattern in $artifact.required_name_patterns) {
            if ($paths -contains $pattern) {
                Add-Finding "PASS" "$label contains pinned source input $pattern"
            } else {
                Add-Finding "BLOCKED" "$label is missing pinned source input: $pattern"
            }
        }
        return $paths
    } catch {
        Add-Finding "BLOCKED" "$label archive inspection failed: $_"
        return @()
    }
}

function Test-ArchiveFileMatches([string]$archivePath, [string]$label, [object[]]$items) {
    if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
        return
    }
    $temporaryRoot = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) ("ra2ayrmb-file-check-" + [Guid]::NewGuid().ToString("N"))))
    $temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $temporaryRoot.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to extract an archive file outside the temporary directory."
    }
    New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
    try {
        foreach ($item in $items) {
            $sourcePath = Join-Path $SourceTree ($item.SourcePath -replace '/', '\')
            if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
                Add-Finding "BLOCKED" "$label source comparison file is missing: $($item.SourcePath)"
                continue
            }
            & $sevenZipPath x -y ("-o" + $temporaryRoot) $archivePath $item.ArchivePath | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Add-Finding "BLOCKED" "$label could not extract the declared source/data file: $($item.ArchivePath)"
                continue
            }
            $extractedPath = [IO.Path]::GetFullPath((Join-Path $temporaryRoot ($item.ArchivePath -replace '/', '\')))
            $temporaryPrefix = $temporaryRoot.TrimEnd('\') + '\'
            if (-not $extractedPath.StartsWith($temporaryPrefix, [StringComparison]::OrdinalIgnoreCase) -or
                -not (Test-Path -LiteralPath $extractedPath -PathType Leaf)) {
                Add-Finding "BLOCKED" "$label extracted file is missing or escapes the temporary directory: $($item.ArchivePath)"
                continue
            }
            if ((Get-Sha256File $sourcePath) -ieq (Get-Sha256File $extractedPath)) {
                Add-Finding "PASS" "$label file matches the corresponding source: $($item.ArchivePath)"
            } else {
                Add-Finding "BLOCKED" "$label file differs from the corresponding source: $($item.ArchivePath)"
            }
        }
    } finally {
        $resolvedTemporary = [IO.Path]::GetFullPath($temporaryRoot)
        if ($resolvedTemporary.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $resolvedTemporary).StartsWith("ra2ayrmb-file-check-")) {
            Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
        }
    }
}

Write-Host "Release license artifact check for v$version"
Write-Host "Source tree: $SourceTree"
Write-Host "Release directory: $ReleaseDirectory"

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $python -PathType Leaf) {
    $phase = if ($SourceTree -ieq $projectRoot) { "source" } else { "export" }
    $sourceGate = Join-Path $SourceTree "tools\check_open_source_release.py"
    $gateArguments = @(
        $sourceGate,
        $phase,
        "--root",
        $SourceTree
    )
    if ($phase -eq "source") {
        $gateArguments += "--allow-dirty"
    }
    & $python @gateArguments
    if ($LASTEXITCODE -eq 0) {
        Add-Finding "PASS" "Exported source tree passed the repository export gate."
    } else {
        Add-Finding "BLOCKED" "Exported source tree failed tools/check_open_source_release.py."
    }
} else {
    Add-Finding "BLOCKED" "Project .venv Python was not found: $python"
}

foreach ($component in $inventory.components) {
    if (-not $component.id -or -not $component.name -or -not $component.license -or
        -not $component.scope -or -not $component.evidence -or -not $component.review) {
        Add-Finding "BLOCKED" "Component inventory row is incomplete: $($component | ConvertTo-Json -Compress)"
        continue
    }
    foreach ($evidence in $component.evidence) {
        Test-RequiredFile $SourceTree $evidence "Inventory evidence for $($component.name)"
    }
}

$xcc = $inventory.components | Where-Object id -eq "xcc-name-data" | Select-Object -First 1
if (-not $xcc -or $xcc.license -ne "GPL-3.0") {
    Add-Finding "BLOCKED" "XCC name data must be explicitly inventoried as GPL-3.0."
} else {
    $xccLicense = (Get-Content -LiteralPath (Join-Path $SourceTree "mix_browser\data\name_sources\xcc\COPYING") -TotalCount 4) -join "`n"
    if ($xccLicense -notmatch "GNU GENERAL PUBLIC LICENSE" -or $xccLicense -notmatch "Version 3") {
        Add-Finding "BLOCKED" "XCC COPYING does not identify GNU GPL version 3."
    } else {
        Add-Finding "PASS" "XCC name data and its GPL-3.0 license are explicitly checked."
    }
    foreach ($relativePath in $xcc.source_paths) {
        Test-RequiredFile $SourceTree $relativePath "XCC source tree"
    }
}

$sourcePaths = @(Test-Archive "source" "Project source")
$executablePaths = @(Test-Archive "executable" "Windows executable")
$vlcSourcePaths = @(Test-Archive "vlc_source" "VLC corresponding source")
$requiredProjectSourceArchives = @(
    "docs/licenses/CORRESPONDING_SOURCE_OFFER.txt",
    "tools/audit_release_binary.py",
    "tools/release_console.py",
    "tools/stage_release_upload.ps1",
    "tools/write_github_release_info.py",
    "tools/package_vlc_source.ps1",
    "tools/compare_vlc_release.ps1",
    "third_party/python-vlc/README.md",
    "third_party/python-vlc/vlc.py"
)
foreach ($requiredPath in $requiredProjectSourceArchives) {
    if ($sourcePaths -contains $requiredPath) {
        Add-Finding "PASS" "Project source archive contains release file: $requiredPath"
    } else {
        Add-Finding "BLOCKED" "Project source archive is missing release file: $requiredPath"
    }
}
if ($executablePaths -contains "RA2AYRMB/licenses/RA2AYRMB-GPL-2.0-or-later.txt") {
    Add-Finding "BLOCKED" "The executable archive includes the project's GPL-2.0 notice instead of selecting GPL-3.0 for this combined distribution."
}

$xccData = @(
    [pscustomobject]@{
        ArchivePath = "mix_browser/data/name_sources/xcc/COPYING"
        SourcePath = "mix_browser/data/name_sources/xcc/COPYING"
    },
    [pscustomobject]@{
        ArchivePath = "mix_browser/data/name_sources/xcc/ra2 mix description.txt"
        SourcePath = "mix_browser/data/name_sources/xcc/ra2 mix description.txt"
    },
    [pscustomobject]@{
        ArchivePath = "mix_browser/data/name_sources/xcc/td mix description.txt"
        SourcePath = "mix_browser/data/name_sources/xcc/td mix description.txt"
    },
    [pscustomobject]@{
        ArchivePath = "mix_browser/data/name_sources/xcc/ts mix description.txt"
        SourcePath = "mix_browser/data/name_sources/xcc/ts mix description.txt"
    }
)
$sourceArtifact = Resolve-ReleaseArtifactPath $inventory.artifacts.source.filename.Replace('{version}', $version)
Test-ArchiveFileMatches $sourceArtifact "Project source archive" $xccData
$executableXccData = @(
    [pscustomobject]@{
        ArchivePath = "RA2AYRMB/licenses/XCC/COPYING"
        SourcePath = "mix_browser/data/name_sources/xcc/COPYING"
    },
    [pscustomobject]@{
        ArchivePath = "RA2AYRMB/_internal/mix_browser/data/name_sources/xcc/ra2 mix description.txt"
        SourcePath = "mix_browser/data/name_sources/xcc/ra2 mix description.txt"
    },
    [pscustomobject]@{
        ArchivePath = "RA2AYRMB/_internal/mix_browser/data/name_sources/xcc/td mix description.txt"
        SourcePath = "mix_browser/data/name_sources/xcc/td mix description.txt"
    },
    [pscustomobject]@{
        ArchivePath = "RA2AYRMB/_internal/mix_browser/data/name_sources/xcc/ts mix description.txt"
        SourcePath = "mix_browser/data/name_sources/xcc/ts mix description.txt"
    }
)
$executableArtifact = Resolve-ReleaseArtifactPath $inventory.artifacts.executable.filename.Replace('{version}', $version)
Test-ArchiveFileMatches $executableArtifact "Windows executable archive" $executableXccData
$pythonVlc = $inventory.components | Where-Object id -eq "python-vlc" | Select-Object -First 1
if ($pythonVlc -and $pythonVlc.source_sha256) {
    $bindingSource = Join-Path $SourceTree "third_party\python-vlc\vlc.py"
    if (-not (Test-Path -LiteralPath $bindingSource -PathType Leaf)) {
        Add-Finding "BLOCKED" "The replaceable python-vlc source is missing from the source tree."
    } elseif ((Get-Sha256File $bindingSource) -ine $pythonVlc.source_sha256) {
        Add-Finding "BLOCKED" "The replaceable python-vlc source does not match the reviewed SHA-256."
    } else {
        Add-Finding "PASS" "The replaceable python-vlc source matches its reviewed SHA-256."
    }
    $bindingArchiveItems = @(
        [pscustomobject]@{
            ArchivePath = "third_party/python-vlc/vlc.py"
            SourcePath = "third_party/python-vlc/vlc.py"
        }
    )
    Test-ArchiveFileMatches $sourceArtifact "Project source archive" $bindingArchiveItems
    $bindingArchiveItems[0].ArchivePath = "RA2AYRMB/python-vlc/vlc.py"
    Test-ArchiveFileMatches $executableArtifact "Windows executable archive" $bindingArchiveItems
}
New-Item -ItemType Directory -Force -Path $reviewDirectory | Out-Null
$binaryAuditReport = Join-Path $reviewDirectory "Binary-component-audit-v$version.md"
$auditTemporaryRoot = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) ("ra2ayrmb-binary-audit-" + [Guid]::NewGuid().ToString("N"))))
$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
if (-not $auditTemporaryRoot.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to extract the release executable outside the temporary directory."
}
New-Item -ItemType Directory -Path $auditTemporaryRoot | Out-Null
try {
    if (-not (Test-Path -LiteralPath $executableArtifact -PathType Leaf)) {
        Add-Finding "BLOCKED" "The executable archive is unavailable for PyInstaller module inspection."
    } else {
        & $sevenZipPath x -y ("-o" + $auditTemporaryRoot) $executableArtifact "RA2AYRMB/RA2AYRMB.exe" | Out-Null
        $auditExecutable = Join-Path $auditTemporaryRoot "RA2AYRMB\RA2AYRMB.exe"
        $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
        $auditScript = Join-Path $projectRoot "tools\audit_release_binary.py"
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $auditExecutable -PathType Leaf)) {
            Add-Finding "BLOCKED" "The release executable could not be extracted from its archive for module inspection."
        } elseif (-not (Test-Path -LiteralPath $python -PathType Leaf) -or -not (Test-Path -LiteralPath $auditScript -PathType Leaf)) {
            Add-Finding "BLOCKED" "The project .venv Python or PyInstaller binary audit tool is missing."
        } else {
            & $python $auditScript --executable $auditExecutable --inventory $inventoryPath --output $binaryAuditReport
            if ($LASTEXITCODE -eq 0) {
                Add-Finding "PASS" "The final executable's PyInstaller modules and CArchive entries are classified: review-v$version/Binary-component-audit-v$version.md"
            } else {
                Add-Finding "BLOCKED" "The final executable has unclassified or forbidden frozen modules; see review-v$version/Binary-component-audit-v$version.md."
            }
        }
    }
} finally {
    if ($auditTemporaryRoot.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $auditTemporaryRoot).StartsWith("ra2ayrmb-binary-audit-")) {
        Remove-Item -LiteralPath $auditTemporaryRoot -Recurse -Force
    }
}
$distributionComponent = $inventory.components | Where-Object id -eq "windows-executable-distribution" | Select-Object -First 1
if (-not $distributionComponent -or $distributionComponent.license -ne "GPL-3.0") {
    Add-Finding "BLOCKED" "The Windows combined application must be explicitly inventoried as GPL-3.0."
}
$expectedVlcPlugins = @()
$pluginManifestPath = Join-Path $SourceTree "tools\vlc_runtime_plugins.txt"
if (Test-Path -LiteralPath $pluginManifestPath -PathType Leaf) {
    foreach ($plugin in Get-Content -LiteralPath $pluginManifestPath) {
        $plugin = $plugin.Trim()
        if (-not $plugin -or $plugin.StartsWith('#')) { continue }
        $archivePlugin = "RA2AYRMB/vlc/plugins/$plugin"
        $expectedVlcPlugins += $archivePlugin
        if ($executablePaths -contains $archivePlugin) {
            Add-Finding "PASS" "Windows package contains selected VLC plugin: $plugin"
        } else {
            Add-Finding "BLOCKED" "Windows package is missing selected VLC plugin: $plugin"
        }
    }
    $actualVlcPlugins = @($executablePaths | Where-Object { $_ -match '^RA2AYRMB/vlc/plugins/.+\.dll$' } | Sort-Object -Unique)
    $unexpectedVlcPlugins = @($actualVlcPlugins | Where-Object { $_ -notin $expectedVlcPlugins })
    if ($unexpectedVlcPlugins.Count -eq 0) {
        Add-Finding "PASS" "The packaged VLC plugin DLL set exactly matches the reviewed manifest."
    } else {
        foreach ($plugin in $unexpectedVlcPlugins) {
            Add-Finding "BLOCKED" "VLC plugin is packaged without an inventory entry: $plugin"
        }
    }
    if ($actualVlcPlugins -contains "RA2AYRMB/vlc/plugins/text_renderer/libfreetype_plugin.dll") {
        Add-Finding "BLOCKED" "The GPL FreeType VLC plugin is present although its GPL-2.0-only build dependency is incompatible with this GPL-3.0 combined distribution."
    } else {
        Add-Finding "PASS" "The VLC FreeType plugin and its GPL-2.0-only build dependency are absent."
    }
} else {
    Add-Finding "BLOCKED" "The source tree is missing the VLC runtime plugin manifest."
}
$distributionNoticeSource = "docs/licenses/RA2AYRMB-WINDOWS-DISTRIBUTION.txt"
$distributionNoticePath = Join-Path $SourceTree $distributionNoticeSource
if (Test-Path -LiteralPath $distributionNoticePath -PathType Leaf) {
    $distributionNoticeText = (Get-Content -LiteralPath $distributionNoticePath -Raw).ToLowerInvariant()
    foreach ($marker in @(
        "gpl-3.0",
        "gpl-2.0-or-later grant",
        "using the gpl-3.0 option",
        "not offered under the project's mit option",
        "does not offer the combined work under a later gpl version",
        "full gpl-3.0 text",
        "retain their own terms",
        "xcc mix name data",
        "gpl-3.0"
    )) {
        if ($distributionNoticeText.Contains($marker)) {
            Add-Finding "PASS" "Windows distribution notice identifies: $marker"
        } else {
            Add-Finding "BLOCKED" "Windows distribution notice is missing its scope statement: $marker"
        }
    }
    $distributionNoticeMatch = @(
        [pscustomobject]@{
            ArchivePath = "docs/licenses/RA2AYRMB-WINDOWS-DISTRIBUTION.txt"
            SourcePath = $distributionNoticeSource
        },
        [pscustomobject]@{
            ArchivePath = "docs/licenses/GPL-3.0.txt"
            SourcePath = "docs/licenses/GPL-3.0.txt"
        }
    )
    Test-ArchiveFileMatches $sourceArtifact "Project source archive" $distributionNoticeMatch
    $distributionNoticeMatch[0].ArchivePath = "RA2AYRMB/licenses/RA2AYRMB-WINDOWS-DISTRIBUTION.txt"
    $distributionNoticeMatch[1].ArchivePath = "RA2AYRMB/licenses/GPL-3.0.txt"
    Test-ArchiveFileMatches $executableArtifact "Windows executable archive" $distributionNoticeMatch
} else {
    Add-Finding "BLOCKED" "The source tree is missing the Windows executable distribution license notice."
}

foreach ($component in $inventory.components) {
    foreach ($notice in $component.binary_notices) {
        if ($executablePaths -contains $notice) {
            Add-Finding "PASS" "Windows package contains the notice for $($component.name): $notice"
        } else {
            Add-Finding "BLOCKED" "Windows package is missing the declared notice for $($component.name): $notice"
        }
    }
    foreach ($relativePath in $component.binary_paths) {
        if ($executablePaths -contains $relativePath) {
            Add-Finding "PASS" "Windows package contains the declared $($component.name) file: $relativePath"
        } else {
            Add-Finding "BLOCKED" "Windows package is missing the declared $($component.name) file: $relativePath"
        }
    }
}

$nativeFiles = @($executablePaths | Where-Object { $_ -match '(?i)\.(exe|dll|pyd|zip|pkg)$' } | Sort-Object -Unique)
$componentById = @{}
foreach ($component in $inventory.components) {
    $componentById[[string]$component.id] = $component
}
foreach ($nativeFile in $nativeFiles) {
    $rule = $inventory.binary_audit.binary_file_rules | Where-Object {
        [regex]::IsMatch($nativeFile, [string]$_.pattern, [Text.RegularExpressions.RegexOptions]::IgnoreCase)
    } | Select-Object -First 1
    if (-not $rule) {
        Add-Finding "BLOCKED" "Packaged binary or Python archive file is not classified: $nativeFile"
        continue
    }
    $owner = $componentById[[string]$rule.component]
    if (-not $owner) {
        Add-Finding "BLOCKED" "Binary inventory rule references an unknown component: $($rule.component)"
        continue
    }
    Add-Finding "PASS" "Packaged file classified as $($owner.name) ($($owner.license)): $nativeFile"
}

$offerPath = Join-Path $SourceTree "docs\licenses\VLC\SOURCE_CODE_OFFER.txt"
if (Test-Path -LiteralPath $offerPath -PathType Leaf) {
    $offer = Get-Content -LiteralPath $offerPath -Raw
    $assetMatch = [regex]::Match($offer, 'https://github\.com/[^\s)]+/releases/download/[^\s)]+/(?<asset>RA2AYRMB-vlc-source-[^\s)]+\.7z)')
    if (-not $assetMatch.Success) {
        Add-Finding "BLOCKED" "The VLC source offer does not point to a versioned GitHub release asset."
    } else {
        $assetPath = Resolve-ReleaseArtifactPath $assetMatch.Groups["asset"].Value
        if (Test-Path -LiteralPath $assetPath -PathType Leaf) {
            Add-Finding "PASS" "The VLC source offer points to a locally built release asset: $($assetMatch.Groups['asset'].Value)"
        } else {
            Add-Finding "BLOCKED" "The VLC source offer asset is not present in the release output: $($assetMatch.Groups['asset'].Value)"
        }
    }
    if ($offer -notmatch "at least three years" -or
        $offer -notmatch "at no charge" -or
        $offer -notmatch "issues") {
        Add-Finding "BLOCKED" "The VLC source offer is missing its duration, no-charge, or request-route terms."
    }
}

$vlcSourceArtifact = Resolve-ReleaseArtifactPath $inventory.artifacts.vlc_source.filename
if (Test-Path -LiteralPath $vlcSourceArtifact -PathType Leaf) {
    $temporaryRoot = [IO.Path]::GetFullPath((Join-Path ([IO.Path]::GetTempPath()) ("ra2ayrmb-license-check-" + [Guid]::NewGuid().ToString("N"))))
    $temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $temporaryRoot.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to extract the VLC source archive outside the temporary directory."
    }
    New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
    try {
        & $sevenZipPath x -y ("-o" + $temporaryRoot) $vlcSourceArtifact | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Add-Finding "BLOCKED" "The VLC source archive could not be extracted for internal checksum verification."
        } else {
            $manifestPath = Join-Path $temporaryRoot "RA2AYRMB-vlc-source-3.0.24\SHA256SUMS.txt"
            if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
                Add-Finding "BLOCKED" "The VLC source archive has no internal SHA256SUMS.txt."
            } else {
                $manifestRoot = Split-Path -Parent $manifestPath
                $manifestEntries = Get-Content -LiteralPath $manifestPath | Where-Object { $_ -and $_ -ne "SHA-256  File" }
                foreach ($line in $manifestEntries) {
                    if ($line -notmatch '^(?<hash>[0-9a-fA-F]{64})  (?<path>.+)$') {
                        Add-Finding "BLOCKED" "Malformed VLC source checksum line: $line"
                        continue
                    }
                    $relative = $Matches["path"] -replace '/', '\'
                    $filePath = [IO.Path]::GetFullPath((Join-Path $manifestRoot $relative))
                    $manifestRootPrefix = [IO.Path]::GetFullPath($manifestRoot).TrimEnd('\') + '\'
                    if (-not $filePath.StartsWith($manifestRootPrefix, [StringComparison]::OrdinalIgnoreCase) -or
                        -not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
                        Add-Finding "BLOCKED" "VLC source checksum entry is missing or escapes the archive root: $relative"
                        continue
                    }
                    $actualHash = Get-Sha256File $filePath
                    if ($actualHash -ieq $Matches["hash"]) {
                        Add-Finding "PASS" "VLC source input checksum matches: $relative"
                    } else {
                        Add-Finding "BLOCKED" "VLC source input checksum mismatch: $relative"
                    }
                }
            }
        }
    } catch {
        Add-Finding "BLOCKED" "VLC source checksum verification failed: $_"
    } finally {
        $resolvedTemporary = [IO.Path]::GetFullPath($temporaryRoot)
        if ($resolvedTemporary.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase) -and
            (Split-Path -Leaf $resolvedTemporary).StartsWith("ra2ayrmb-license-check-")) {
            Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
        }
    }
}

$reportPath = Join-Path $reviewDirectory "License-artifact-check-v$version.md"
$blockedCount = @($findings | Where-Object Status -eq "BLOCKED").Count
$automatedStatus = if ($blockedCount -gt 0) { "BLOCKED" } else { "PASS" }
$releaseReadiness = if ($blockedCount -gt 0) { "BLOCKED" } else { "READY TO PUBLISH" }
$report = [Collections.Generic.List[string]]::new()
$report.Add("# Release License Artifact Check")
$report.Add("")
$report.Add("- Candidate: v$version")
$report.Add("- Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')")
$report.Add("- Source tree: ``$SourceTree``")
$report.Add("- Release directory: ``$ReleaseDirectory``")
$report.Add("- Automated artifact status: **$automatedStatus**")
$report.Add("- Local release readiness: **$releaseReadiness**")
$report.Add("")
$report.Add("## Artifact Checks")
$report.Add("")
$report.Add("| Status | Finding |")
$report.Add("| --- | --- |")
foreach ($finding in $findings) {
    $escaped = $finding.Message.Replace('|', '\|')
    $report.Add("| $($finding.Status) | $escaped |")
}
$report.Add("")
$report.Add("## Component Inventory")
$report.Add("")
$report.Add("| Component | License | Distribution scope | Verification basis |")
$report.Add("| --- | --- | --- | --- |")
foreach ($component in $inventory.components) {
    $scope = ([string]$component.scope).Replace('|', '\|')
    $verification = ([string]$component.review).Replace('|', '\|')
    $report.Add("| $($component.name) | $($component.license) | $scope | $verification |")
}
$report.Add("")
$report.Add("## Packaged Binary and Python Archive Files")
$report.Add("")
if ($nativeFiles.Count -eq 0) {
    $report.Add("No EXE, DLL, PYD, ZIP, or PKG entries were found in the executable archive, or the archive is unavailable.")
} else {
    $report.Add("| Path | Component | License |")
    $report.Add("| --- | --- | --- |")
    foreach ($nativeFile in $nativeFiles) {
        $rule = $inventory.binary_audit.binary_file_rules | Where-Object {
            [regex]::IsMatch($nativeFile, [string]$_.pattern, [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        } | Select-Object -First 1
        $owner = if ($rule) { $componentById[[string]$rule.component] } else { $null }
        $componentName = if ($owner) { $owner.name } else { "UNCLASSIFIED" }
        $licenseName = if ($owner) { $owner.license } else { "UNCLASSIFIED" }
        $report.Add("| ``$nativeFile`` | $componentName | $licenseName |")
    }
}
$report.Add("")
$report.Add("## Post-Publication Check")
$report.Add("")
foreach ($check in $inventory.post_publication_checks) {
    $report.Add("- $check")
}
$report.Add("")
$report.Add("This release gate reads the exact local source, executable, and VLC source archives. It classifies every packaged EXE, DLL, PYD, ZIP, and PKG, parses the PyInstaller module archive, checks the source offers and embedded source checksums, and blocks unclassified components.")
[IO.File]::WriteAllLines($reportPath, $report.ToArray(), [Text.UTF8Encoding]::new($false))

Write-Host ""
if ($blockedCount -gt 0) {
    Write-Host "Automated artifact findings: $($findings.Count - $blockedCount) passed, $blockedCount blocked." -ForegroundColor Red
    Write-Host "Local release readiness: $releaseReadiness." -ForegroundColor Red
} else {
    Write-Host "Automated artifact findings: $($findings.Count) passed, 0 blocked." -ForegroundColor Green
    Write-Host "Local release readiness: $releaseReadiness." -ForegroundColor Green
}
Write-Host "Component-by-component report: $reportPath" -ForegroundColor Green
if ($blockedCount -gt 0) {
    exit 1
}
exit 0
