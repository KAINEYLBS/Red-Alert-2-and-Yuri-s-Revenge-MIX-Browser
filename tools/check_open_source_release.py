"""Run source-export and exported-tree checks for a public release."""

from __future__ import annotations

import argparse
import ast
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


REQUIRED_RELEASE_FILES = (
    ".gitignore",
    "LICENSE",
    "LGPL-3.0-only.txt",
    "README.md",
    "README.zh-CN.md",
    "THIRD_PARTY_NOTICES.md",
    "ffmpeg-release-review.json",
    "main.py",
    "package.bat",
    "pyproject.toml",
    "run.bat",
    "run-developer.bat",
    "docs/ffmpeg_release_review.md",
    "docs/licensing.md",
    "docs/mix_browser_previews.md",
    "docs/open_source_release_checklist.md",
    "docs/vlc_runtime_licenses.md",
    "docs/licenses/VLC/COPYING.LIB",
    "mix_browser/__init__.py",
    "mix_browser/data/name_sources/xcc/COPYING",
    "mix_browser/translations/ra2ayrmb_zh_CN.ts",
    "mix_browser/translations/ra2ayrmb_zh_CN.qm",
    "tools/check_i18n.py",
    "tools/check_open_source_release.py",
    "tools/copy_vlc_runtime.ps1",
    "tools/prepare_vlc_runtime.ps1",
    "tools/vlc_runtime_plugins.txt",
)

FORBIDDEN_DIRECTORY_NAMES = {
    ".venv",
    ".runtime",
    ".pyinstaller-work",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
FORBIDDEN_SUFFIXES = {
    ".dll",
    ".exe",
    ".lib",
    ".obj",
    ".pdb",
    ".pyd",
    ".pyc",
    ".pyo",
    ".whl",
    ".zip",
    ".7z",
}
LICENSE_TEXT_PATHS = {
    "docs/licenses/vlc/copying.lib",
}
TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\(([^)]*)\)")


def _read_project_version(root: Path) -> str | None:
    try:
        module = ast.parse(
            (root / "mix_browser/__init__.py").read_text(encoding="utf-8"),
            filename="mix_browser/__init__.py",
        )
    except (OSError, SyntaxError, UnicodeError):
        return None

    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                return None
            return value if isinstance(value, str) else None
    return None


def _display_version(version: str) -> str:
    beta_match = re.fullmatch(r"(\d+(?:\.\d+)*)b\d+", version)
    return f"{beta_match.group(1)} beta" if beta_match else version


def _check_readme(
    root: Path,
    relative_path: str,
    requirements: tuple[tuple[str, str], ...],
    version_pattern: str,
    project_version: str | None,
) -> list[str]:
    path = root / relative_path
    contents = path.read_text(encoding="utf-8", errors="replace")
    errors = [
        f"{relative_path} is missing its {description} information."
        for description, marker in requirements
        if marker.casefold() not in contents.casefold()
    ]

    if project_version is not None:
        version_match = re.search(version_pattern, contents, re.MULTILINE)
        if version_match is None:
            errors.append(f"{relative_path} is missing its project version field.")
        elif version_match.group(1).strip() != _display_version(project_version):
            errors.append(
                f"{relative_path} reports version {version_match.group(1).strip()!r}; "
                f"the application version is {_display_version(project_version)!r}."
            )

    for match in MARKDOWN_LINK_PATTERN.finditer(contents):
        raw_destination = match.group(1).strip()
        if not raw_destination:
            errors.append(f"{relative_path} contains an empty Markdown link.")
            continue
        if raw_destination.startswith("<") and ">" in raw_destination:
            destination = raw_destination[1 : raw_destination.index(">")]
        else:
            destination = raw_destination.split(maxsplit=1)[0]
        try:
            parsed = urlsplit(destination)
        except ValueError:
            errors.append(f"{relative_path} contains an invalid Markdown link: {destination}")
            continue
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = unquote(parsed.path)
        target_path = (
            root / target.lstrip("/")
            if target.startswith("/")
            else path.parent / target
        )
        resolved_target = target_path.resolve()
        try:
            resolved_target.relative_to(root.resolve())
        except ValueError:
            errors.append(f"{relative_path} links outside the project: {destination}")
            continue
        if not resolved_target.exists():
            errors.append(f"{relative_path} has a broken local link: {destination}")
    return errors


