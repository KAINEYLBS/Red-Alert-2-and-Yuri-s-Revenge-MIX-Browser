"""Classify Python modules embedded in the Windows release executable."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from release_console import write_status


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(executable: Path, inventory_path: Path) -> tuple[list[str], list[str]]:
    from PyInstaller.archive.readers import CArchiveReader

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    policy = inventory["binary_audit"]
    components = {row["id"]: row for row in inventory["components"]}
    archive = CArchiveReader(str(executable))
    pyz_names = [name for name, entry in archive.toc.items() if entry[-1] == "z"]
    errors: list[str] = []
    if pyz_names != ["PYZ.pyz"]:
        errors.append(f"Expected one PYZ.pyz archive, found: {pyz_names!r}")
        modules: list[str] = []
    else:
        modules = sorted(archive.open_embedded_archive("PYZ.pyz").toc)

    module_roots: dict[str, str] = policy["module_roots"]
    expected_roots = set(policy["expected_module_roots"])
    forbidden_roots = {name.casefold() for name in policy["forbidden_module_roots"]}
    encountered = {name.split(".", 1)[0] for name in modules}
    standard_roots = set(sys.stdlib_module_names)
    standard_roots.add("__future__")

    unknown_roots = sorted(
        root for root in encountered
        if root not in module_roots and root not in standard_roots
    )
    missing_roots = sorted(expected_roots - encountered)
    forbidden = sorted(root for root in encountered if root.casefold() in forbidden_roots)
    if unknown_roots:
        errors.append(f"Unclassified frozen third-party module roots: {', '.join(unknown_roots)}")
    if missing_roots:
        errors.append(f"Expected frozen module roots are absent: {', '.join(missing_roots)}")
    if forbidden:
        errors.append(f"Forbidden module roots are frozen into the EXE: {', '.join(forbidden)}")

    counts: Counter[str] = Counter()
    modules_by_owner: dict[str, list[str]] = defaultdict(list)
    for name in modules:
        root = name.split(".", 1)[0]
        owner = module_roots.get(root, "python-standard-library")
        counts[owner] += 1
        modules_by_owner[owner].append(name)

    carchive_rows: list[tuple[str, str]] = []
    for name, entry in sorted(archive.toc.items()):
        kind = entry[-1]
        if name == "PYZ.pyz":
            owner = "PyInstaller PYZ archive"
        elif name == "main":
            owner = "project-application"
        elif name == "struct":
            owner = "python-standard-library"
        elif name.startswith(("pyimod", "pyi_rth", "pyiboot")):
            owner = "pyinstaller-runtime"
        else:
            errors.append(f"Unclassified PyInstaller CArchive entry: {name} ({kind})")
            owner = "UNCLASSIFIED"
        carchive_rows.append((name, owner))

    lines = [
        "# Executable Binary Audit",
        "",
        f"- Executable: `{executable}`",
        f"- SHA-256: `{_sha256(executable)}`",
        f"- PyInstaller CArchive entries: {len(archive.toc)}",
        f"- Frozen PYZ modules: {len(modules)}",
        f"- Unclassified module roots: {len(unknown_roots)}",
        f"- Forbidden frozen module roots: {len(forbidden)}",
        "",
        "## Frozen Module Components",
        "",
        "| Component | License | Module count |",
        "| --- | --- | ---: |",
    ]
    for owner, count in sorted(counts.items()):
        if owner == "python-standard-library":
            label, license_name = "CPython standard library", "Python Software Foundation License"
        else:
            component = components[owner]
            label, license_name = component["name"], component["license"]
        lines.append(f"| {label} | {license_name} | {count} |")

    lines.extend(["", "## Non-Standard Frozen Modules", ""])
    for owner in sorted(set(modules_by_owner) - {"python-standard-library"}):
        if owner in components:
            label = components[owner]["name"]
        else:
            label = owner
        lines.extend([f"### {label}", "", "```text"])
        lines.extend(modules_by_owner[owner])
        lines.extend(["```", ""])

    lines.extend(["## PyInstaller CArchive Entries", "", "| Entry | Classification |", "| --- | --- |"])
    for name, owner in carchive_rows:
        lines.append(f"| `{name}` | {owner} |")

    lines.extend(["", "## Findings", ""])
    if errors:
        lines.extend(f"- BLOCKED: {error}" for error in errors)
    else:
        lines.append("All frozen module roots and PyInstaller archive entries are classified; the replaceable `vlc` binding is not frozen.")
    lines.append("")
    return lines, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        report, errors = audit(args.executable.resolve(), args.inventory.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(report), encoding="utf-8")
    except Exception as exc:
        write_status(f"Binary audit failed: {exc}", "red", stream=sys.stderr)
        return 2

    for error in errors:
        write_status(f"BLOCKED: {error}", "red", stream=sys.stderr)
    if errors:
        return 1
    write_status(f"Executable module audit passed: {args.output}", "green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
