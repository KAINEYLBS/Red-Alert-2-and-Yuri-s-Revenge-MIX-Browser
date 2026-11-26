param(
    [Parameter(Mandatory = $true)]
    [string]$SevenZipPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
if ($null -eq $curl) {
    throw "curl.exe is required to download and resume release source inputs."
}
$cacheRoot = Join-Path $projectRoot ".release-cache\vlc-source"
$downloadRoot = Join-Path $cacheRoot "downloads"
$workRoot = Join-Path $cacheRoot "work"
$vlcArchiveName = "vlc-3.0.24.tar.xz"
$vlcArchivePath = Join-Path $downloadRoot $vlcArchiveName
$vlcSourceRoot = Join-Path $workRoot "vlc-3.0.24"
$vlcSha256 = "e7cab503d1d7d5849b89d2cf0e1ee60d0ef6d012407791b644b9cfc0cc225fdf"
$vlcSourceUrl = "https://download.videolan.org/pub/videolan/vlc/3.0.24/$vlcArchiveName"
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "release-artifacts")).TrimEnd('\')
$outputFullPath = [IO.Path]::GetFullPath($OutputPath)

function Get-FileDigest([string]$path, [string]$algorithmName) {
    $algorithm = switch ($algorithmName) {
        "SHA256" { [Security.Cryptography.SHA256]::Create() }
        "SHA512" { [Security.Cryptography.SHA512]::Create() }
        default { throw "Unsupported digest algorithm: $algorithmName" }
    }
    $stream = [IO.File]::OpenRead($path)
    try {
        return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } finally {
        $stream.Dispose()
        $algorithm.Dispose()
    }
}

if (-not $outputFullPath.StartsWith($releaseRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "The VLC source archive must be written inside the project release-artifacts directory."
}
if (-not (Test-Path -LiteralPath $SevenZipPath -PathType Leaf)) {
    throw "7-Zip was not found: $SevenZipPath"
}

New-Item -ItemType Directory -Force -Path $downloadRoot, $workRoot | Out-Null
if (-not (Test-Path -LiteralPath $vlcArchivePath -PathType Leaf)) {
    $partialVlcArchive = "$vlcArchivePath.download"
    Write-Host "Downloading VLC 3.0.24 source..."
    if (-not (Test-Path -LiteralPath $partialVlcArchive -PathType Leaf)) {
        New-Item -ItemType File -Path $partialVlcArchive | Out-Null
    }
    & $curl.Source -C - -L --fail --retry 8 --retry-all-errors --retry-delay 2 --connect-timeout 20 --progress-bar --output $partialVlcArchive $vlcSourceUrl
    if ($LASTEXITCODE -ne 0) {
        throw "VLC source download was interrupted; the partial file is cached for resuming."
    }
    $downloadedVlcSha256 = Get-FileDigest $partialVlcArchive "SHA256"
    if ($downloadedVlcSha256 -ne $vlcSha256) {
        Remove-Item -LiteralPath $partialVlcArchive -Force
        throw "VLC source SHA-256 mismatch. Expected $vlcSha256, got $downloadedVlcSha256."
    }
    Move-Item -LiteralPath $partialVlcArchive -Destination $vlcArchivePath
}
$actualVlcSha256 = Get-FileDigest $vlcArchivePath "SHA256"
if ($actualVlcSha256 -ne $vlcSha256) {
    throw "VLC source SHA-256 mismatch. Expected $vlcSha256, got $actualVlcSha256."
}

if (-not (Test-Path -LiteralPath $vlcSourceRoot -PathType Container)) {
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($null -eq $tar) {
        throw "tar.exe is required to extract the verified VLC source archive."
    }
    & $tar.Source -xf $vlcArchivePath -C $workRoot
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $vlcSourceRoot -PathType Container)) {
        throw "Could not extract the VLC 3.0.24 source archive."
    }
}

$sourcePackages = @(
    @{ Name = "zlib-1.3.2.tar.xz"; Package = "zlib"; Urls = @("https://github.com/madler/zlib/releases/download/v1.3.2/zlib-1.3.2.tar.xz") },
    @{ Name = "libgsm_1.0.13.tar.gz"; Package = "gsm"; Urls = @("https://archive.ubuntu.com/ubuntu/pool/universe/libg/libgsm/libgsm_1.0.13.orig.tar.gz") },
    @{ Name = "openjpeg-2.5.4.tar.gz"; Package = "openjpeg"; Urls = @("https://codeload.github.com/uclouvain/openjpeg/tar.gz/refs/tags/v2.5.4") },
    @{ Name = "libsamplerate-0.1.9.tar.gz"; Package = "samplerate"; Urls = @("https://www.mega-nerd.com/SRC/libsamplerate-0.1.9.tar.gz") },
    @{ Name = "mingw-w64-v14.0.0.tar.bz2"; Package = "mingw64"; Urls = @("https://downloads.sourceforge.net/mingw-w64/mingw-w64/mingw-w64-release/mingw-w64-v14.0.0.tar.bz2") }
)

