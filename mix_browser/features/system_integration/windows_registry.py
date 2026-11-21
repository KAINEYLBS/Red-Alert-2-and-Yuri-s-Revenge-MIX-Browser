from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from mix_browser.features.archive.domain import EMPTY_MIX_ARCHIVE_HEADER
from mix_browser.features.archive.type_detection import MIX_CONTAINER_SUFFIXES
from mix_browser.shared.application_identity import APPLICATION_DISPLAY_NAME


_DIRECTORY_VERB = r"Software\Classes\Directory\shell\RA2AYRCFRE.MIXBrowser.Browse"
_CONTAINER_VERB_NAME = "RA2AYRCFRE.MIXBrowser.Browse"
_CONTAINER_EXTRACT_VERB_NAME = "RA2AYRCFRE.MIXBrowser.Extract"
_FILE_MIX_COPY_VERB = r"Software\Classes\*\shell\RA2AYRCFRE.MIXBrowser.CreateMixCopy"
_FILE_MIX_MOVE_VERB = r"Software\Classes\*\shell\RA2AYRCFRE.MIXBrowser.CreateMixMove"
_FILE_CONTEXT_MENU_ROOT = (
    r"Software\Classes\*\shell\RA2AYRCFRE.MIXBrowser.ContextMenu"
)
_FILE_CONTEXT_MENU_COPY_VERB = _FILE_CONTEXT_MENU_ROOT + r"\shell\CreateMixCopy"
_FILE_CONTEXT_MENU_MOVE_VERB = _FILE_CONTEXT_MENU_ROOT + r"\shell\CreateMixMove"
_FILE_CONTEXT_MENU_BROWSE_VERB = _FILE_CONTEXT_MENU_ROOT + r"\shell\BrowseContainer"
_FILE_CONTEXT_MENU_EXTRACT_VERB = _FILE_CONTEXT_MENU_ROOT + r"\shell\ExtractContainers"
_CONTEXT_MENU_SETTINGS_KEY = (
    r"Software\RA2AYRCFRE\MIXBrowser\ExplorerContextMenu"
)
_CONTEXT_MENU_GROUPING_VALUE = "GroupFileCommands"
_CONTEXT_MENU_BROWSE_EXTENSIONS_VALUE = "BrowseExtensions"
_CONTEXT_MENU_EXTRACT_EXTENSIONS_VALUE = "ExtractExtensions"
_MIX_EXTENSION_NAME = ".mix"
_MIX_EXTENSION = r"Software\Classes\.mix"
_MIX_NEW_PROGID = "RA2AYRCFRE.MIXBrowser.MIX.New"
_MIX_NEW_PROGID_KEY = rf"Software\Classes\{_MIX_NEW_PROGID}"
_MIX_SHELL_NEW = _MIX_EXTENSION + r"\ShellNew"
_MIX_NESTED_SHELL_NEW_CLASS = _MIX_EXTENSION + "\\" + _MIX_NEW_PROGID
_MIX_NESTED_SHELL_NEW = _MIX_NESTED_SHELL_NEW_CLASS + r"\ShellNew"
_MIX_SHELL_NEW_BACKUP = (
    r"Software\RA2AYRCFRE\MIXBrowser\ShellNewRegistrationBackup"
)
_SHELL_NEW_CACHE = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Discardable\PostSetup\ShellNew"
)
_REGISTRATION_OWNER = "RA2AYRMBRegistration"
_MIX_SHELL_NEW_OWNER = "RA2AYRMBRegistration"
_MIX_NEW_EXTENSION_DEFAULT_OWNER = "RA2AYRMBNewMenuDefault"
_MIX_SHELL_NEW_MENU_TEXT = "MIX archive"
_MIX_PROGID = "RA2AYRCFRE.MIXBrowser.MIX"
_APPLICATION_ICON_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "icons" / "MIX-EXE.ico"
)
_APPLICATION_ICON_SOURCE = (
    sys.executable if getattr(sys, "frozen", False) else str(_APPLICATION_ICON_PATH)
)
_APPLICATION_ICON_VALUE = f'"{_APPLICATION_ICON_SOURCE}",0'
_MIX_ICON_PATH = Path(__file__).resolve().parents[2] / "data" / "icons" / "MIX-FILE.ico"
_MIX_SHELL_NEW_ICON_PATH = f'"{_MIX_ICON_PATH}",0'
_CONTAINER_PROGIDS = {
    extension: (
        _MIX_PROGID
        if extension == ".mix"
        else f"RA2AYRCFRE.MIXBrowser.{extension[1:].upper()}"
    )
    for extension in MIX_CONTAINER_SUFFIXES
}
_CONTAINER_PROGID_KEYS = {
    extension: rf"Software\Classes\{progid}"
    for extension, progid in _CONTAINER_PROGIDS.items()
}
_CONTAINER_ICON_PATHS = {
    extension: Path(__file__).resolve().parents[2]
    / "data"
    / "icons"
    / f"{extension[1:].upper()}-FILE.ico"
    for extension in MIX_CONTAINER_SUFFIXES
}
_REGISTERED_APPLICATIONS = r"Software\RegisteredApplications"
_APPLICATION_NAME = APPLICATION_DISPLAY_NAME
_LEGACY_APPLICATION_NAME = "MIX Browser"
_CAPABILITIES_KEY = r"Software\RA2AYRCFRE\MIXBrowser\Capabilities"
_CAPABILITIES_PATH = _CAPABILITIES_KEY
_DEFAULT_APPS_KEY_PREFIX = (
    "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\"
)


def _extension_open_with_key(extension: str) -> str:
    return rf"Software\Classes\{extension}\OpenWithProgids"


def _extension_class_key(extension: str) -> str:
    return rf"Software\Classes\{extension}"


def _extension_user_choice_key(extension: str) -> str:
    return _DEFAULT_APPS_KEY_PREFIX + extension + r"\UserChoice"