def _check_repository_readiness(root: Path) -> list[str]:
    project_version = _read_project_version(root)
    errors = []
    if project_version is None:
        errors.append("Could not read a literal __version__ from mix_browser/__init__.py.")

    english_requirements = (
        ("project purpose", "desktop application for browsing and managing Westwood MIX archives"),
        ("supported platform", "Supported Windows desktop builds require Windows 10 or later"),
        ("Python requirement and install instructions", "Python 3.10 or newer"),
        ("source installation command", ".venv\\Scripts\\python.exe -m pip install -e ."),
        ("Windows build instructions", "package.bat"),
        ("license information", "[MIT License](LICENSE)"),
    )
    chinese_requirements = (
        ("project purpose", "是一款桌面应用，用于浏览和管理 Westwood MIX 归档"),
        ("supported platform", "Windows 10 或更高版本"),
        ("Python requirement and install instructions", "Python 3.10 或更高版本"),
        ("source installation command", ".venv\\Scripts\\python.exe -m pip install -e ."),
        ("Windows build instructions", "package.bat"),
        ("license information", "[MIT 许可证](LICENSE)"),
    )
    errors.extend(_check_readme(
        root,
        "README.md",
        english_requirements,
        r"^Version:\s*\*\*(.+?)\*\*",
        project_version,
    ))
    errors.extend(
        _check_readme(
            root,
            "README.zh-CN.md",
            chinese_requirements,
            r"^版本：\*\*(.+?)\*\*",
            project_version,
        )
    )

    project_metadata = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
    if not re.search(
        r"(?m)^\s*version\s*=\s*\{\s*attr\s*=\s*"
        r"['\"]mix_browser\.__version__['\"]\s*\}\s*$",
        project_metadata,
    ):
        errors.append(
            "pyproject.toml does not derive its package version from "
            "mix_browser.__version__."
        )
    return errors


