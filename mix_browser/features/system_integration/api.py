from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from mix_browser.features.archive.type_detection import MIX_CONTAINER_SUFFIXES
from mix_browser.features.system_integration.open_with_dialog import (
    open_file_with_windows_default,
)
from mix_browser.features.system_integration.windows_registry import WindowsShellRegistry
from mix_browser.shared.application_errors import ApplicationApiError


_INTEGRATION_KEYS = (
    "directory_context_menu",
    "mix_context_menu",
    "mix_new_menu",
    "mix_file_association",
    "container_file_associations",
    "container_file_context_menus",
)
_EXTENSION_MAP_KEYS = frozenset(
    {"container_file_associations", "container_file_context_menus"}
)


# @arch mix-browser.system-integration-api service | en: Manages Windows Explorer integration for supported container extensions and opens reusable samples through normal shell associations | zh: 管理受支持容器扩展名的 Windows 资源管理器集成，并通过常规 Shell 关联打开可复用样例
class SystemIntegrationApplication:
    def __init__(self) -> None:
        command = desktop_launch_command()
        command_line = subprocess.list2cmdline([*command, "--open-path"])
        self._registry = WindowsShellRegistry(
            command_line + ' "%1"'
        )

    def get_state(self) -> dict[str, object]:
        try:
            return self._registry.read_state()
        except OSError as exc:
            raise ApplicationApiError(
                "system_integration_error",
                f"The Windows shell registration state could not be read: {exc}",
            ) from exc

    def configure(
        self,
        *,
        directory_context_menu: bool | None = None,
        mix_context_menu: bool | None = None,
        mix_new_menu: bool | None = None,
        mix_file_association: bool | None = None,
        container_file_associations: dict[str, bool] | None = None,
        container_file_context_menus: dict[str, bool] | None = None,
    ) -> dict[str, object]:
        for key, value in (
            ("container_file_associations", container_file_associations),
            ("container_file_context_menus", container_file_context_menus),
        ):
            if value is None:
                continue
            normalized = {
                extension.casefold(): bool(registered)
                for extension, registered in value.items()
            }
            unsupported = set(normalized) - MIX_CONTAINER_SUFFIXES
            if unsupported:
                raise ApplicationApiError(
                    "invalid_input",
                    "Unsupported container file extension(s): "
                    + ", ".join(sorted(unsupported)),
                )
            if key == "container_file_associations":
                container_file_associations = normalized
            else:
                container_file_context_menus = normalized
        requested = {
            "directory_context_menu": directory_context_menu,
            "mix_context_menu": mix_context_menu,
            "mix_new_menu": mix_new_menu,
            "mix_file_association": mix_file_association,
            "container_file_associations": container_file_associations,
            "container_file_context_menus": container_file_context_menus,
        }
        if not any(value is not None for value in requested.values()):
            raise ApplicationApiError(
                "invalid_input",
                "At least one system integration setting must be specified.",
            )
        previous = self.get_state()
        if not previous["supported"]:
            raise ApplicationApiError(
                "unsupported_platform",
                "Windows shell integration is only available on Windows.",
            )
        changed: dict[str, object] = {}
        for key, value in requested.items():
            if value is None:
                continue
            if key in _EXTENSION_MAP_KEYS:
                previous_values = previous[key]
                refresh_key = (
                    "container_file_association_needs_refresh"
                    if key == "container_file_associations"
                    else "container_file_context_menu_needs_refresh"
                )
                refresh_values = previous[refresh_key]
                differs = any(
                    bool(registered) != bool(previous_values.get(extension))
                    or (
                        bool(registered)
                        and bool(refresh_values.get(extension))
                    )
                    for extension, registered in value.items()
                )
            else:
                differs = bool(value) != bool(previous[key]) or (
                    bool(value)
                    and bool(previous.get(f"{key}_needs_refresh"))
                )
            if differs:
                changed[key] = value
        if not changed:
            return previous
        try:
            return self._registry.configure(**requested)
        except OSError as exc:
            rollback_keys = set(changed)
            try:
                if rollback_keys:
                    rollback_values = {
                        key: None for key in _INTEGRATION_KEYS
                    }
                    for key in rollback_keys:
                        if key in _EXTENSION_MAP_KEYS:
                            rollback_values[key] = dict(previous[key])
                        else:
                            rollback_values[key] = bool(previous[key])
                    self._registry.configure(**rollback_values)
            except OSError as rollback_error:
                message = (
                    f"The registration failed: {exc}. "
                    f"Restoring the previous registrations also failed: {rollback_error}."
                )
            else:
                message = f"The Windows shell registration could not be updated: {exc}"
            raise ApplicationApiError("system_integration_error", message) from exc

    def open_container_file_with_windows_default(self, path: Path) -> None:
        state = self.get_state()
        if not bool(state.get("supported")):
            raise ApplicationApiError(
                "unsupported_platform",
                "Windows file associations are only available on Windows.",
            )
        try:
            open_file_with_windows_default(path)
        except OSError as exc:
            raise ApplicationApiError(
                "system_integration_error",
                f"Windows could not open the container sample: {exc}",
            ) from exc

    def open_mix_file_with_windows_default(self, path: Path) -> None:
        self.open_container_file_with_windows_default(path)

# @arch mix-browser.desktop-launch-command utility | en: Resolves a GUI-safe command for desktop and Windows shell launches | zh: 为桌面启动和 Windows 外壳启动解析无控制台的命令
def desktop_launch_command() -> tuple[str, ...]:
    if getattr(sys, "frozen", False):
        return (sys.executable,)
    if sys.platform != "win32":
        return (sys.executable, "-m", "mix_browser.app.application")

    interpreter = Path(sys.executable)
    gui_interpreter = interpreter.with_name("pythonw.exe")
    if not gui_interpreter.is_file():
        gui_interpreter = interpreter

    source_entrypoint = Path(__file__).resolve().parents[3] / "main.py"
    if source_entrypoint.is_file():
        return (str(gui_interpreter), str(source_entrypoint))
    return (
        str(gui_interpreter),
        "-m",
        "mix_browser.app.application",
    )
