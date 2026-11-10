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
    def __init__(self, open_command: str) -> None:
        self._open_command = open_command

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
        container_file_context_menus = {
            extension: self._verb_is_registered(
                self._container_context_verb(extension)
            )
            for extension in sorted(MIX_CONTAINER_SUFFIXES)
        }
        container_file_context_menu_needs_refresh = {
            extension: self._verb_needs_refresh(
                self._container_context_verb(extension),
                browse_label,
            )
            for extension in sorted(MIX_CONTAINER_SUFFIXES)
        }
        return {
            "supported": True,
            "directory_context_menu": self._verb_is_registered(_DIRECTORY_VERB),
            "mix_context_menu": container_file_context_menus.get(".mix", False),
            "container_file_context_menus": container_file_context_menus,
            "container_file_context_menu_needs_refresh": container_file_context_menu_needs_refresh,
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
            "mix_context_menu_needs_refresh": container_file_context_menu_needs_refresh.get(
                ".mix", False
            ),
            "mix_new_menu_needs_refresh": self._mix_new_menu_needs_refresh(),
            "mix_file_association_needs_refresh": container_file_association_needs_refresh.get(
                ".mix", False
            ),
        }

    def configure(
        self,
        *,
        directory_context_menu: bool | None,
        mix_context_menu: bool | None,
        mix_new_menu: bool | None,
        mix_file_association: bool | None,
        container_file_associations: dict[str, bool] | None = None,
        container_file_context_menus: dict[str, bool] | None = None,
    ) -> dict[str, object]:
        if not self.is_supported():
            raise OSError("Windows shell registration is only available on Windows.")

        import winreg

        current = self.read_state()
        changed = False
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

        if mix_context_menu is not None or container_file_context_menus is not None:
            current_context_menus = dict(current["container_file_context_menus"])
            desired_context_menus = dict(current_context_menus)
            if container_file_context_menus is not None:
                for extension, registered in container_file_context_menus.items():
                    normalized = extension.casefold()
                    if normalized not in MIX_CONTAINER_SUFFIXES:
                        raise ValueError(
                            f"Unsupported MIX container extension: {extension}"
                        )
                    desired_context_menus[normalized] = bool(registered)
            if mix_context_menu is not None:
                desired_context_menus[".mix"] = bool(mix_context_menu)
            context_needs_refresh = current[
                "container_file_context_menu_needs_refresh"
            ]
            if desired_context_menus != current_context_menus or any(
                desired_context_menus[extension]
                and bool(context_needs_refresh[extension])
                for extension in MIX_CONTAINER_SUFFIXES
            ):
                for extension, registered in desired_context_menus.items():
                    verb = self._container_context_verb(extension)
                    if registered:
                        self._write_verb(verb, self._browse_menu_label())
                    else:
                        self._delete_tree(winreg.HKEY_CURRENT_USER, verb)
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
        return (
            isinstance(command, str)
            and command.casefold().rstrip().endswith('--open-path "%1"')
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

    def _verb_needs_refresh(self, path: str, label: str) -> bool:
        if not self._verb_is_registered(path):
            return False
        import winreg

        command = self._value(
            winreg.HKEY_CURRENT_USER,
            path + r"\command",
            "",
        )
        return (
            self._value(winreg.HKEY_CURRENT_USER, path, "") != label
            or command != self._open_command
            or self._value(winreg.HKEY_CURRENT_USER, path, "Icon")
            != _APPLICATION_ICON_VALUE
        )

    @staticmethod
    def _browse_menu_label() -> str:
        from PySide6.QtCore import QCoreApplication, QTranslator

        source = "Browse with {0}"
        # Explorer reads this registry label directly, outside the app's active translator.
        QCoreApplication.translate("WindowsShellRegistry", "Browse with {0}")

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
                    return translated.format(APPLICATION_DISPLAY_NAME)

        return source.format(APPLICATION_DISPLAY_NAME)

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

    def _write_verb(self, path: str, label: str) -> None:
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
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            path + r"\command",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, self._open_command)

    @staticmethod
    def _container_context_verb(extension: str) -> str:
        return (
            rf"Software\Classes\SystemFileAssociations\{extension}"
            rf"\shell\{_CONTAINER_VERB_NAME}"
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
