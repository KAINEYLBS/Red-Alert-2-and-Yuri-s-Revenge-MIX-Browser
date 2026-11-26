"""Generate copy-ready GitHub release metadata from the in-app release notes."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

from release_console import write_status


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _assigned_string(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise ValueError(f"Could not find the {name} string in {path}.")


def _current_release_notes(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    dialog = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "VersionUpdatesDialog"
        ),
        None,
    )
    if dialog is None:
        raise ValueError("Could not find VersionUpdatesDialog.")

    method = next(
        (
            node
            for node in dialog.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_current_release_notes"
        ),
        None,
    )
    if method is None:
        raise ValueError("Could not find _current_release_notes().")

    returns = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple)
    ]
    if len(returns) != 1:
        raise ValueError("Expected one tuple of current release notes.")

    notes: list[str] = []
    for item in returns[0].value.elts:
        if not (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and isinstance(item.func.value, ast.Name)
            and item.func.value.id == "self"
            and item.func.attr == "tr"
            and len(item.args) == 1
            and isinstance(item.args[0], ast.Constant)
            and isinstance(item.args[0].value, str)
        ):
            raise ValueError("Each current release note must be a literal self.tr() string.")
        notes.append(item.args[0].value)

    if not notes:
        raise ValueError("No current release notes were found.")
    return tuple(notes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    version = _assigned_string(PROJECT_ROOT / "mix_browser" / "__init__.py", "__version__")
    notes = _current_release_notes(
        PROJECT_ROOT / "mix_browser" / "features" / "browser" / "version_updates_dialog.py"
    )
    body = "\n".join(f"- {note}" for note in notes)
    document = (
        "# GitHub Release Details\n\n"
        f"Title: RA2AYRMB v{version}\n"
        f"Recommended tag: v{version}\n\n"
        "## Body\n\n"
        f"{body}\n"
    )

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(document.encode("utf-8"))
    write_status(f"GitHub release information written to {output}", "green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