foreach ($sourcePackage in $sourcePackages) {
    $checksumFile = Join-Path $vlcSourceRoot "contrib\src\$($sourcePackage.Package)\SHA512SUMS"
    if (-not (Test-Path -LiteralPath $checksumFile -PathType Leaf)) {
        throw "The VLC source tree is missing the checksum list for $($sourcePackage.Package)."
    }
    $checksumPattern = "^(?<hash>[0-9A-Fa-f]{128})\s+$([regex]::Escape($sourcePackage.Name))\s*$"
    $checksumLine = Get-Content -LiteralPath $checksumFile | Where-Object { [regex]::IsMatch($_, $checksumPattern) } | Select-Object -First 1
    if (-not $checksumLine) {
        throw "The VLC checksum list does not pin $($sourcePackage.Name)."
    }
    $checksumMatch = [regex]::Match($checksumLine, $checksumPattern)
    $expectedSha512 = $checksumMatch.Groups["hash"].Value.ToLowerInvariant()
    $cachedArchive = Join-Path $downloadRoot $sourcePackage.Name

    if (Test-Path -LiteralPath $cachedArchive -PathType Leaf) {
        $cachedSha512 = Get-FileDigest $cachedArchive "SHA512"
        if ($cachedSha512 -ne $expectedSha512) {
            Remove-Item -LiteralPath $cachedArchive -Force
        }
    }
    if (-not (Test-Path -LiteralPath $cachedArchive -PathType Leaf)) {
        $downloaded = $false
        foreach ($url in $sourcePackage.Urls) {
            $partialPath = "$cachedArchive.download"
            try {
                Write-Host "Downloading $($sourcePackage.Name)..."
                if (-not (Test-Path -LiteralPath $partialPath -PathType Leaf)) {
                    New-Item -ItemType File -Path $partialPath | Out-Null
                }
                & $curl.Source -C - -L --fail --retry 8 --retry-all-errors --retry-delay 2 --connect-timeout 20 --progress-bar --output $partialPath $url
                if ($LASTEXITCODE -ne 0) {
                    throw "Download was interrupted; the partial file is cached for resuming."
                }
                $downloadedSha512 = Get-FileDigest $partialPath "SHA512"
                if ($downloadedSha512 -ne $expectedSha512) {
                    Remove-Item -LiteralPath $partialPath -Force
                    throw "SHA-512 mismatch for $($sourcePackage.Name)."
                }
                Move-Item -LiteralPath $partialPath -Destination $cachedArchive
                $downloaded = $true
                break
            } catch {
                if ($url -eq $sourcePackage.Urls[-1]) {
                    throw "Could not obtain verified source $($sourcePackage.Name): $_"
                }
            }
        }
        if (-not $downloaded) {
            throw "Could not obtain verified source $($sourcePackage.Name)."
        }
    }
}

$ffmpegCommit = "71fb6132637a2a430375c24afc381fff8b854fe7"
$ffmpegCommitArchive = Join-Path $downloadRoot "ffmpeg-vlc-commit-$ffmpegCommit-code-ffmpeg.tar.gz"
$ffmpegCommitUrl = "https://code.ffmpeg.org/FFmpeg/FFmpeg/archive/$ffmpegCommit.tar.gz"
$ffmpegCommitHashPath = "$ffmpegCommitArchive.sha256"
if (Test-Path -LiteralPath $ffmpegCommitArchive -PathType Leaf) {
    $cachedFfmpegSha256 = Get-FileDigest $ffmpegCommitArchive "SHA256"
    if ((Test-Path -LiteralPath $ffmpegCommitHashPath -PathType Leaf) -and
        (Get-Content -LiteralPath $ffmpegCommitHashPath -Raw).Trim().ToLowerInvariant() -ne $cachedFfmpegSha256) {
        Remove-Item -LiteralPath $ffmpegCommitArchive -Force
        Remove-Item -LiteralPath $ffmpegCommitHashPath -Force
    }
}
if (-not (Test-Path -LiteralPath $ffmpegCommitArchive -PathType Leaf)) {
    $partialFfmpegArchive = "$ffmpegCommitArchive.download"
    if (-not (Test-Path -LiteralPath $partialFfmpegArchive -PathType Leaf)) {
        New-Item -ItemType File -Path $partialFfmpegArchive | Out-Null
    }
    Write-Host "Downloading FFmpeg source commit $ffmpegCommit..."
    & $curl.Source -C - -L --fail --retry 8 --retry-all-errors --retry-delay 2 --connect-timeout 20 --progress-bar --output $partialFfmpegArchive $ffmpegCommitUrl
    if ($LASTEXITCODE -ne 0) {
        throw "FFmpeg source download was interrupted; the partial file is cached for resuming."
    }
    Move-Item -LiteralPath $partialFfmpegArchive -Destination $ffmpegCommitArchive
}
$ffmpegCommitSha256 = Get-FileDigest $ffmpegCommitArchive "SHA256"
[IO.File]::WriteAllText($ffmpegCommitHashPath, $ffmpegCommitSha256, [Text.UTF8Encoding]::new($false))