# @arch mix-browser.windows-shell-registration adapter | en: Registers and removes per-user Windows Explorer verbs and container file capabilities | zh: 注册和移除当前用户的 Windows 资源管理器菜单项与容器文件能力
class WindowsShellRegistry:
    def __init__(
        self,
        open_command: str,
        *,
        shell_operation_commands: dict[str, str] | None = None,
    ) -> None:
        self._open_command = open_command
        self._shell_operation_commands = dict(shell_operation_commands or {})

    @staticmethod
    def is_supported() -> bool:
        return sys.platform == "win32"

    def read_state(self) -> dict[str, object]:
        if not self.is_supported():
            return {
                "supported": False,
                "directory_context_menu": False,
                "mix_context_menu": False,
                "container_file_context_menus": {
                    extension: False for extension in sorted(MIX_CONTAINER_SUFFIXES)
                },
                "container_file_extract_context_menus": {
                    extension: False for extension in sorted(MIX_CONTAINER_SUFFIXES)
                },
                "context_menu_submenu": True,
                "context_menu_submenu_needs_refresh": False,
                "container_file_extract_context_menu_needs_refresh": {
                    extension: False for extension in sorted(MIX_CONTAINER_SUFFIXES)
                },
                "file_context_mix_copy": False,
                "file_context_mix_copy_needs_refresh": False,
                "file_context_mix_move": False,
                "file_context_mix_move_needs_refresh": False,
                "container_file_context_menu_needs_refresh": {
                    extension: False for extension in sorted(MIX_CONTAINER_SUFFIXES)
                },
                "mix_new_menu": False,
                "directory_context_menu_needs_refresh": False,
                "mix_context_menu_needs_refresh": False,
                "mix_new_menu_needs_refresh": False,
                "mix_file_association": False,
                "mix_file_association_needs_refresh": False,
                "mix_is_default": False,
                "container_file_associations": {
                    extension: False for extension in sorted(MIX_CONTAINER_SUFFIXES)
                },
                "container_file_association_needs_refresh": {
                    extension: False for extension in sorted(MIX_CONTAINER_SUFFIXES)
                },
                "container_file_is_default": {
                    extension: False for extension in sorted(MIX_CONTAINER_SUFFIXES)
                },
            }

        import winreg

        browse_label = self._browse_menu_label()
        file_context_state = self._file_context_menu_state()
        container_file_associations = {
            extension: self._container_handler_is_registered(extension)
            for extension in sorted(MIX_CONTAINER_SUFFIXES)
        }
        container_file_association_needs_refresh = {
            extension: self._container_handler_needs_refresh(extension)
            for extension in sorted(MIX_CONTAINER_SUFFIXES)
        }
        container_file_is_default = {
            extension: self._container_is_default(extension)
            for extension in sorted(MIX_CONTAINER_SUFFIXES)
        }
        return {
            "supported": True,
            **file_context_state,
            "directory_context_menu": self._verb_is_registered(_DIRECTORY_VERB),
            "mix_new_menu": self._mix_new_menu_is_registered(),
            "mix_file_association": container_file_associations.get(".mix", False),
            "mix_is_default": container_file_is_default.get(".mix", False),
            "container_file_associations": container_file_associations,
            "container_file_association_needs_refresh": container_file_association_needs_refresh,
            "container_file_is_default": container_file_is_default,
            "directory_context_menu_needs_refresh": self._verb_needs_refresh(
                _DIRECTORY_VERB,
                browse_label,
            ),
            "mix_new_menu_needs_refresh": self._mix_new_menu_needs_refresh(),
            "mix_file_association_needs_refresh": container_file_association_needs_refresh.get(
                ".mix", False
            ),
        }

    def _file_context_menu_state(self) -> dict[str, object]:
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        extensions = sorted(MIX_CONTAINER_SUFFIXES)
        grouped = self._context_menu_grouping_enabled()
        stored_copy = self._context_menu_bool("PackCopy")
        stored_move = self._context_menu_bool("PackMove")
        stored_browse = self._context_menu_extensions(
            _CONTEXT_MENU_BROWSE_EXTENSIONS_VALUE
        )
        stored_extract = self._context_menu_extensions(
            _CONTEXT_MENU_EXTRACT_EXTENSIONS_VALUE
        )

        direct_copy = self._verb_is_registered(_FILE_MIX_COPY_VERB)
        direct_move = self._verb_is_registered(_FILE_MIX_MOVE_VERB)
        cascade_copy = self._verb_is_registered(_FILE_CONTEXT_MENU_COPY_VERB)
        cascade_move = self._verb_is_registered(_FILE_CONTEXT_MENU_MOVE_VERB)
        copy_enabled = (
            stored_copy
            if stored_copy is not None
            else direct_copy or cascade_copy
        )
        move_enabled = (
            stored_move
            if stored_move is not None
            else direct_move or cascade_move
        )

        direct_browse = {
            extension: self._verb_is_registered(
                self._container_context_verb(extension)
            )
            for extension in extensions
        }
        direct_extract = {
            extension: self._verb_is_registered(
                self._container_extract_context_verb(extension)
            )
            for extension in extensions
        }
        browse_enabled = {
            extension: (
                extension in stored_browse
                if stored_browse is not None
                else direct_browse[extension]
            )
            for extension in extensions
        }
        extract_enabled = {
            extension: (
                extension in stored_extract
                if stored_extract is not None
                else direct_extract[extension]
            )
            for extension in extensions
        }
        browse_extensions = {
            extension for extension, enabled in browse_enabled.items() if enabled
        }
        extract_extensions = {
            extension for extension, enabled in extract_enabled.items() if enabled
        }

        direct_browse_needs_refresh = {
            extension: self._verb_needs_refresh(
                self._container_context_verb(extension),
                self._browse_menu_label(),
            )
            for extension in extensions
        }
        direct_extract_needs_refresh = {
            extension: self._verb_needs_refresh(
                self._container_extract_context_verb(extension),
                self._shell_menu_label(
                    "Extract selected containers into same-name folders..."
                ),
                self._shell_operation_commands["extract_containers"],
                multi_select=True,
            )
            for extension in extensions
        }

        cascade_copy_registered = cascade_copy
        cascade_move_registered = cascade_move
        cascade_browse_registered = self._verb_is_registered(
            _FILE_CONTEXT_MENU_BROWSE_VERB
        )
        cascade_extract_registered = self._verb_is_registered(
            _FILE_CONTEXT_MENU_EXTRACT_VERB
        )
        cascade_browse_needs_refresh = self._verb_needs_refresh(
            _FILE_CONTEXT_MENU_BROWSE_VERB,
            self._browse_menu_label(),
            applies_to=self._extension_applies_to(browse_extensions),
        )
        cascade_extract_needs_refresh = self._verb_needs_refresh(
            _FILE_CONTEXT_MENU_EXTRACT_VERB,
            self._shell_menu_label(
                "Extract selected containers into same-name folders..."
            ),
            self._shell_operation_commands["extract_containers"],
            multi_select=True,
            applies_to=self._extension_applies_to(extract_extensions),
        )

        parent_exists = self._key_exists(hive, _FILE_CONTEXT_MENU_ROOT)
        parent_applies_to = (
            None
            if copy_enabled or move_enabled
            else self._extension_applies_to(
                browse_extensions | extract_extensions
            )
        )
        parent_current = self._cascade_menu_is_current(
            _FILE_CONTEXT_MENU_ROOT,
            parent_applies_to,
        )
        enabled_file_commands = (
            copy_enabled or move_enabled or browse_extensions or extract_extensions
        )
        direct_any = (
            direct_copy
            or direct_move
            or any(direct_browse.values())
            or any(direct_extract.values())
        )
        cascade_any = (
            cascade_copy_registered
            or cascade_move_registered
            or cascade_browse_registered
            or cascade_extract_registered
        )

        if grouped:
            submenu_needs_refresh = direct_any or (
                enabled_file_commands
                and (
                    not parent_current
                    or (copy_enabled and not cascade_copy_registered)
                    or (move_enabled and not cascade_move_registered)
                    or (browse_extensions and not cascade_browse_registered)
                    or (extract_extensions and not cascade_extract_registered)
                    or (not copy_enabled and cascade_copy_registered)
                    or (not move_enabled and cascade_move_registered)
                    or (not browse_extensions and cascade_browse_registered)
                    or (not extract_extensions and cascade_extract_registered)
                    or (copy_enabled
                        and self._verb_needs_refresh(
                            _FILE_CONTEXT_MENU_COPY_VERB,
                            self._shell_menu_label(
                                "Create MIX here and copy selected items..."
                            ),
                            self._shell_operation_commands["pack_copy"],
                            multi_select=True,
                        ))
                    or (move_enabled
                        and self._verb_needs_refresh(
                            _FILE_CONTEXT_MENU_MOVE_VERB,
                            self._shell_menu_label(
                                "Create MIX here and move selected items..."
                            ),
                            self._shell_operation_commands["pack_move"],
                            multi_select=True,
                        ))
                    or (browse_extensions and cascade_browse_needs_refresh)
                    or (extract_extensions and cascade_extract_needs_refresh)
                )
            ) or (not enabled_file_commands and (parent_exists or cascade_any))
        else:
            submenu_needs_refresh = parent_exists or cascade_any or any(
                enabled_file_commands
                and (
                    (copy_enabled and self._verb_needs_refresh(
                        _FILE_MIX_COPY_VERB,
                        self._shell_menu_label(
                            "Create MIX here and copy selected items..."
                        ),
                        self._shell_operation_commands["pack_copy"],
                        multi_select=True,
                    ))
                    or (move_enabled and self._verb_needs_refresh(
                        _FILE_MIX_MOVE_VERB,
                        self._shell_menu_label(
                            "Create MIX here and move selected items..."
                        ),
                        self._shell_operation_commands["pack_move"],
                        multi_select=True,
                    ))
                )
            ) or any(
                browse_enabled[extension]
                and direct_browse_needs_refresh[extension]
                for extension in extensions
            ) or (not copy_enabled and direct_copy) or (
                not move_enabled and direct_move
            ) or any(
                extract_enabled[extension]
                and direct_extract_needs_refresh[extension]
                for extension in extensions
            ) or any(
                not browse_enabled[extension] and direct_browse[extension]
                for extension in extensions
            ) or any(
                not extract_enabled[extension] and direct_extract[extension]
                for extension in extensions
            )

        def needs_refresh(
            enabled: bool,
            direct_registered: bool,
            cascade_registered: bool,
            direct_needs_refresh: bool = False,
            cascade_needs_refresh: bool = False,
        ) -> bool:
            if grouped:
                return enabled and (
                    direct_registered
                    or not cascade_registered
                    or not parent_current
                    or cascade_needs_refresh
                )
            return cascade_registered or (
                enabled and direct_needs_refresh
            )

        browse_needs_refresh = {
            extension: needs_refresh(
                browse_enabled[extension],
                direct_browse[extension],
                cascade_browse_registered,
                direct_browse_needs_refresh[extension],
                cascade_browse_needs_refresh,
            )
            for extension in extensions
        }
        extract_needs_refresh = {
            extension: needs_refresh(
                extract_enabled[extension],
                direct_extract[extension],
                cascade_extract_registered,
                direct_extract_needs_refresh[extension],
                cascade_extract_needs_refresh,
            )
            for extension in extensions
        }
        return {
            "context_menu_submenu": grouped,
            "context_menu_submenu_needs_refresh": submenu_needs_refresh,
            "file_context_mix_copy": copy_enabled,
            "file_context_mix_copy_needs_refresh": needs_refresh(
                copy_enabled,
                direct_copy,
                cascade_copy_registered,
                self._verb_needs_refresh(
                    _FILE_MIX_COPY_VERB,
                    self._shell_menu_label(
                        "Create MIX here and copy selected items..."
                    ),
                    self._shell_operation_commands["pack_copy"],
                    multi_select=True,
                ),
                self._verb_needs_refresh(
                    _FILE_CONTEXT_MENU_COPY_VERB,
                    self._shell_menu_label(
                        "Create MIX here and copy selected items..."
                    ),
                    self._shell_operation_commands["pack_copy"],
                    multi_select=True,
                ),
            ),
            "file_context_mix_move": move_enabled,
            "file_context_mix_move_needs_refresh": needs_refresh(
                move_enabled,
                direct_move,
                cascade_move_registered,
                self._verb_needs_refresh(
                    _FILE_MIX_MOVE_VERB,
                    self._shell_menu_label(
                        "Create MIX here and move selected items..."
                    ),
                    self._shell_operation_commands["pack_move"],
                    multi_select=True,
                ),
                self._verb_needs_refresh(
                    _FILE_CONTEXT_MENU_MOVE_VERB,
                    self._shell_menu_label(
                        "Create MIX here and move selected items..."
                    ),
                    self._shell_operation_commands["pack_move"],
                    multi_select=True,
                ),
            ),
            "container_file_context_menus": browse_enabled,
            "container_file_context_menu_needs_refresh": browse_needs_refresh,
            "container_file_extract_context_menus": extract_enabled,
            "container_file_extract_context_menu_needs_refresh": extract_needs_refresh,
            "mix_context_menu": browse_enabled.get(".mix", False),
            "mix_context_menu_needs_refresh": browse_needs_refresh.get(
                ".mix", False
            ),
        }

    def _context_menu_grouping_enabled(self) -> bool:
        import winreg

        value = self._value(
            winreg.HKEY_CURRENT_USER,
            _CONTEXT_MENU_SETTINGS_KEY,
            _CONTEXT_MENU_GROUPING_VALUE,
        )
        return True if value is None else bool(value)

    def _context_menu_bool(self, name: str) -> bool | None:
        import winreg

        value = self._value(
            winreg.HKEY_CURRENT_USER,
            _CONTEXT_MENU_SETTINGS_KEY,
            name,
        )
        return bool(value) if isinstance(value, int) else None

    def _context_menu_extensions(self, name: str) -> set[str] | None:
        import winreg

        value = self._value(
            winreg.HKEY_CURRENT_USER,
            _CONTEXT_MENU_SETTINGS_KEY,
            name,
        )
        if not isinstance(value, (tuple, list)):
            return None
        return {
            extension.casefold()
            for extension in value
            if isinstance(extension, str)
            and extension.casefold() in MIX_CONTAINER_SUFFIXES
        }

    @staticmethod
    def _extension_applies_to(extensions: set[str]) -> str | None:
        if not extensions:
            return None
        return " OR ".join(
            f'System.FileExtension:="{extension}"'
            for extension in sorted(extensions)
        )

    def _cascade_menu_is_current(
        self,
        path: str,
        applies_to: str | None,
    ) -> bool:
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        return (
            self._value(hive, path, "MUIVerb") == _APPLICATION_NAME
            and self._value(hive, path, "SubCommands") == ""
            and self._value(hive, path, "Icon") == _APPLICATION_ICON_VALUE
            and self._value(hive, path, _REGISTRATION_OWNER) == _APPLICATION_NAME
            and self._value(hive, path, "AppliesTo") == applies_to
        )

    def _write_cascade_menu(
        self,
        path: str,
        applies_to: str | None,
    ) -> None:
        import winreg

        self._delete_tree(winreg.HKEY_CURRENT_USER, path)
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, _APPLICATION_NAME)
            winreg.SetValueEx(key, "SubCommands", 0, winreg.REG_SZ, "")
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, _APPLICATION_ICON_VALUE)
            winreg.SetValueEx(
                key,
                _REGISTRATION_OWNER,
                0,
                winreg.REG_SZ,
                _APPLICATION_NAME,
            )
            if applies_to is not None:
                winreg.SetValueEx(
                    key,
                    "AppliesTo",
                    0,
                    winreg.REG_SZ,
                    applies_to,
                )

    def _write_context_menu_settings(
        self,
        *,
        grouped: bool,
        copy_enabled: bool,
        move_enabled: bool,
        browse_extensions: set[str],
        extract_extensions: set[str],
    ) -> None:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            _CONTEXT_MENU_SETTINGS_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            for name, enabled in (
                (_CONTEXT_MENU_GROUPING_VALUE, grouped),
                ("PackCopy", copy_enabled),
                ("PackMove", move_enabled),
            ):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(enabled))
            winreg.SetValueEx(
                key,
                _CONTEXT_MENU_BROWSE_EXTENSIONS_VALUE,
                0,
                winreg.REG_MULTI_SZ,
                sorted(browse_extensions),
            )
            winreg.SetValueEx(
                key,
                _CONTEXT_MENU_EXTRACT_EXTENSIONS_VALUE,
                0,
                winreg.REG_MULTI_SZ,
                sorted(extract_extensions),
            )

    def _configure_file_context_menu(
        self,
        *,
        grouped: bool,
        copy_enabled: bool,
        move_enabled: bool,
        browse_extensions: set[str],
        extract_extensions: set[str],
    ) -> None:
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        for path in (
            _FILE_MIX_COPY_VERB,
            _FILE_MIX_MOVE_VERB,
            _FILE_CONTEXT_MENU_ROOT,
            *(
                self._container_context_verb(extension)
                for extension in MIX_CONTAINER_SUFFIXES
            ),
            *(
                self._container_extract_context_verb(extension)
                for extension in MIX_CONTAINER_SUFFIXES
            ),
        ):
            self._delete_tree(hive, path)

        if grouped:
            has_commands = (
                copy_enabled
                or move_enabled
                or bool(browse_extensions)
                or bool(extract_extensions)
            )
            if has_commands:
                parent_applies_to = (
                    None
                    if copy_enabled or move_enabled
                    else self._extension_applies_to(
                        browse_extensions | extract_extensions
                    )
                )
                self._write_cascade_menu(
                    _FILE_CONTEXT_MENU_ROOT,
                    parent_applies_to,
                )
                if copy_enabled:
                    self._write_verb(
                        _FILE_CONTEXT_MENU_COPY_VERB,
                        self._shell_menu_label(
                            "Create MIX here and copy selected items..."
                        ),
                        self._shell_operation_commands["pack_copy"],
                        multi_select=True,
                    )
                if move_enabled:
                    self._write_verb(
                        _FILE_CONTEXT_MENU_MOVE_VERB,
                        self._shell_menu_label(
                            "Create MIX here and move selected items..."
                        ),
                        self._shell_operation_commands["pack_move"],
                        multi_select=True,
                    )
                if browse_extensions:
                    self._write_verb(
                        _FILE_CONTEXT_MENU_BROWSE_VERB,
                        self._browse_menu_label(),
                        applies_to=self._extension_applies_to(browse_extensions),
                    )
                if extract_extensions:
                    self._write_verb(
                        _FILE_CONTEXT_MENU_EXTRACT_VERB,
                        self._shell_menu_label(
                            "Extract selected containers into same-name folders..."
                        ),
                        self._shell_operation_commands["extract_containers"],
                        multi_select=True,
                        applies_to=self._extension_applies_to(extract_extensions),
                    )
        else:
            if copy_enabled:
                self._write_verb(
                    _FILE_MIX_COPY_VERB,
                    self._shell_menu_label(
                        "Create MIX here and copy selected items..."
                    ),
                    self._shell_operation_commands["pack_copy"],
                    multi_select=True,
                )
            if move_enabled:
                self._write_verb(
                    _FILE_MIX_MOVE_VERB,
                    self._shell_menu_label(
                        "Create MIX here and move selected items..."
                    ),
                    self._shell_operation_commands["pack_move"],
                    multi_select=True,
                )
            for extension in browse_extensions:
                self._write_verb(
                    self._container_context_verb(extension),
                    self._browse_menu_label(),
                )
            for extension in extract_extensions:
                self._write_verb(
                    self._container_extract_context_verb(extension),
                    self._shell_menu_label(
                        "Extract selected containers into same-name folders..."
                    ),
                    self._shell_operation_commands["extract_containers"],
                    multi_select=True,
                )

        self._write_context_menu_settings(
            grouped=grouped,
            copy_enabled=copy_enabled,
            move_enabled=move_enabled,
            browse_extensions=browse_extensions,
            extract_extensions=extract_extensions,
        )

    def configure(
        self,
        *,
        directory_context_menu: bool | None,
        mix_context_menu: bool | None,
        mix_new_menu: bool | None,
        mix_file_association: bool | None,
        container_file_associations: dict[str, bool] | None = None,
        container_file_context_menus: dict[str, bool] | None = None,
        file_context_mix_copy: bool | None = None,
        file_context_mix_move: bool | None = None,
        container_file_extract_context_menus: dict[str, bool] | None = None,
        context_menu_submenu: bool | None = None,
    ) -> dict[str, object]:
        if not self.is_supported():
            raise OSError("Windows shell registration is only available on Windows.")

        import winreg

        current = self.read_state()
        changed = False
        file_context_settings_requested = any(
            value is not None
            for value in (
                file_context_mix_copy,
                file_context_mix_move,
                container_file_context_menus,
                mix_context_menu,
                container_file_extract_context_menus,
                context_menu_submenu,
            )
        )
        if file_context_settings_requested:
            desired_grouping = (
                bool(current["context_menu_submenu"])
                if context_menu_submenu is None
                else bool(context_menu_submenu)
            )
            desired_copy = (
                bool(current["file_context_mix_copy"])
                if file_context_mix_copy is None
                else bool(file_context_mix_copy)
            )
            desired_move = (
                bool(current["file_context_mix_move"])
                if file_context_mix_move is None
                else bool(file_context_mix_move)
            )
            desired_browse = dict(current["container_file_context_menus"])
            if container_file_context_menus is not None:
                for extension, registered in container_file_context_menus.items():
                    normalized = extension.casefold()
                    if normalized not in MIX_CONTAINER_SUFFIXES:
                        raise ValueError(
                            f"Unsupported MIX container extension: {extension}"
                        )
                    desired_browse[normalized] = bool(registered)
            if mix_context_menu is not None:
                desired_browse[".mix"] = bool(mix_context_menu)

            desired_extract = dict(
                current["container_file_extract_context_menus"]
            )
            if container_file_extract_context_menus is not None:
                for extension, registered in container_file_extract_context_menus.items():
                    normalized = extension.casefold()
                    if normalized not in MIX_CONTAINER_SUFFIXES:
                        raise ValueError(
                            f"Unsupported MIX container extension: {extension}"
                        )
                    desired_extract[normalized] = bool(registered)

            settings_changed = (
                desired_grouping != bool(current["context_menu_submenu"])
                or desired_copy != bool(current["file_context_mix_copy"])
                or desired_move != bool(current["file_context_mix_move"])
                or desired_browse != current["container_file_context_menus"]
                or desired_extract
                != current["container_file_extract_context_menus"]
                or bool(current["context_menu_submenu_needs_refresh"])
                or any(
                    desired_browse[extension]
                    and bool(
                        current["container_file_context_menu_needs_refresh"][
                            extension
                        ]
                    )
                    for extension in MIX_CONTAINER_SUFFIXES
                )
                or any(
                    desired_extract[extension]
                    and bool(
                        current[
                            "container_file_extract_context_menu_needs_refresh"
                        ][extension]
                    )
                    for extension in MIX_CONTAINER_SUFFIXES
                )
                or (
                    desired_copy
                    and bool(current["file_context_mix_copy_needs_refresh"])
                )
                or (
                    desired_move
                    and bool(current["file_context_mix_move_needs_refresh"])
                )
            )
            if settings_changed:
                self._configure_file_context_menu(
                    grouped=desired_grouping,
                    copy_enabled=desired_copy,
                    move_enabled=desired_move,
                    browse_extensions={
                        extension
                        for extension, enabled in desired_browse.items()
                        if enabled
                    },
                    extract_extensions={
                        extension
                        for extension, enabled in desired_extract.items()
                        if enabled
                    },
                )
                changed = True
        if (
            directory_context_menu is not None
            and (
                bool(directory_context_menu)
                != bool(current["directory_context_menu"])
                or (
                    bool(directory_context_menu)
                    and bool(current["directory_context_menu_needs_refresh"])
                )
            )
        ):
            if directory_context_menu:
                self._write_verb(
                    _DIRECTORY_VERB,
                    self._browse_menu_label(),
                )
                changed = True
            elif not directory_context_menu:
                self._delete_tree(winreg.HKEY_CURRENT_USER, _DIRECTORY_VERB)
                changed = True

        if container_file_associations is not None or mix_file_association is not None:
            current_associations = dict(current["container_file_associations"])
            desired_associations = dict(current_associations)
            if container_file_associations is not None:
                for extension, registered in container_file_associations.items():
                    normalized = extension.casefold()
                    if normalized not in MIX_CONTAINER_SUFFIXES:
                        raise ValueError(
                            f"Unsupported MIX container extension: {extension}"
                        )
                    desired_associations[normalized] = bool(registered)
            if mix_file_association is not None:
                desired_associations[".mix"] = bool(mix_file_association)
            needs_refresh = current["container_file_association_needs_refresh"]
            if desired_associations != current_associations or any(
                desired_associations[extension] and bool(needs_refresh[extension])
                for extension in MIX_CONTAINER_SUFFIXES
            ):
                self._configure_container_file_associations(desired_associations)
                changed = True

        if (
            mix_new_menu is not None
            and (
                bool(mix_new_menu) != bool(current["mix_new_menu"])
                or (
                    bool(mix_new_menu)
                    and bool(current["mix_new_menu_needs_refresh"])
                )
            )
        ):
            if mix_new_menu:
                self._register_mix_new_menu()
            else:
                self._unregister_mix_new_menu()
            changed = True

        if changed:
            self._notify_shell_changed()
        return self.read_state()

    @staticmethod
    def _key_exists(hive, path: str) -> bool:
        import winreg

        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ):
                return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _value(hive, path: str, name: str) -> object | None:
        import winreg

        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return value
        except FileNotFoundError:
            return None

    @staticmethod
    def _value_exists(hive, path: str, name: str) -> bool:
        import winreg

        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                for index in range(winreg.QueryInfoKey(key)[1]):
                    value_name, _, _ = winreg.EnumValue(key, index)
                    if value_name.casefold() == name.casefold():
                        return True
        except FileNotFoundError:
            return False
        return False

    def _command_belongs_to_application(self, command: object) -> bool:
        if not isinstance(command, str):
            return False
        normalized = command.casefold().rstrip()
        return normalized.endswith('--open-path "%1"') or any(
            normalized == expected.casefold()
            for expected in self._shell_operation_commands.values()
        )

    def _verb_is_registered(self, path: str) -> bool:
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        command = self._value(hive, path + r"\command", "")
        owner = self._value(hive, path, _REGISTRATION_OWNER)
        return (
            isinstance(self._value(hive, path, ""), str)
            and isinstance(command, str)
            and (owner == _APPLICATION_NAME or self._command_belongs_to_application(command))
        )

    def _verb_needs_refresh(
        self,
        path: str,
        label: str,
        command_expected: str | None = None,
        *,
        multi_select: bool = False,
        applies_to: str | None = None,
    ) -> bool:
        if not self._verb_is_registered(path):
            return False
        import winreg

        command = self._value(
            winreg.HKEY_CURRENT_USER,
            path + r"\command",
            "",
        )
        expected_command = command_expected or self._open_command
        return (
            self._value(winreg.HKEY_CURRENT_USER, path, "") != label
            or command != expected_command
            or self._value(winreg.HKEY_CURRENT_USER, path, "Icon")
            != _APPLICATION_ICON_VALUE
            or self._value(winreg.HKEY_CURRENT_USER, path, "MultiSelectModel")
            != ("Player" if multi_select else None)
            or self._value(winreg.HKEY_CURRENT_USER, path, "AppliesTo")
            != applies_to
        )

    @staticmethod
    def _shell_menu_label(source: str, *arguments: object) -> str:
        from PySide6.QtCore import QCoreApplication, QTranslator

        # Explorer reads this registry label directly, outside the app's active translator.
        QCoreApplication.translate("WindowsShellRegistry", source)

        try:
            import ctypes

            language_id = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
        except (AttributeError, OSError, TypeError, ValueError):
            language_id = 0

        if (language_id & 0x03FF) == 0x0004:
            catalog_path = (
                Path(__file__).resolve().parents[2]
                / "translations"
                / "ra2ayrmb_zh_CN.qm"
            )
            translator = QTranslator()
            if translator.load(str(catalog_path)):
                translated = translator.translate("WindowsShellRegistry", source)
                if translated:
                    return translated.format(*arguments)

        return source.format(*arguments)

    @staticmethod
    def _browse_menu_label() -> str:
        return WindowsShellRegistry._shell_menu_label(
            "Browse with {0}",
            APPLICATION_DISPLAY_NAME,
        )

    def _container_handler_is_registered(self, extension: str) -> bool:
        import winreg

        extension = extension.casefold()
        progid = _CONTAINER_PROGIDS[extension]
        progid_key = _CONTAINER_PROGID_KEYS[extension]
        open_with_key = _extension_open_with_key(extension)
        registered_apps = (
            self._value(
                winreg.HKEY_CURRENT_USER,
                _REGISTERED_APPLICATIONS,
                _APPLICATION_NAME,
            ),
            self._value(
                winreg.HKEY_CURRENT_USER,
                _REGISTERED_APPLICATIONS,
                _LEGACY_APPLICATION_NAME,
            ),
        )
        if not any(
            isinstance(value, str)
            and value.casefold() == _CAPABILITIES_PATH.casefold()
            for value in registered_apps
        ):
            return False
        command = self._value(
            winreg.HKEY_CURRENT_USER,
            progid_key + r"\shell\open\command",
            "",
        )
        owner = self._value(
            winreg.HKEY_CURRENT_USER,
            progid_key,
            _REGISTRATION_OWNER,
        )
        open_with = self._value_exists(
            winreg.HKEY_CURRENT_USER,
            open_with_key,
            progid,
        )
        capability_progid = self._value(
            winreg.HKEY_CURRENT_USER,
            _CAPABILITIES_KEY + r"\FileAssociations",
            extension,
        )
        return (
            isinstance(command, str)
            and (owner == _APPLICATION_NAME or self._command_belongs_to_application(command))
            and capability_progid == progid
            and open_with
        )

    def _container_handler_needs_refresh(self, extension: str) -> bool:
        if not self._container_handler_is_registered(extension):
            return False
        import winreg

        extension = extension.casefold()
        progid = _CONTAINER_PROGIDS[extension]
        progid_key = _CONTAINER_PROGID_KEYS[extension]
        command = self._value(
            winreg.HKEY_CURRENT_USER,
            progid_key + r"\shell\open\command",
            "",
        )
        icon = self._value(
            winreg.HKEY_CURRENT_USER,
            progid_key + r"\DefaultIcon",
            "",
        )
        registered_app_path = self._value(
            winreg.HKEY_CURRENT_USER,
            _REGISTERED_APPLICATIONS,
            _APPLICATION_NAME,
        )
        legacy_app_path = self._value(
            winreg.HKEY_CURRENT_USER,
            _REGISTERED_APPLICATIONS,
            _LEGACY_APPLICATION_NAME,
        )
        capabilities_path_is_current = (
            isinstance(registered_app_path, str)
            and registered_app_path.casefold() == _CAPABILITIES_PATH.casefold()
        )
        legacy_capabilities_path_remains = (
            isinstance(legacy_app_path, str)
            and legacy_app_path.casefold() == _CAPABILITIES_PATH.casefold()
        )
        capability_progid = self._value(
            winreg.HKEY_CURRENT_USER,
            _CAPABILITIES_KEY + r"\FileAssociations",
            extension,
        )
        open_with_is_registered = self._value_exists(
            winreg.HKEY_CURRENT_USER,
            _extension_open_with_key(extension),
            progid,
        )
        return (
            command != self._open_command
            or icon != f'"{_CONTAINER_ICON_PATHS[extension]}",0'
            or not capabilities_path_is_current
            or legacy_capabilities_path_remains
            or capability_progid != progid
            or not open_with_is_registered
        )

    def _container_is_default(self, extension: str) -> bool:
        import winreg

        extension = extension.casefold()
        progid = _CONTAINER_PROGIDS[extension]
        user_choice = self._value(
            winreg.HKEY_CURRENT_USER,
            _extension_user_choice_key(extension),
            "ProgId",
        )
        if user_choice is not None:
            if not isinstance(user_choice, str):
                return False
            if user_choice.casefold() == progid.casefold():
                return True
            selected_command = self._value(
                winreg.HKEY_CLASSES_ROOT,
                user_choice + r"\shell\open\command",
                "",
            )
            return self._command_belongs_to_application(selected_command)
        current_class = self._value(
            winreg.HKEY_CLASSES_ROOT,
            extension,
            "",
        )
        if not isinstance(current_class, str):
            return False
        if current_class.casefold() == progid.casefold():
            return True
        current_command = self._value(
            winreg.HKEY_CLASSES_ROOT,
            current_class + r"\shell\open\command",
            "",
        )
        return self._command_belongs_to_application(current_command)

    def _write_verb(
        self,
        path: str,
        label: str,
        command: str | None = None,
        *,
        multi_select: bool = False,
        applies_to: str | None = None,
    ) -> None:
        import winreg

        self._delete_tree(winreg.HKEY_CURRENT_USER, path)
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, label)
            winreg.SetValueEx(
                key,
                "Icon",
                0,
                winreg.REG_SZ,
                _APPLICATION_ICON_VALUE,
            )
            winreg.SetValueEx(
                key,
                _REGISTRATION_OWNER,
                0,
                winreg.REG_SZ,
                _APPLICATION_NAME,
            )
            if multi_select:
                winreg.SetValueEx(
                    key,
                    "MultiSelectModel",
                    0,
                    winreg.REG_SZ,
                    "Player",
                )
            if applies_to is not None:
                winreg.SetValueEx(
                    key,
                    "AppliesTo",
                    0,
                    winreg.REG_SZ,
                    applies_to,
                )
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            path + r"\command",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                "",
                0,
                winreg.REG_SZ,
                command or self._open_command,
            )

    @staticmethod
    def _container_context_verb(extension: str) -> str:
        return (
            rf"Software\Classes\SystemFileAssociations\{extension}"
            rf"\shell\{_CONTAINER_VERB_NAME}"
        )

    @staticmethod
    def _container_extract_context_verb(extension: str) -> str:
        return (
            rf"Software\Classes\SystemFileAssociations\{extension}"
            rf"\shell\{_CONTAINER_EXTRACT_VERB_NAME}"
        )

    def _mix_new_menu_is_registered(self) -> bool:
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        return any(
            self._value(hive, path, _MIX_SHELL_NEW_OWNER) == _APPLICATION_NAME
            for path in (_MIX_SHELL_NEW, _MIX_NESTED_SHELL_NEW)
        ) or (
            self._value(hive, _MIX_EXTENSION, _MIX_NEW_EXTENSION_DEFAULT_OWNER)
            == _APPLICATION_NAME
        ) or (
            self._value(hive, _MIX_NEW_PROGID_KEY, _MIX_SHELL_NEW_OWNER)
            == _APPLICATION_NAME
        ) or (
            self._value(hive, _MIX_SHELL_NEW_BACKUP, _MIX_SHELL_NEW_OWNER)
            == _APPLICATION_NAME
        )

    def _mix_new_menu_needs_refresh(self) -> bool:
        if not self._mix_new_menu_is_registered():
            return False
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        current_shell_new_is_registered = (
            self._value(hive, _MIX_SHELL_NEW, _MIX_SHELL_NEW_OWNER)
            == _APPLICATION_NAME
            and self._value(hive, _MIX_SHELL_NEW, "Data")
            == EMPTY_MIX_ARCHIVE_HEADER
            and self._value(hive, _MIX_SHELL_NEW, "MenuText")
            == _MIX_SHELL_NEW_MENU_TEXT
            and self._value(hive, _MIX_SHELL_NEW, "ItemName")
            == _MIX_SHELL_NEW_MENU_TEXT
            and self._value(hive, _MIX_SHELL_NEW, "IconPath")
            == _MIX_SHELL_NEW_ICON_PATH
            and self._value(hive, _MIX_SHELL_NEW, "NullFile") is None
        )
        has_legacy_shell_new = (
            self._value(hive, _MIX_NESTED_SHELL_NEW, _MIX_SHELL_NEW_OWNER)
            == _APPLICATION_NAME
        )
        has_legacy_progid = (
            self._value(hive, _MIX_NEW_PROGID_KEY, _MIX_SHELL_NEW_OWNER)
            == _APPLICATION_NAME
            and self._value(
                hive,
                _MIX_NEW_PROGID_KEY + r"\shell\open\command",
                "",
            ) is not None
        )
        has_stale_extension_default = (
            self._value(hive, _MIX_EXTENSION, _MIX_NEW_EXTENSION_DEFAULT_OWNER)
            == _APPLICATION_NAME
            and (
                self._value(hive, _MIX_EXTENSION, "") != _MIX_NEW_PROGID
                or self._value(hive, _MIX_NEW_PROGID_KEY, _MIX_SHELL_NEW_OWNER)
                != _APPLICATION_NAME
            )
        )
        effective_extension_default = self._value(
            winreg.HKEY_CLASSES_ROOT,
            _MIX_EXTENSION_NAME,
            "",
        )
        extension_type_needs_registration = not effective_extension_default or (
            isinstance(effective_extension_default, str)
            and effective_extension_default.casefold() == _MIX_NEW_PROGID.casefold()
            and self._value(hive, _MIX_NEW_PROGID_KEY, _MIX_SHELL_NEW_OWNER)
            != _APPLICATION_NAME
        )
        return (
            not current_shell_new_is_registered
            or has_legacy_shell_new
            or has_legacy_progid
            or has_stale_extension_default
            or self._mix_shell_new_cache_contains_mix() is False
            or extension_type_needs_registration
        )

    def _register_mix_new_menu(self) -> None:
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        self._unregister_mix_new_menu()
        if self._key_exists(hive, _MIX_SHELL_NEW):
            self._backup_foreign_mix_shell_new(hive)
            self._delete_tree(hive, _MIX_SHELL_NEW)
        self._register_mix_new_extension_type()

        with winreg.CreateKeyEx(
            hive,
            _MIX_SHELL_NEW,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                _MIX_SHELL_NEW_OWNER,
                0,
                winreg.REG_SZ,
                _APPLICATION_NAME,
            )
            winreg.SetValueEx(
                key,
                "MenuText",
                0,
                winreg.REG_SZ,
                _MIX_SHELL_NEW_MENU_TEXT,
            )
            winreg.SetValueEx(
                key,
                "ItemName",
                0,
                winreg.REG_SZ,
                _MIX_SHELL_NEW_MENU_TEXT,
            )
            winreg.SetValueEx(
                key,
                "IconPath",
                0,
                winreg.REG_SZ,
                _MIX_SHELL_NEW_ICON_PATH,
            )
            winreg.SetValueEx(
                key,
                "Data",
                0,
                winreg.REG_BINARY,
                EMPTY_MIX_ARCHIVE_HEADER,
            )
        self._refresh_mix_shell_new_cache()

    def _register_mix_new_extension_type(self) -> None:
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        if self._value(winreg.HKEY_CLASSES_ROOT, _MIX_EXTENSION_NAME, ""):
            return

        extension_owner = self._value(
            hive,
            _MIX_EXTENSION,
            _MIX_NEW_EXTENSION_DEFAULT_OWNER,
        )
        extension_default = self._value(hive, _MIX_EXTENSION, "")
        if extension_default and extension_default != _MIX_NEW_PROGID:
            return
        if extension_owner not in (None, _APPLICATION_NAME):
            raise OSError(
                "The .mix extension default is already managed by another registration."
            )

        progid_owner = self._value(hive, _MIX_NEW_PROGID_KEY, _MIX_SHELL_NEW_OWNER)
        if (
            self._key_exists(hive, _MIX_NEW_PROGID_KEY)
            and progid_owner != _APPLICATION_NAME
        ):
            raise OSError(
                "The MIX New menu file type is already registered differently."
            )

        with winreg.CreateKeyEx(
            hive,
            _MIX_NEW_PROGID_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                "",
                0,
                winreg.REG_SZ,
                _MIX_SHELL_NEW_MENU_TEXT,
            )
            winreg.SetValueEx(
                key,
                "FriendlyTypeName",
                0,
                winreg.REG_SZ,
                _MIX_SHELL_NEW_MENU_TEXT,
            )
            winreg.SetValueEx(
                key,
                _MIX_SHELL_NEW_OWNER,
                0,
                winreg.REG_SZ,
                _APPLICATION_NAME,
            )

        with winreg.CreateKeyEx(
            hive,
            _MIX_EXTENSION,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, _MIX_NEW_PROGID)
            winreg.SetValueEx(
                key,
                _MIX_NEW_EXTENSION_DEFAULT_OWNER,
                0,
                winreg.REG_SZ,
                _APPLICATION_NAME,
            )

    def _unregister_mix_new_menu(self) -> None:
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        if (
            self._value(hive, _MIX_SHELL_NEW, _MIX_SHELL_NEW_OWNER)
            == _APPLICATION_NAME
        ):
            self._delete_tree(hive, _MIX_SHELL_NEW)

        self._unregister_owned_mix_new_menu(hive, _MIX_NESTED_SHELL_NEW)

        if (
            self._value(hive, _MIX_NEW_PROGID_KEY, _MIX_SHELL_NEW_OWNER)
            == _APPLICATION_NAME
        ):
            self._delete_tree(hive, _MIX_NEW_PROGID_KEY)

        if (
            self._value(hive, _MIX_EXTENSION, _MIX_NEW_EXTENSION_DEFAULT_OWNER)
            == _APPLICATION_NAME
        ):
            self._delete_value_if_equal(
                hive,
                _MIX_EXTENSION,
                "",
                _MIX_NEW_PROGID,
            )
            self._delete_value_if_equal(
                hive,
                _MIX_EXTENSION,
                _MIX_NEW_EXTENSION_DEFAULT_OWNER,
                _APPLICATION_NAME,
            )
        self._delete_key_if_empty(hive, _MIX_NESTED_SHELL_NEW_CLASS)
        self._restore_mix_shell_new_backup(hive)
        self._delete_key_if_empty(hive, _MIX_EXTENSION)
        self._refresh_mix_shell_new_cache()

    def _backup_foreign_mix_shell_new(self, hive) -> None:
        import winreg

        try:
            with winreg.OpenKey(hive, _MIX_SHELL_NEW, 0, winreg.KEY_READ) as key:
                subkey_count, value_count, _ = winreg.QueryInfoKey(key)
                if subkey_count:
                    raise OSError(
                        "The existing .mix New menu entry has nested registry keys "
                        "and cannot be replaced safely."
                    )
                values = [
                    winreg.EnumValue(key, index)
                    for index in range(value_count)
                ]
        except FileNotFoundError:
            return

        entries = []
        for name, value, value_type in values:
            if isinstance(value, bytes):
                encoded_value = {
                    "encoding": "base64",
                    "value": base64.b64encode(value).decode("ascii"),
                }
            else:
                encoded_value = {"encoding": "json", "value": value}
            entries.append(
                {
                    "name": name,
                    "type": value_type,
                    "data": encoded_value,
                }
            )

        if self._key_exists(hive, _MIX_SHELL_NEW_BACKUP):
            if (
                self._value(hive, _MIX_SHELL_NEW_BACKUP, _MIX_SHELL_NEW_OWNER)
                != _APPLICATION_NAME
            ):
                raise OSError(
                    "The MIX New menu backup location is already in use."
                )
            self._delete_tree(hive, _MIX_SHELL_NEW_BACKUP)
        try:
            with winreg.CreateKeyEx(
                hive,
                _MIX_SHELL_NEW_BACKUP,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key,
                    _MIX_SHELL_NEW_OWNER,
                    0,
                    winreg.REG_SZ,
                    _APPLICATION_NAME,
                )
                winreg.SetValueEx(
                    key,
                    "Values",
                    0,
                    winreg.REG_SZ,
                    json.dumps(entries, ensure_ascii=True),
                )
        except Exception:
            if (
                self._value(hive, _MIX_SHELL_NEW_BACKUP, _MIX_SHELL_NEW_OWNER)
                == _APPLICATION_NAME
            ):
                self._delete_tree(hive, _MIX_SHELL_NEW_BACKUP)
            raise

    def _restore_mix_shell_new_backup(self, hive) -> None:
        import winreg

        if (
            self._value(hive, _MIX_SHELL_NEW_BACKUP, _MIX_SHELL_NEW_OWNER)
            != _APPLICATION_NAME
        ):
            return
        if self._key_exists(hive, _MIX_SHELL_NEW):
            self._delete_tree(hive, _MIX_SHELL_NEW_BACKUP)
            return

        serialized = self._value(hive, _MIX_SHELL_NEW_BACKUP, "Values")
        if not isinstance(serialized, str):
            raise OSError("The previous .mix New menu registration backup is invalid.")
        try:
            entries = json.loads(serialized)
        except (TypeError, ValueError) as error:
            raise OSError(
                "The previous .mix New menu registration backup is invalid."
            ) from error

        with winreg.CreateKeyEx(
            hive,
            _MIX_SHELL_NEW,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            for entry in entries:
                data = entry["data"]
                value = (
                    base64.b64decode(data["value"])
                    if data["encoding"] == "base64"
                    else data["value"]
                )
                winreg.SetValueEx(
                    key,
                    entry["name"],
                    0,
                    entry["type"],
                    value,
                )
        self._delete_tree(hive, _MIX_SHELL_NEW_BACKUP)

    def _refresh_mix_shell_new_cache(self) -> None:
        import winreg

        hive = winreg.HKEY_CURRENT_USER
        if not self._key_exists(hive, _SHELL_NEW_CACHE):
            return
        try:
            with winreg.OpenKey(
                hive,
                _SHELL_NEW_CACHE,
                0,
                winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
            ) as key:
                classes, value_type = winreg.QueryValueEx(key, "Classes")
                if value_type != winreg.REG_MULTI_SZ or not isinstance(classes, list):
                    return
                updated = [
                    value
                    for value in classes
                    if value.casefold() != _MIX_EXTENSION_NAME
                ]
                if self._mix_extension_has_shell_new_item():
                    updated.append(_MIX_EXTENSION_NAME)
                if updated != classes:
                    winreg.SetValueEx(key, "Classes", 0, value_type, updated)
        except FileNotFoundError:
            return

    @staticmethod
    def _mix_shell_new_cache_contains_mix() -> bool | None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                _SHELL_NEW_CACHE,
                0,
                winreg.KEY_QUERY_VALUE,
            ) as key:
                classes, value_type = winreg.QueryValueEx(key, "Classes")
        except FileNotFoundError:
            return None
        if value_type != winreg.REG_MULTI_SZ or not isinstance(classes, list):
            return None
        return any(
            isinstance(extension, str)
            and extension.casefold() == _MIX_EXTENSION_NAME
            for extension in classes
        )

    @staticmethod
    def _mix_extension_has_shell_new_item() -> bool:
        import winreg

        hive = winreg.HKEY_CLASSES_ROOT
        if WindowsShellRegistry._key_exists(
            hive,
            _MIX_EXTENSION_NAME + r"\ShellNew",
        ):
            return True
        try:
            with winreg.OpenKey(
                hive,
                _MIX_EXTENSION_NAME,
                0,
                winreg.KEY_READ,
            ) as key:
                subkey_count = winreg.QueryInfoKey(key)[0]
                subkeys = [winreg.EnumKey(key, index) for index in range(subkey_count)]
        except FileNotFoundError:
            return False
        return any(
            WindowsShellRegistry._key_exists(
                hive,
                _MIX_EXTENSION_NAME + "\\" + subkey + r"\ShellNew",
            )
            for subkey in subkeys
        )

    def _unregister_owned_mix_new_menu(self, hive, path: str) -> bool:
        if self._value(hive, path, _MIX_SHELL_NEW_OWNER) != _APPLICATION_NAME:
            return False
        self._delete_value_if_equal(hive, path, "Data", EMPTY_MIX_ARCHIVE_HEADER)
        self._delete_value_if_equal(hive, path, "NullFile", None)
        self._delete_value_if_equal(
            hive,
            path,
            "MenuText",
            _MIX_SHELL_NEW_MENU_TEXT,
        )
        self._delete_value_if_equal(
            hive,
            path,
            "ItemName",
            _MIX_SHELL_NEW_MENU_TEXT,
        )
        self._delete_value_if_equal(
            hive,
            path,
            "IconPath",
            _MIX_SHELL_NEW_ICON_PATH,
        )
        self._delete_value_if_equal(
            hive,
            path,
            _MIX_SHELL_NEW_OWNER,
            _APPLICATION_NAME,
        )
        self._delete_key_if_empty(hive, path)
        return True

    def _register_container_handlers(self, extensions: set[str]) -> None:
        import winreg

        if not extensions:
            return
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            _CAPABILITIES_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "ApplicationName", 0, winreg.REG_SZ, _APPLICATION_NAME)
            winreg.SetValueEx(
                key,
                "ApplicationDescription",
                0,
                winreg.REG_SZ,
                "Browse Red Alert 2 and Yuri's Revenge MIX archives.",
            )
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            _REGISTERED_APPLICATIONS,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(
                key,
                _APPLICATION_NAME,
                0,
                winreg.REG_SZ,
                _CAPABILITIES_PATH,
            )
        for extension in sorted(extensions):
            progid = _CONTAINER_PROGIDS[extension]
            progid_key = _CONTAINER_PROGID_KEYS[extension]
            icon_path = _CONTAINER_ICON_PATHS[extension]
            self._delete_tree(winreg.HKEY_CURRENT_USER, progid_key)
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                progid_key,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(
                    key,
                    "",
                    0,
                    winreg.REG_SZ,
                    f"RA2AYRMB {extension[1:].upper()} Archive",
                )
                winreg.SetValueEx(
                    key,
                    "FriendlyTypeName",
                    0,
                    winreg.REG_SZ,
                    f"{extension[1:].upper()} archive",
                )
                winreg.SetValueEx(
                    key,
                    _REGISTRATION_OWNER,
                    0,
                    winreg.REG_SZ,
                    _APPLICATION_NAME,
                )
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                progid_key + r"\DefaultIcon",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{icon_path}",0')
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                progid_key + r"\shell\open\command",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, self._open_command)
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                _extension_open_with_key(extension),
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, progid, 0, winreg.REG_NONE, b"")
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                _CAPABILITIES_KEY + r"\FileAssociations",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                winreg.SetValueEx(key, extension, 0, winreg.REG_SZ, progid)
        self._delete_value_if_equal(
            winreg.HKEY_CURRENT_USER,
            _REGISTERED_APPLICATIONS,
            _LEGACY_APPLICATION_NAME,
            _CAPABILITIES_PATH,
        )

    def _unregister_container_handler(self, extension: str) -> None:
        import winreg

        extension = extension.casefold()
        progid = _CONTAINER_PROGIDS[extension]
        self._delete_value_if_equal(
            winreg.HKEY_CURRENT_USER,
            _extension_open_with_key(extension),
            progid,
            None,
        )
        self._delete_value_if_equal(
            winreg.HKEY_CURRENT_USER,
            _extension_class_key(extension),
            "",
            progid,
        )
        self._delete_value_if_equal(
            winreg.HKEY_CURRENT_USER,
            _CAPABILITIES_KEY + r"\FileAssociations",
            extension,
            progid,
        )
        self._delete_tree(
            winreg.HKEY_CURRENT_USER,
            _CONTAINER_PROGID_KEYS[extension],
        )

    def _configure_container_file_associations(
        self,
        desired: dict[str, bool],
    ) -> None:
        for extension, registered in desired.items():
            if registered:
                self._register_container_handlers({extension})
            else:
                self._unregister_container_handler(extension)

        import winreg

        if not any(desired.values()):
            for name in (_APPLICATION_NAME, _LEGACY_APPLICATION_NAME):
                self._delete_value_if_equal(
                    winreg.HKEY_CURRENT_USER,
                    _REGISTERED_APPLICATIONS,
                    name,
                    _CAPABILITIES_PATH,
                )
            self._delete_tree(winreg.HKEY_CURRENT_USER, _CAPABILITIES_KEY)

    @staticmethod
    def _key_has_values_or_subkeys(hive, path: str) -> bool:
        import winreg

        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                subkey_count, value_count, _ = winreg.QueryInfoKey(key)
        except FileNotFoundError:
            return False
        return bool(subkey_count or value_count)

    @staticmethod
    def _delete_key_if_empty(hive, path: str) -> None:
        import winreg

        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
                subkey_count, value_count, _ = winreg.QueryInfoKey(key)
            if subkey_count == 0 and value_count == 0:
                winreg.DeleteKey(hive, path)
        except FileNotFoundError:
            return

    @staticmethod
    def _delete_value_if_equal(hive, path: str, name: str, expected: object | None) -> None:
        import winreg

        try:
            with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
                value, _ = winreg.QueryValueEx(key, name)
                if expected is not None and value != expected:
                    return
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            return

    @staticmethod
    def _delete_tree(hive, path: str) -> None:
        import winreg

        while True:
            try:
                with winreg.OpenKey(
                    hive,
                    path,
                    0,
                    winreg.KEY_READ | winreg.KEY_WRITE,
                ) as key:
                    try:
                        child = winreg.EnumKey(key, 0)
                    except OSError:
                        child = None
            except FileNotFoundError:
                return
            if child is None:
                break
            WindowsShellRegistry._delete_tree(hive, path + "\\" + child)
        try:
            winreg.DeleteKey(hive, path)
        except FileNotFoundError:
            pass

    @staticmethod
    def _notify_shell_changed() -> None:
        import ctypes

        try:
            ctypes.windll.shell32.SHChangeNotify(
                0x08000000,
                0x1000,
                None,
                None,
            )
        except (AttributeError, OSError):
            pass
