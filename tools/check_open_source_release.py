"""Run source-export and exported-tree checks for a public release."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from release_console import write_status

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


REQUIRED_RELEASE_FILES = (
    "LICENSE",
    "LICENSE-GPL-2.0-or-later.txt",
    "LGPL-3.0-only.txt",
    "README.md",
    "README.zh-CN.md",
    "THIRD_PARTY_NOTICES.md",
    "main.py",
    "package.bat",
    "pyproject.toml",
    "run.bat",
    "run-developer.bat",
    "docs/cli_mcp.md",
    "docs/licensing.md",
    "docs/mix_browser_previews.md",
    "docs/mix_name_data_sources.md",
    "docs/mix_name_discovery.md",
    "docs/vlc_runtime_licenses.md",
    "docs/licenses/Mesa/MIT.txt",
    "docs/licenses/Mesa/Khronos.txt",
    "docs/licenses/Mesa/Boost-1.0.txt",
    "docs/licenses/LLVM/LICENSE.TXT",
    "docs/licenses/CFFI/LICENSE",
    "docs/licenses/pycparser/LICENSE",
    "docs/licenses/Lucide/ISC.txt",
    "docs/licenses/OpenSSL/LICENSE.txt",
    "docs/licenses/PyInstaller/COPYING.txt",
    "docs/licenses/GPL-3.0.txt",
    "docs/licenses/CORRESPONDING_SOURCE_OFFER.txt",
    "docs/licenses/Qt/Apache-2.0.txt",
    "docs/licenses/VLC/COPYING.LIB",
    "docs/licenses/VLC/SOURCE_CODE_OFFER.txt",
    "docs/licenses/Qt/THIRD-PARTY-NOTICES.md",
    "docs/licenses/Qt/double-conversion-LICENSE.txt",
    "docs/licenses/Qt/FTL.txt",
    "docs/licenses/Qt/harfbuzz-COPYING.txt",
    "docs/licenses/Qt/ICC-LICENSE.txt",
    "docs/licenses/Qt/IJG.txt",
    "docs/licenses/Qt/libjpeg-LICENSE.txt",
    "docs/licenses/Qt/libpng-2.0.txt",
    "docs/licenses/Qt/Libpng.txt",
    "docs/licenses/Qt/MPL-2.0.txt",
    "docs/licenses/Qt/PCRE2-BSD-3-Clause-Exception.txt",
    "docs/licenses/Qt/Zlib.txt",
    "docs/licenses/Microsoft/REDIST.txt",
    "docs/licenses/Microsoft/Visual-C++-Redistributable.md",
    "docs/licenses/packaging/LICENSE",
    "docs/licenses/packaging/LICENSE.APACHE",
    "docs/licenses/packaging/LICENSE.BSD",
    "docs/licenses/python-vlc/COPYING",
    "docs/licenses/typing_extensions/LICENSE",
    "docs/licenses/Python/Expat-COPYING.txt",
    "docs/licenses/Python/libmpdec-LICENSE.txt",
    "docs/licenses/Python/Unicode-LICENSE.txt",
    "docs/licenses/Python/zlib-ng-LICENSE.txt",
    "docs/licenses/RA2AYRMB-WINDOWS-DISTRIBUTION.txt",
    "mix_browser/__init__.py",
    "mix_browser/data/name_sources/xcc/COPYING",
    "mix_browser/translations/ra2ayrmb_zh_CN.ts",
    "mix_browser/translations/ra2ayrmb_zh_CN.qm",
    "tools/copy_vlc_runtime.ps1",
    "tools/check_release_licenses.bat",
    "tools/check_release_licenses.ps1",
    "tools/check_open_source_release.py",
    "tools/release_console.py",
    "tools/audit_release_binary.py",
    "tools/stage_release_upload.ps1",
    "tools/write_github_release_info.py",
    "tools/package_vlc_source.ps1",
    "tools/compare_vlc_release.ps1",
    "tools/prepare_vlc_runtime.bat",
    "tools/prepare_vlc_runtime.ps1",
    "tools/release_component_inventory.json",
    "tools/vlc_runtime_plugins.txt",
)
ALLOWED_ROOT_FILES = {
    "license",
    "license-gpl-2.0-or-later.txt",
    "lgpl-3.0-only.txt",
    "readme.md",
    "readme.zh-cn.md",
    "third_party_notices.md",
    "main.py",
    "package.bat",
    "pyproject.toml",
    "run.bat",
    "run-developer.bat",
}
ALLOWED_ROOT_DIRECTORIES = {"docs", "mix_browser", "ra2ayrcfre", "third_party", "tools"}
ALLOWED_DOC_FILES = {
    "docs/cli_mcp.md",
    "docs/licensing.md",
    "docs/mix_browser_previews.md",
    "docs/mix_name_data_sources.md",
    "docs/mix_name_discovery.md",
    "docs/vlc_runtime_licenses.md",
    "docs/licenses/mesa/mit.txt",
    "docs/licenses/mesa/khronos.txt",
    "docs/licenses/mesa/boost-1.0.txt",
    "docs/licenses/llvm/license.txt",
    "docs/licenses/cffi/license",
    "docs/licenses/pycparser/license",
    "docs/licenses/lucide/isc.txt",
    "docs/licenses/openssl/license.txt",
    "docs/licenses/pyinstaller/copying.txt",
    "docs/licenses/gpl-3.0.txt",
    "docs/licenses/ra2ayrmb-windows-distribution.txt",
    "docs/licenses/vlc/copying.lib",
    "docs/licenses/vlc/source_code_offer.txt",
    "docs/licenses/corresponding_source_offer.txt",
    "docs/licenses/qt/apache-2.0.txt",
    "docs/licenses/qt/blake2-copying.txt",
    "docs/licenses/qt/bsd-2-clause.txt",
    "docs/licenses/qt/bsd-3-clause.txt",
    "docs/licenses/qt/cc0-1.0.txt",
    "docs/licenses/qt/double-conversion-license.txt",
    "docs/licenses/qt/ftl.txt",
    "docs/licenses/qt/harfbuzz-copying.txt",
    "docs/licenses/qt/icc-license.txt",
    "docs/licenses/qt/ijg.txt",
    "docs/licenses/qt/libjpeg-license.txt",
    "docs/licenses/qt/libpng-2.0.txt",
    "docs/licenses/qt/libpng.txt",
    "docs/licenses/qt/mit-open-group.txt",
    "docs/licenses/qt/mit.txt",
    "docs/licenses/qt/mpl-2.0.txt",
    "docs/licenses/qt/pcre2-bsd-3-clause-exception.txt",
    "docs/licenses/qt/sha1-public-domain.txt",
    "docs/licenses/qt/third-party-notices.md",
    "docs/licenses/qt/zlib.txt",
    "docs/licenses/microsoft/redist.txt",
    "docs/licenses/microsoft/visual-c++-redistributable.md",
    "docs/licenses/packaging/license",
    "docs/licenses/packaging/license.apache",
    "docs/licenses/packaging/license.bsd",
    "docs/licenses/python-vlc/copying",
    "docs/licenses/typing_extensions/license",
    "docs/licenses/python/expat-copying.txt",
    "docs/licenses/python/libmpdec-license.txt",
    "docs/licenses/python/unicode-license.txt",
    "docs/licenses/python/zlib-ng-license.txt",
}
ALLOWED_DOC_DIRECTORIES = {
    "docs/licenses",
    "docs/licenses/mesa",
    "docs/licenses/llvm",
    "docs/licenses/cffi",
    "docs/licenses/pycparser",
    "docs/licenses/lucide",
    "docs/licenses/openssl",
    "docs/licenses/pyinstaller",
    "docs/licenses/vlc",
    "docs/licenses/qt",
    "docs/licenses/microsoft",
    "docs/licenses/packaging",
    "docs/licenses/python-vlc",
    "docs/licenses/typing_extensions",
    "docs/licenses/python",
}
ALLOWED_TOOL_FILES = {
    "tools/check_open_source_release.py",
    "tools/release_console.py",
    "tools/audit_release_binary.py",
    "tools/stage_release_upload.ps1",
    "tools/write_github_release_info.py",
    "tools/package_vlc_source.ps1",
    "tools/compare_vlc_release.ps1",
    "tools/check_release_licenses.bat",
    "tools/check_release_licenses.ps1",
    "tools/copy_vlc_runtime.ps1",
    "tools/prepare_vlc_runtime.bat",
    "tools/prepare_vlc_runtime.ps1",
    "tools/release_component_inventory.json",
    "tools/vlc_runtime_plugins.txt",
    "tools/pyinstaller_hooks/hook-cryptodome.py",
    "tools/pyinstaller_hooks/hook-pyside6.qtcore.py",
    "tools/pyinstaller_hooks/hook-pyside6.qtgui.py",
    "tools/pyinstaller_hooks/hook-pyside6.qtnetwork.py",
    "tools/pyinstaller_hooks/hook-pyside6.qtwidgets.py",
    "tools/pyinstaller_hooks/hook-setuptools._vendor.jaraco.text.py",
}
ALLOWED_TOOL_DIRECTORIES = {"tools/pyinstaller_hooks"}
ALLOWED_THIRD_PARTY_FILES = {
    "third_party/python-vlc/readme.md",
    "third_party/python-vlc/vlc.py",
}
ALLOWED_THIRD_PARTY_DIRECTORIES = {"third_party/python-vlc"}

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
    beta_match = re.fullmatch(r"(\d+(?:\.\d+)*)b(\d+)", version)
    if not beta_match:
        return version
    beta_number = int(beta_match.group(2))
    display_version = f"{beta_match.group(1)} beta"
    return f"{display_version} {beta_number}" if beta_number else display_version


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
        ("combined Windows application license", "GPL-3.0"),
        ("separate XCC data license", "GPL-3.0"),
    )
    chinese_requirements = (
        ("project purpose", "是一款桌面应用，用于浏览和管理 Westwood MIX 归档"),
        ("supported platform", "Windows 10 或更高版本"),
        ("Python requirement and install instructions", "Python 3.10 或更高版本"),
        ("source installation command", ".venv\\Scripts\\python.exe -m pip install -e ."),
        ("Windows build instructions", "package.bat"),
        ("license information", "[MIT 许可证](LICENSE)"),
        ("combined Windows application license", "GPL-3.0"),
        ("separate XCC data license", "GPL-3.0"),
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

    inventory_path = root / "tools/release_component_inventory.json"
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        return [f"Could not read the release component inventory or pyproject.toml: {exc}"]

    python_vlc = next(
        (component for component in inventory.get("components", []) if component.get("id") == "python-vlc"),
        None,
    )
    if python_vlc is None:
        errors.append("The release inventory is missing the python-vlc component.")
    else:
        expected_sha256 = python_vlc.get("source_sha256", "")
        python_vlc_source = root / "third_party/python-vlc/vlc.py"
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            errors.append("The python-vlc source SHA-256 must be exactly 64 lowercase hexadecimal characters.")
        elif hashlib.sha256(python_vlc_source.read_bytes()).hexdigest() != expected_sha256:
            errors.append("The python-vlc source does not match its reviewed SHA-256.")

    def normalize_distribution(name: str) -> str:
        return re.sub(r"[-_.]+", "-", name).casefold()

    inventory_distributions = {
        normalize_distribution(name)
        for component in inventory.get("components", [])
        for name in component.get("distribution_names", [])
    }
    declared_requirements = list(pyproject.get("build-system", {}).get("requires", []))
    project = pyproject.get("project", {})
    declared_requirements.extend(project.get("dependencies", []))
    for optional_requirements in project.get("optional-dependencies", {}).values():
        declared_requirements.extend(optional_requirements)
    declared_distributions = {
        normalize_distribution(match.group(1))
        for requirement in declared_requirements
        if (match := re.match(r"\s*([A-Za-z0-9][A-Za-z0-9_.-]*)", requirement))
    }
    for distribution in sorted(declared_distributions - inventory_distributions):
        errors.append(
            "tools/release_component_inventory.json does not cover declared Python "
            f"distribution {distribution}."
        )

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
        "CPython Expat parser",
        "CPython decimal arithmetic library",
        "CPython Unicode Character Database",
        "zlib-ng 2.2.4",
        "OpenSSL",
        "PySide6 Essentials",
        "Mesa llvmpipe",
        "LLVM 3.6.2",
        "python-vlc",
        "VLC 3.0.24",
        "pycryptodomex",
        "CFFI",
        "pycparser",
        "MCP Python SDK",
        "PyInstaller",
        "setuptools 84.0.0",
        "packaging 26.3",
        "typing_extensions 4.16.0",
        "Microsoft Visual C++ runtime",
    ):
        if component.casefold() not in notices.casefold():
            errors.append(f"THIRD_PARTY_NOTICES.md does not list {component}.")

    packaging_script = (root / "package.bat").read_text(
        encoding="utf-8", errors="replace"
    ).casefold()
    for packaged_license in (
        "ra2ayrmb-mit.txt",
        "gpl-3.0.txt",
        "third_party_notices.md",
        "qt\\lgpl-3.0-only.txt",
        "xcc\\copying",
        "pyinstaller\\copying.txt",
        "lucide\\isc.txt",
        "vlc\\source_code_offer.txt",
        "ra2ayrmb-windows-distribution.txt",
        "setuptools\\license",
        "setuptools-vendor\\packaging-26.0.dist-info\\licenses\\license.apache",
        "setuptools-vendor\\packaging-26.0.dist-info\\licenses\\license.bsd",
        "microsoft\\visual-c++-redistributable.md",
        "packaging\\license",
        "python\\expat-copying.txt",
        "python\\libmpdec-license.txt",
        "python\\unicode-license.txt",
        "python\\zlib-ng-license.txt",
        "packaging\\license.apache",
        "packaging\\license.bsd",
        "typing_extensions\\license",
    ):
        if packaged_license not in packaging_script:
            errors.append(
                f"package.bat does not place the visible license bundle entry: {packaged_license}"
            )
    maintained_license_tree_copy = (
        'robocopy "%~dp0docs\\licenses" "%license_root%" /e' in packaging_script
    )
    if not maintained_license_tree_copy:
        errors.append(
            "package.bat must copy the maintained docs/licenses tree into the visible license directory."
        )
    for source_license in (
        "docs/licenses/Mesa/MIT.txt",
        "docs/licenses/Mesa/Khronos.txt",
        "docs/licenses/Mesa/Boost-1.0.txt",
        "docs/licenses/LLVM/LICENSE.TXT",
        "docs/licenses/CFFI/LICENSE",
        "docs/licenses/pycparser/LICENSE",
        "docs/licenses/OpenSSL/LICENSE.txt",
        "docs/licenses/Python/Expat-COPYING.txt",
        "docs/licenses/Python/libmpdec-LICENSE.txt",
        "docs/licenses/Python/Unicode-LICENSE.txt",
        "docs/licenses/Python/zlib-ng-LICENSE.txt",
    ):
        if not (root / source_license).is_file():
            errors.append(f"Required maintained binary license is missing: {source_license}")
    for package_name, package_version in (
        ("pyside6-essentials", "6.11.1"),
        ("shiboken6", "6.11.1"),
        ("python-vlc", "3.0.21203"),
        ("pyinstaller", "6.20.0"),
        ("pycryptodomex", "3.23.0"),
        ("cffi", "2.1.1"),
        ("pycparser", "3.12"),
        ("setuptools", "84.0.0"),
        ("packaging", "26.3"),
        ("typing-extensions", "4.16.0"),
    ):
        if f"'{package_name}':'{package_version}'" not in packaging_script:
            errors.append(
                "package.bat must enforce the reviewed version for "
                f"{package_name} {package_version}."
            )
    for runtime_requirement in (
        "platform.python_version() == '3.14.7'",
        "ssl.openssl_version.startswith('openssl 3.5.7 ')",
    ):
        if runtime_requirement not in packaging_script:
            errors.append(
                "package.bat must enforce the reviewed runtime version: "
                f"{runtime_requirement}."
            )
    copies_dependency_license_directory = 'robocopy "%%d\\licenses"' in packaging_script
    if "licenseref-qt-commercial.txt" in packaging_script or copies_dependency_license_directory:
        errors.append("package.bat must not copy Qt's alternative commercial license metadata.")
    for obsolete_claim in (
        "permission remains unconfirmed",
        "if pyinstaller includes them",
        "mesa uses the mit license",
    ):
        if obsolete_claim in notices.casefold():
            errors.append(
                "THIRD_PARTY_NOTICES.md contains a superseded or unverified claim: "
                f"{obsolete_claim}"
            )
    for xcc_list in (
        "ra2 mix description.txt",
        "td mix description.txt",
        "ts mix description.txt",
    ):
        if xcc_list not in packaging_script:
            errors.append(f"package.bat is missing the XCC name list: {xcc_list}")
    if "name_sources\\xcc;mix_browser\\data\\name_sources\\xcc" in packaging_script:
        errors.append("package.bat must not bundle the XCC license file twice as application data.")
    license_text_requirements = (
        ("LICENSE-GPL-2.0-or-later.txt", "GNU GENERAL PUBLIC LICENSE"),
        ("docs/licenses/GPL-3.0.txt", "Version 3"),
        ("docs/licenses/RA2AYRMB-WINDOWS-DISTRIBUTION.txt", "GPL-3.0"),
        ("docs/licenses/packaging/LICENSE.APACHE", "Apache License"),
        ("docs/licenses/typing_extensions/LICENSE", "Python Software Foundation License Version 2"),
        ("docs/licenses/Mesa/MIT.txt", "Brian Paul Be Liable"),
        ("docs/licenses/Mesa/Khronos.txt", "The Khronos Group Inc."),
        ("docs/licenses/Mesa/Boost-1.0.txt", "Boost Software License, Version 1.0"),
        ("docs/licenses/LLVM/LICENSE.TXT", "University of Illinois/NCSA"),
        ("docs/licenses/CFFI/LICENSE", "MIT No Attribution"),
        ("docs/licenses/pycparser/LICENSE", "All rights reserved."),
        ("docs/licenses/Lucide/ISC.txt", "Lucide Contributors"),
        ("docs/licenses/OpenSSL/LICENSE.txt", "Apache License"),
        ("docs/licenses/PyInstaller/COPYING.txt", "Bootloader Exception"),
        ("docs/licenses/Python/Expat-COPYING.txt", "Expat maintainers"),
        ("docs/licenses/Python/libmpdec-LICENSE.txt", "Stefan Krah"),
        ("docs/licenses/Python/Unicode-LICENSE.txt", "UNICODE LICENSE V3"),
        ("docs/licenses/Python/zlib-ng-LICENSE.txt", "Jean-loup Gailly and Mark Adler"),
    )
    for relative_path, marker in license_text_requirements:
        contents = (root / relative_path).read_text(encoding="utf-8", errors="replace")
        if marker.casefold() not in contents.casefold():
            errors.append(f"{relative_path} does not contain its expected license text.")

    distribution_notice = (
        root / "docs/licenses/RA2AYRMB-WINDOWS-DISTRIBUTION.txt"
    ).read_text(encoding="utf-8", errors="replace").casefold()
    for marker in (
        "gpl-3.0",
        "gpl-2.0-or-later grant",
        "not offered under the project's mit option",
        "does not offer the combined work under a later gpl version",
        "full gpl-3.0 text",
        "retain their own terms",
        "xcc mix name data",
        "gpl-3.0",
    ):
        if marker not in distribution_notice:
            errors.append(
                "The Windows distribution license notice is missing its required scope statement: "
                f"{marker}."
            )

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
        "OpenSSL",
        "PyInstaller",
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
    if (
        "## Corresponding Source" not in review_text
        or "https://code.videolan.org/videolan/vlc/-/tree/3.0.24" not in review_text
    ):
        errors.append("The VLC runtime license review is missing its corresponding source location.")
    source_offer = (root / "docs/licenses/VLC/SOURCE_CODE_OFFER.txt").read_text(
        encoding="utf-8", errors="replace"
    )
    for offer_requirement in (
        "GPL-2.0",
        "VLC 3.0.24",
        "at least three years",
        "any third party",
        "at no charge",
        "releases/download/v1.2.1/RA2AYRMB-vlc-source-3.0.24.7z",
        "github.com/KAINEYLBS/Red-Alert-2-and-Yuri-s-Revenge-MIX-Browser/issues",
    ):
        if offer_requirement.casefold() not in source_offer.casefold():
            errors.append(
                "VLC source offer is missing required text: "
                f"{offer_requirement}"
            )
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


def _check_export_scope(root: Path) -> list[str]:
    errors: list[str] = []
    for path in root.iterdir():
        relative = path.relative_to(root).as_posix().casefold()
        if relative == ".git":
            continue
        if path.is_dir():
            if relative not in ALLOWED_ROOT_DIRECTORIES:
                errors.append(f"Unapproved top-level directory was exported: {relative}/")
        elif relative not in ALLOWED_ROOT_FILES:
            errors.append(f"Unapproved top-level file was exported: {relative}")

    for base, allowed_files, allowed_directories in (
        ("docs", ALLOWED_DOC_FILES, ALLOWED_DOC_DIRECTORIES),
        ("tools", ALLOWED_TOOL_FILES, ALLOWED_TOOL_DIRECTORIES),
        ("third_party", ALLOWED_THIRD_PARTY_FILES, ALLOWED_THIRD_PARTY_DIRECTORIES),
    ):
        base_path = root / base
        if not base_path.exists():
            continue
        for path in base_path.rglob("*"):
            relative = path.relative_to(root).as_posix().casefold()
            if path.is_dir():
                if relative not in allowed_directories:
                    errors.append(f"Unapproved {base} directory was exported: {relative}/")
            elif relative not in allowed_files:
                errors.append(f"Unapproved {base} file was exported: {relative}")
    return errors


def _check_export_tree(root: Path) -> list[str]:
    errors = _check_required_files(root)
    errors.extend(_check_export_scope(root))
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
            write_status(f"BLOCKED: {error}", "red", stream=sys.stderr)
        return 1

    write_status(f"Source checks passed at commit {commit}.", "green")
    if status:
        write_status(
            "WARNING: this local export will include uncommitted worktree changes:",
            "yellow",
        )
        for line in status[:20]:
            write_status(f"  {line}", "yellow")
        if len(status) > 20:
            write_status(f"  ... and {len(status) - 20} more changed files", "yellow")
    write_status(
        "Automated source, licensing-document, README, version, and link checks passed.",
        "green",
    )
    return 0


def _run_export_gate(root: Path) -> int:
    errors = _check_export_tree(root)
    if errors:
        for error in errors:
            write_status(f"BLOCKED: {error}", "red", stream=sys.stderr)
        return 1
    write_status("Open-source export contents passed inspection.", "green")
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
        write_status(f"Release gate root is not a directory: {root}", "red", stream=sys.stderr)
        return 1
    if args.phase == "source":
        return _run_source_gate(root, allow_dirty=args.allow_dirty)
    return _run_export_gate(root)


if __name__ == "__main__":
    raise SystemExit(main())