def _check_required_files(root: Path) -> list[str]:
    errors = [
        f"Required release file is missing: {relative_path}"
        for relative_path in REQUIRED_RELEASE_FILES
        if not (root / relative_path).is_file()
    ]
    if errors:
        return errors

    license_text = (root / "LICENSE").read_text(encoding="utf-8", errors="replace")
    if not license_text.startswith("MIT License"):
        errors.append("LICENSE does not identify the project license as MIT.")

    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8", errors="replace"
    )
    for component in (
        "XCC",
        "Simple Icons",
        "CPython runtime",
        "PySide6 Essentials",
        "python-vlc",
        "VLC 3.0.24",
        "pycryptodomex",
        "MCP Python SDK",
        "PyInstaller",
    ):
        if component.casefold() not in notices.casefold():
            errors.append(f"THIRD_PARTY_NOTICES.md does not list {component}.")

    license_text = (root / "LICENSE").read_text(encoding="utf-8", errors="replace")
    if not re.search(
        r"(?m)^Copyright \(c\) \d{4}(?:-\d{4})? KAINEYLB小卡$",
        license_text,
    ):
        errors.append("LICENSE is missing the project copyright holder declaration.")
    vlc_lgpl_text = (root / "docs/licenses/VLC/COPYING.LIB").read_text(
        encoding="utf-8", errors="replace"
    )
    if "GNU LESSER GENERAL PUBLIC LICENSE" not in vlc_lgpl_text:
        errors.append("docs/licenses/VLC/COPYING.LIB does not contain the LGPL license text.")
    licensing_text = (root / "docs/licensing.md").read_text(encoding="utf-8", errors="replace")
    for declaration in (
        "KAINEYLB小卡",
        "MIX-EXE.ico",
        "MIX-FILE.ico",
        "MMX-FILE.ico",
        "YRO-FILE.ico",
        "CnCNet",
    ):
        if declaration.casefold() not in licensing_text.casefold():
            errors.append(
                "docs/licensing.md is missing its provenance declaration for "
                f"{declaration}."
            )

    plugin_manifest = root / "tools/vlc_runtime_plugins.txt"
    plugin_review = root / "docs/vlc_runtime_licenses.md"
    plugins = [
        line.strip()
        for line in plugin_manifest.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    review_text = plugin_review.read_text(encoding="utf-8", errors="replace")
    if not plugins:
        errors.append("The VLC runtime plugin manifest is empty.")
    for plugin in plugins:
        if f"`{plugin}`" not in review_text:
            errors.append(f"VLC plugin license review is missing: {plugin}")

    errors.extend(_check_repository_readiness(root))
    return errors


def _inspect_git_tree(root: Path) -> tuple[list[str], str | None, list[str]]:
    try:
        top_level = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"Could not verify the release Git checkout: {exc}"], None, []

    if os.path.normcase(os.path.realpath(top_level)) != os.path.normcase(str(root)):
        return [f"The source path is not the Git checkout root: {top_level}"], commit, []
    return [], commit, status


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(metadata, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _check_export_tree(root: Path) -> list[str]:
    errors = _check_required_files(root)
    reference_data = root / "docs/reference"
    if reference_data.exists():
        errors.append("The exported tree must not include docs/reference/.")

    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path == root:
            directories[:] = [name for name in directories if name.casefold() != ".git"]

        retained_directories = []
        for name in directories:
            path = current_path / name
            if name.casefold() in FORBIDDEN_DIRECTORY_NAMES:
                errors.append(f"Build or cache directory was exported: {path.relative_to(root)}")
                continue
            if _is_reparse_point(path):
                errors.append(f"Linked directory was exported: {path.relative_to(root)}")
                continue
            retained_directories.append(name)
        directories[:] = retained_directories

        for name in filenames:
            path = current_path / name
            relative = path.relative_to(root)
            if _is_reparse_point(path):
                errors.append(f"Linked file was exported: {relative}")
                continue
            if (
                path.suffix.casefold() in FORBIDDEN_SUFFIXES
                and relative.as_posix().casefold() not in LICENSE_TEXT_PATHS
            ):
                errors.append(f"Build artifact or binary was exported: {relative}")
                continue
            lowered_name = name.casefold()
            if (
                lowered_name == ".env"
                or (lowered_name.startswith(".env.") and lowered_name not in {".env.example", ".env.sample"})
                or lowered_name in {"credentials.json", "secrets.json", "secrets.yaml", "secrets.yml"}
                or lowered_name.startswith(("id_rsa", "id_ed25519"))
                or path.suffix.casefold() in {".key", ".pem", ".p12", ".pfx"}
            ):
                errors.append(f"Potential secret or private credential was exported: {relative}")
                continue

            if path.suffix.casefold() in TEXT_SUFFIXES:
                try:
                    contents = path.read_text(encoding="utf-8", errors="ignore")
                except OSError as exc:
                    errors.append(f"Could not inspect exported file {relative}: {exc}")
                    continue
                for pattern in SECRET_PATTERNS:
                    if pattern.search(contents):
                        errors.append(f"Potential credential was found in exported file: {relative}")
                        break
    return errors


def _run_source_gate(root: Path, allow_dirty: bool = False) -> int:
    errors = _check_required_files(root)
    git_errors, commit, status = _inspect_git_tree(root)
    errors.extend(git_errors)
    if status and not allow_dirty:
        errors.append("The source worktree is not clean:")
        errors.extend(f"  {line}" for line in status[:20])
        if len(status) > 20:
            errors.append(f"  ... and {len(status) - 20} more changed files")
    if errors:
        for error in errors:
            print(f"BLOCKED: {error}", file=sys.stderr)
        return 1

    print(f"Source checks passed at commit {commit}.")
    if status:
        print("WARNING: this local export will include uncommitted worktree changes:")
        for line in status[:20]:
            print(f"  {line}")
        if len(status) > 20:
            print(f"  ... and {len(status) - 20} more changed files")
    print("Automated source, licensing-document, README, version, and link checks passed.")
    return 0


def _run_export_gate(root: Path) -> int:
    errors = _check_export_tree(root)
    if errors:
        for error in errors:
            print(f"BLOCKED: {error}", file=sys.stderr)
        return 1
    print("Open-source export contents passed inspection.")
    return 0


# @arch ra2ayrmb.open-source-release-gate entrypoint | en: Checks source-export contents and release prerequisites | zh: 检查开源导出内容和发布前置条件
def main() -> int:
    parser = argparse.ArgumentParser(description="Check open-source release readiness.")
    parser.add_argument("phase", choices=("source", "export"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow uncommitted files in a local source export, while listing them.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        print(f"Release gate root is not a directory: {root}", file=sys.stderr)
        return 1
    if args.phase == "source":
        return _run_source_gate(root, allow_dirty=args.allow_dirty)
    return _run_export_gate(root)


if __name__ == "__main__":
    raise SystemExit(main())
