"""Check Qt translation coverage and compile validated catalogs."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


_EXCLUDED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    ".venv",
    ".pyinstaller-work",
    ".release-cache",
    "__pycache__",
    "build",
    "dist",
    "reference_tool_temp",
}
_PLACEHOLDER_PATTERN = re.compile(r"\{[^{}]+\}|%L?\d+|%n")
_NUMBER_PATTERN = re.compile(r"\d[\d,._]*\d|\d+")


def _tool_path(name: str) -> Path:
    executable = f"{name}.exe" if os.name == "nt" else name
    return Path(sys.executable).resolve().parent / executable


def _source_files(project_root: Path) -> list[Path]:
    return sorted(
        path
        for path in project_root.rglob("*.py")
        if not any(part in _EXCLUDED_DIRECTORIES for part in path.relative_to(project_root).parts)
    )


def _read_catalog(path: Path) -> dict[tuple[str, str, str], tuple[ET.Element, ET.Element]]:
    root = ET.parse(path).getroot()
    messages: dict[tuple[str, str, str], tuple[ET.Element, ET.Element]] = {}
    for context in root.findall("context"):
        context_name = context.findtext("name", default="")
        for message in context.findall("message"):
            source = message.findtext("source", default="")
            comment = message.findtext("comment", default="")
            translation = message.find("translation")
            if translation is None:
                continue
            if translation.get("type") in {"obsolete", "vanished"}:
                continue
            messages[(context_name, source, comment)] = (message, translation)
    return messages


def _element_text(element: ET.Element) -> str:
    return "".join(element.itertext())


def _translation_units(translation: ET.Element) -> list[str]:
    plural_forms = translation.findall("numerusform")
    if plural_forms:
        return [_element_text(form) for form in plural_forms]
    return [_element_text(translation)]


def _placeholder_counts(text: str) -> Counter[str]:
    return Counter(_PLACEHOLDER_PATTERN.findall(text))


def _significant_numbers(text: str) -> Counter[str]:
    without_placeholders = _PLACEHOLDER_PATTERN.sub("", text)
    values = Counter()
    for value in _NUMBER_PATTERN.findall(without_placeholders):
        normalized = value.replace(",", "").replace("_", "")
        if sum(character.isdigit() for character in normalized) >= 4:
            values[normalized] += 1
    return values


def _short_source(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _validate_catalog(
    source_messages: dict[tuple[str, str, str], ET.Element],
    catalog_path: Path,
) -> list[str]:
    catalog = _read_catalog(catalog_path)
    failures: list[str] = []
    for key, source_message in source_messages.items():
        context, source, _comment = key
        entry = catalog.get(key)
        if entry is None:
            failures.append(f"Missing [{context}] {_short_source(source)}")
            continue

        message, translation = entry
        units = _translation_units(translation)
        if translation.get("type") == "unfinished" or not units or any(not unit.strip() for unit in units):
            failures.append(f"Unfinished [{context}] {_short_source(source)}")
            continue

        source_placeholders = _placeholder_counts(source)
        for unit in units:
            if _placeholder_counts(unit) != source_placeholders:
                failures.append(f"Placeholder mismatch [{context}] {_short_source(source)}")
                break

        required_numbers = _significant_numbers(source)
        if required_numbers and any(
            not required_numbers <= _significant_numbers(unit) for unit in units
        ):
            failures.append(f"Numeric value missing from translation [{context}] {_short_source(source)}")

    return failures


def _extract_source_messages(
    project_root: Path,
    source_files: list[Path],
    lupdate: Path,
    temporary_directory: Path,
) -> dict[tuple[str, str, str], ET.Element]:
    extracted_path = temporary_directory / "source_messages.ts"
    command = [
        str(lupdate),
        *(str(path) for path in source_files),
        "-ts",
        str(extracted_path),
    ]
    result = subprocess.run(
        command,
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise RuntimeError("pyside6-lupdate failed")

    messages: dict[tuple[str, str, str], ET.Element] = {}
    root = ET.parse(extracted_path).getroot()
    for context in root.findall("context"):
        context_name = context.findtext("name", default="")
        for message in context.findall("message"):
            key = (
                context_name,
                message.findtext("source", default=""),
                message.findtext("comment", default=""),
            )
            messages[key] = message
    return messages


def _compile_catalog(catalog_path: Path, lrelease: Path) -> None:
    output_path = catalog_path.with_suffix(".qm")
    result = subprocess.run(
        [
            str(lrelease),
            "-nounfinished",
            "-fail-on-invalid",
            str(catalog_path),
            "-qm",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if result.returncode:
        raise RuntimeError(f"pyside6-lrelease failed for {catalog_path.name}")


# @arch ra2ayrmb.i18n-gate entrypoint | en: Checks Qt translation coverage and compiles validated catalogs | zh: 检查 Qt 翻译覆盖率并编译通过校验的翻译目录
def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    source_files = _source_files(project_root)
    catalogs = sorted((project_root / "mix_browser" / "translations").glob("*.ts"))
    lupdate = _tool_path("pyside6-lupdate")
    lrelease = _tool_path("pyside6-lrelease")

    missing_tools = [str(path) for path in (lupdate, lrelease) if not path.is_file()]
    if missing_tools:
        print("Qt Linguist tools were not found in the active Python environment:", file=sys.stderr)
        for path in missing_tools:
            print(f"  {path}", file=sys.stderr)
        return 1
    if not source_files:
        print("No project Python source files were found.", file=sys.stderr)
        return 1
    if not catalogs:
        print("No Qt translation catalogs were found under mix_browser/translations.", file=sys.stderr)
        return 1

    try:
        with tempfile.TemporaryDirectory(prefix="ra2ayrmb-i18n-") as temporary_name:
            source_messages = _extract_source_messages(
                project_root,
                source_files,
                lupdate,
                Path(temporary_name),
            )
            failures = [
                (catalog_path, failure)
                for catalog_path in catalogs
                for failure in _validate_catalog(source_messages, catalog_path)
            ]
        if failures:
            print("i18n gate failed:", file=sys.stderr)
            for catalog_path, failure in failures:
                print(f"  {catalog_path.relative_to(project_root)}: {failure}", file=sys.stderr)
            return 1

        for catalog_path in catalogs:
            _compile_catalog(catalog_path, lrelease)
    except (OSError, ET.ParseError, RuntimeError) as error:
        print(f"i18n gate failed: {error}", file=sys.stderr)
        return 1

    print(
        f"i18n gate passed: {len(source_messages)} source messages, "
        f"{len(catalogs)} translation catalog(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