$stagingRoot = Join-Path $cacheRoot ("staging-" + [Guid]::NewGuid().ToString("N"))
$bundleName = "RA2AYRMB-vlc-source-3.0.24"
$bundleRoot = Join-Path $stagingRoot $bundleName
$vlcInputRoot = Join-Path $bundleRoot "VLC"
$dependencyRoot = Join-Path $bundleRoot "Dependencies"
New-Item -ItemType Directory -Force -Path $vlcInputRoot, $dependencyRoot | Out-Null
Copy-Item -LiteralPath $vlcArchivePath -Destination (Join-Path $vlcInputRoot $vlcArchiveName)

$manifestLines = @("SHA-256  File")
foreach ($sourcePackage in $sourcePackages) {
    $cachedArchive = Join-Path $downloadRoot $sourcePackage.Name
    Copy-Item -LiteralPath $cachedArchive -Destination (Join-Path $dependencyRoot $sourcePackage.Name)
    $sha256 = Get-FileDigest $cachedArchive "SHA256"
    $manifestLines += "$sha256  Dependencies/$($sourcePackage.Name)"
}
$ffmpegCommitFile = Split-Path -Leaf $ffmpegCommitArchive
Copy-Item -LiteralPath $ffmpegCommitArchive -Destination (Join-Path $dependencyRoot $ffmpegCommitFile)
$manifestLines += "$ffmpegCommitSha256  Dependencies/$ffmpegCommitFile"
$manifestLines += "$(Get-FileDigest $vlcArchivePath 'SHA256')  VLC/$vlcArchiveName"
[IO.File]::WriteAllLines((Join-Path $bundleRoot "SHA256SUMS.txt"), $manifestLines, [Text.UTF8Encoding]::new($false))

$readmeLines = @(
    "RA2AYRMB corresponding source for the VLC 3.0.24 Windows runtime.",
    "",
    "VLC/ contains the complete upstream VLC 3.0.24 source archive.",
    "Dependencies/ contains the source archives identified by the VLC 3.0.24 contribution rules for the selected runtime plugins:",
    "  FFmpeg 8.1.2 at commit 71fb6132637a2a430375c24afc381fff8b854fe7, zlib 1.3.2, GSM 1.0.13, OpenJPEG 2.5.4, libsamplerate 0.1.9, and MinGW-w64 14.0.0 winpthreads.",
    "The VLC source archive contains the corresponding contribution recipes, patches, and build configuration. Its contrib/src/*/SHA512SUMS files provide upstream SHA-512 values for dependency archives. The FFmpeg archive is an immutable upstream snapshot for the pinned Git commit.",
    "",
    "VLC source: https://download.videolan.org/pub/videolan/vlc/3.0.24/vlc-3.0.24.tar.xz",
    "Dependency source locations are recorded in the matching VLC contrib/src/*/rules.mak files.",
    "Use SHA256SUMS.txt to verify the files in this archive."
)
[IO.File]::WriteAllLines((Join-Path $bundleRoot "README.txt"), $readmeLines, [Text.UTF8Encoding]::new($false))

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $outputFullPath) | Out-Null
if (Test-Path -LiteralPath $outputFullPath -PathType Leaf) {
    Remove-Item -LiteralPath $outputFullPath -Force
}
Push-Location $stagingRoot
try {
    & $SevenZipPath a -t7z -mx=9 -mmt=on $outputFullPath $bundleName
    if ($LASTEXITCODE -ne 0) {
        throw "7-Zip could not create the VLC source archive."
    }
} finally {
    Pop-Location
}
& $SevenZipPath t $outputFullPath
if ($LASTEXITCODE -ne 0) {
    throw "The VLC source archive did not pass its integrity check."
}

$resolvedCacheRoot = [IO.Path]::GetFullPath($cacheRoot).TrimEnd('\')
$resolvedStagingRoot = [IO.Path]::GetFullPath($stagingRoot)
if ($resolvedStagingRoot.StartsWith($resolvedCacheRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $resolvedStagingRoot -Recurse -Force
}
Write-Host "VLC source archive SHA-256: $(Get-FileDigest $outputFullPath 'SHA256')" -ForegroundColor Green
