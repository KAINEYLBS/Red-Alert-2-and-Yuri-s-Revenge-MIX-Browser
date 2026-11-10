"""Compare bundled FFmpeg-related DLLs with the reviewed release record."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import urlopen


_BINARY_PREFIXES = (
    "ffmpeg",
    "avcodec",
    "avformat",
    "avutil",
    "avdevice",
    "avfilter",
    "postproc",
    "swresample",
    "swscale",
)


def _is_ffmpeg_binary(path: Path) -> bool:
    name = path.name.casefold()
    return path.suffix.casefold() == ".dll" and name.startswith(_BINARY_PREFIXES)


def _relative_binary_path(path: Path, scan_root: Path) -> str:
    if scan_root.name.casefold() == "pyside6":
        relative = path.relative_to(scan_root)
    else:
        parts = path.parts
        indexes = [index for index, part in enumerate(parts) if part.casefold() == "pyside6"]
        if not indexes:
            raise ValueError(f"FFmpeg binary is outside a PySide6 directory: {path}")
        relative = Path(*parts[indexes[-1] + 1 :])
    return relative.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _binary_hashes(scan_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in scan_root.rglob("*"):
        if not path.is_file() or not _is_ffmpeg_binary(path):
            continue
        relative = _relative_binary_path(path, scan_root)
        if relative in hashes:
            raise ValueError(f"Duplicate FFmpeg binary path after normalization: {relative}")
        hashes[relative] = _sha256(path)
    return dict(sorted(hashes.items()))


def _source_archives(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw_archives = record.get("source_archives")
    if not isinstance(raw_archives, list) or not raw_archives:
        raise ValueError("source_archives must list the corresponding source archives")

    archives = []
    seen_filenames = set()
    seen_license_filenames = set()
    for archive in raw_archives:
        if not isinstance(archive, dict):
            raise ValueError("each source archive record must be an object")
        name = archive.get("name")
        filename = archive.get("filename")
        url = archive.get("url")
        digest = archive.get("sha256")
        raw_license_files = archive.get("license_files")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(filename, str)
            or Path(filename).name != filename
            or not isinstance(url, str)
            or not url.startswith("https://")
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(raw_license_files, list)
            or not raw_license_files
        ):
            raise ValueError(
                "source archive records need a name, safe filename, HTTPS URL, SHA-256, "
                "and license_files"
            )
        if filename.casefold() in seen_filenames:
            raise ValueError(f"duplicate source archive filename: {filename}")
        seen_filenames.add(filename.casefold())
        license_files = []
        for license_file in raw_license_files:
            if not isinstance(license_file, dict):
                raise ValueError("each source license file record must be an object")
            archive_path = license_file.get("archive_path")
            license_filename = license_file.get("filename")
            license_digest = license_file.get("sha256")
            if (
                not isinstance(archive_path, str)
                or not archive_path
                or archive_path.startswith(("/", "\\"))
                or "\\" in archive_path
                or any(part in ("", ".", "..") for part in archive_path.split("/"))
                or not isinstance(license_filename, str)
                or Path(license_filename).name != license_filename
                or not isinstance(license_digest, str)
                or len(license_digest) != 64
                or any(character not in "0123456789abcdef" for character in license_digest)
            ):
                raise ValueError("source license files need a safe archive path, filename, and SHA-256")
            if license_filename.casefold() in seen_license_filenames:
                raise ValueError(f"duplicate source license filename: {license_filename}")
            seen_license_filenames.add(license_filename.casefold())
            license_files.append(
                {
                    "archive_path": archive_path,
                    "filename": license_filename,
                    "sha256": license_digest,
                }
            )
        archives.append(
            {
                "name": name,
                "filename": filename,
                "url": url,
                "sha256": digest,
                "license_files": license_files,
            }
        )
    return archives


def _extract_license_files(archive_path: Path, destination: Path, archive: dict[str, Any]) -> None:
    with tarfile.open(archive_path, mode="r:*") as source_archive:
        for license_file in archive["license_files"]:
            target = destination / license_file["filename"]
            if target.is_file() and _sha256(target) == license_file["sha256"]:
                continue

            member = source_archive.getmember(license_file["archive_path"])
            if not member.isfile():
                raise ValueError(f"source license entry is not a regular file: {license_file['archive_path']}")
            source_file = source_archive.extractfile(member)
            if source_file is None:
                raise ValueError(f"cannot read source license entry: {license_file['archive_path']}")

            temporary_path = None
            try:
                with source_file, tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=destination,
                    prefix=f"{target.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary_file:
                    temporary_path = Path(temporary_file.name)
                    digest = hashlib.sha256()
                    while chunk := source_file.read(1024 * 1024):
                        temporary_file.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != license_file["sha256"]:
                    raise ValueError(f"source license hash mismatch: {license_file['filename']}")
                os.replace(temporary_path, target)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)


def _prepare_sources(manifest_path: Path, destination: Path) -> int:
    try:
        record: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(record, dict)
            or record.get("schema_version") != 1
            or record.get("status") != "approved"
        ):
            print("FFmpeg source archives require an approved review record.", file=sys.stderr)
            return 1
        archives = _source_archives(record)
        destination.mkdir(parents=True, exist_ok=True)
        for archive in archives:
            target = destination / archive["filename"]
            if target.is_file() and _sha256(target) == archive["sha256"]:
                print(f"Using verified FFmpeg source archive: {archive['filename']}")
            else:
                temporary_path = None
                try:
                    print(f"Downloading FFmpeg source archive: {archive['filename']}", flush=True)
                    with tempfile.NamedTemporaryFile(
                        mode="wb",
                        dir=destination,
                        prefix=f"{target.name}.",
                        suffix=".tmp",
                        delete=False,
                    ) as temporary_file:
                        temporary_path = Path(temporary_file.name)
                        digest = hashlib.sha256()
                        with urlopen(archive["url"], timeout=60) as response:
                            content_length = response.headers.get("Content-Length")
                            total_bytes = int(content_length) if content_length and content_length.isdigit() else None
                            downloaded_bytes = 0
                            last_reported_mib = -1
                            while chunk := response.read(1024 * 1024):
                                temporary_file.write(chunk)
                                digest.update(chunk)
                                downloaded_bytes += len(chunk)
                                downloaded_mib = downloaded_bytes // (1024 * 1024)
                                if downloaded_mib != last_reported_mib:
                                    if total_bytes:
                                        progress = (
                                            f"{downloaded_bytes / (1024 * 1024):.1f} MiB downloaded "
                                            f"({downloaded_bytes / total_bytes:.0%})"
                                        )
                                    else:
                                        progress = f"{downloaded_bytes / (1024 * 1024):.1f} MiB downloaded"
                                    print(f"  {archive['filename']}: {progress}", flush=True)
                                    last_reported_mib = downloaded_mib
                    if digest.hexdigest() != archive["sha256"]:
                        raise ValueError(f"downloaded source archive hash mismatch: {archive['filename']}")
                    os.replace(temporary_path, target)
                finally:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
                print(f"Downloaded and verified FFmpeg source archive: {archive['filename']}")
            _extract_license_files(target, destination, archive)
            for license_file in archive["license_files"]:
                print(f"Prepared FFmpeg license: {license_file['filename']}")
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError, KeyError, EOFError) as error:
        print(f"Cannot prepare FFmpeg source archives: {error}", file=sys.stderr)
        return 1
    return 0


def _check_packaged_sources(record: dict[str, Any], package_root: Path) -> bool:
    try:
        archives = _source_archives(record)
    except ValueError as error:
        print(f"FFmpeg review source records are incomplete: {error}", file=sys.stderr)
        return False

    source_root = package_root / "licenses" / "FFmpeg"
    for archive in archives:
        source_path = source_root / archive["filename"]
        try:
            actual_hash = _sha256(source_path)
        except OSError:
            print(
                f"Required FFmpeg source archive is missing: {source_path}",
                file=sys.stderr,
            )
            return False
        if actual_hash != archive["sha256"]:
            print(
                f"Packaged FFmpeg source archive differs from the reviewed source: {archive['filename']}",
                file=sys.stderr,
            )
            return False
        for license_file in archive["license_files"]:
            license_path = source_root / license_file["filename"]
            try:
                license_hash = _sha256(license_path)
            except OSError:
                print(f"Required FFmpeg license file is missing: {license_path}", file=sys.stderr)
                return False
            if license_hash != license_file["sha256"]:
                print(
                    f"Packaged FFmpeg license differs from the reviewed source: {license_file['filename']}",
                    file=sys.stderr,
                )
                return False
    return True


def _report(scan_root: Path) -> int:
    hashes = _binary_hashes(scan_root)
    if not hashes:
        print(f"No FFmpeg-related DLLs found under: {scan_root}", file=sys.stderr)
        return 1
    print(json.dumps({"binaries_sha256": hashes}, indent=2))
    return 0


def _check(scan_root: Path, manifest_path: Path) -> int:
    try:
        record: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Cannot read FFmpeg review record: {error}", file=sys.stderr)
        return 1
    if not isinstance(record, dict):
        print("FFmpeg review record must contain a JSON object.", file=sys.stderr)
        return 1

    if record.get("schema_version") != 1 or record.get("status") != "approved":
        print("FFmpeg release review is not approved.", file=sys.stderr)
        try:
            _report(scan_root)
        except (OSError, ValueError) as error:
            print(f"Cannot inspect FFmpeg binaries: {error}", file=sys.stderr)
        return 1

    required_text = ("reviewed_on", "ffmpeg_runtime_version", "review_notes")
    missing = [
        key
        for key in required_text
        if not isinstance(record.get(key), str) or not record[key].strip()
    ]
    sources = record.get("license_sources")
    if (
        not isinstance(sources, list)
        or not sources
        or any(not isinstance(item, str) or not item.strip() for item in sources)
    ):
        missing.append("license_sources")
    if record.get("codec_configuration_reviewed") is not True:
        missing.append("codec_configuration_reviewed")
    if record.get("redistribution_obligations_reviewed") is not True:
        missing.append("redistribution_obligations_reviewed")
    try:
        _source_archives(record)
    except ValueError:
        missing.append("source_archives")
    if missing:
        print("FFmpeg review record is incomplete: " + ", ".join(missing), file=sys.stderr)
        return 1

    try:
        current_hashes = _binary_hashes(scan_root)
    except (OSError, ValueError) as error:
        print(f"Cannot inspect FFmpeg binaries: {error}", file=sys.stderr)
        return 1
    if not current_hashes:
        print(f"No FFmpeg-related DLLs found under: {scan_root}", file=sys.stderr)
        return 1

    reviewed_hashes = record.get("binaries_sha256")
    if not isinstance(reviewed_hashes, dict) or reviewed_hashes != current_hashes:
        print("FFmpeg binaries differ from the reviewed release record.", file=sys.stderr)
        print(json.dumps({"binaries_sha256": current_hashes}, indent=2))
        return 1
    if scan_root.name.casefold() != "pyside6" and not _check_packaged_sources(record, scan_root):
        return 1

    return 0


# @arch ra2ayrmb.ffmpeg-release-audit entrypoint | en: Checks FFmpeg binaries against the reviewed release record | zh: 将 FFmpeg 二进制与已审查的发布记录进行核对
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    report_parser = commands.add_parser("report", help="Print current FFmpeg-related DLL hashes as JSON")
    report_parser.add_argument("root", type=Path)
    check_parser = commands.add_parser("check", help="Require an approved record matching the DLL hashes")
    check_parser.add_argument("root", type=Path)
    check_parser.add_argument("manifest", type=Path)
    sources_parser = commands.add_parser(
        "prepare-sources",
        help="Download and verify the corresponding FFmpeg and codec source archives",
    )
    sources_parser.add_argument("manifest", type=Path)
    sources_parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    if args.command == "prepare-sources":
        return _prepare_sources(args.manifest.resolve(), args.destination.resolve())

    root = args.root.resolve()
    if not root.is_dir():
        print(f"Scan directory does not exist: {root}", file=sys.stderr)
        return 1
    if args.command == "report":
        return _report(root)
    return _check(root, args.manifest.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
