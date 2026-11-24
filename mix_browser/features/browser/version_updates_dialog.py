from __future__ import annotations

from html import escape

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from mix_browser import __version__
from mix_browser.shared.versioning import format_display_version


_PREVIOUS_RELEASE_VERSION = "1.1.0"
_RELEASE_HISTORY = (
    (
        "1.0.0",
        "1.1.0",
    ),
    (
        "1.0.0b1",
        "1.0.0",
    ),
    (
        "1.0.0b0",
        "1.0.0b1",
    ),
)


# @arch mix-browser.version-updates-dialog component | en: Presents current and historical release notes | zh: 展示当前版本和历史版本更新内容
class VersionUpdatesDialog(QDialog):
    def __init__(
        self,
        *,
        show_dont_show_again: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Version Updates"))
        self.setMinimumSize(560, 400)
        self.resize(620, 440)
        self._dont_show_checkbox: QCheckBox | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self._heading = QLabel(
            self.tr("What's new in {0}").format(
                format_display_version(__version__)
            ),
            self,
        )
        self._heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(self._heading)

        self._pages = QStackedWidget(self)
        previous_version = format_display_version(_PREVIOUS_RELEASE_VERSION)
        self._pages.addWidget(
            self._notes_page(
                self.tr("Changes since {0}").format(previous_version),
                (
                    self.tr(
                        "Added an optional orbit view for voxel previews, with adjustable viewing direction and elevation, including top-down and bottom-up views."
                    ),
                    self.tr(
                        "SHP previews now identify selected frames that contain no image data."
                    ),
                    self.tr(
                        "Previews now show the format-defined transparent palette index's color by default, with a preference to display that index as transparent."
                    ),
                    self.tr(
                        "Corrected automatic palette selection for theater-specific assets, animation variants, buildings, and loading screens."
                    ),
                    self.tr(
                        "Palette candidates can be grouped by use in the preview and Preferences; palettes with multiple identified uses are marked accordingly."
                    ),
                    self.tr(
                        "Preview zoom now stays anchored at the pointer, and automatic palette changes no longer cause a brief flash."
                    ),
                    self.tr(
                        "Sortable table headers reserve space for sort indicators and the clear-sort control so labels are not clipped."
                    ),
                ),
            )
        )
        self._pages.addWidget(self._history_page())
        layout.addWidget(self._pages, 1)

        actions = QHBoxLayout()
        if show_dont_show_again:
            self._dont_show_checkbox = QCheckBox(
                self.tr(
                    "Don't show this window automatically again for this version"
                ),
                self,
            )
            self._dont_show_checkbox.setChecked(True)
            actions.addWidget(self._dont_show_checkbox)
        actions.addStretch(1)

        self._history_button = QPushButton(self.tr("Release history..."), self)
        self._history_button.clicked.connect(self._show_history)
        actions.addWidget(self._history_button)
        self._back_button = QPushButton(self.tr("Back to latest"), self)
        self._back_button.clicked.connect(self._show_latest)
        self._back_button.hide()
        actions.addWidget(self._back_button)
        close_button = QPushButton(self.tr("Close"), self)
        close_button.clicked.connect(self.accept)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    @property
    def dont_show_again(self) -> bool:
        return (
            self._dont_show_checkbox is not None
            and self._dont_show_checkbox.isChecked()
        )

    def _notes_page(self, heading: str, notes: tuple[str, ...]) -> QWidget:
        page = QWidget(self._pages)
        layout = QVBoxLayout(page)
        subtitle = QLabel(heading, page)
        subtitle.setProperty("visualRole", "description")
        layout.addWidget(subtitle)
        browser = QTextBrowser(page)
        browser.setOpenExternalLinks(False)
        browser.setFrameShape(QFrame.Shape.NoFrame)
        browser.setHtml(
            "<ul>"
            + "".join(f"<li>{escape(note)}</li>" for note in notes)
            + "</ul>"
        )
        layout.addWidget(browser, 1)
        return page

    def _history_page(self) -> QWidget:
        page = QWidget(self._pages)
        layout = QVBoxLayout(page)
        browser = QTextBrowser(page)
        browser.setOpenExternalLinks(False)
        browser.setFrameShape(QFrame.Shape.NoFrame)
        sections = []
        for start_version, end_version in _RELEASE_HISTORY:
            heading = self.tr("Changes from {0} to {1}").format(
                format_display_version(start_version),
                format_display_version(end_version),
            )
            items = "".join(
                f"<li>{escape(note)}</li>"
                for note in self._release_history_notes(end_version)
            )
            sections.append(f"<h3>{escape(heading)}</h3><ul>{items}</ul>")
        browser.setHtml("".join(sections))
        layout.addWidget(browser, 1)
        return page

    def _release_history_notes(self, end_version: str) -> tuple[str, ...]:
        if end_version == "1.1.0":
            return (
                self.tr(
                    "Added animated HVA pose previews for paired VXL models, with frame selection and an autoplay setting separate from SHP previews."
                ),
                self.tr(
                    "VXL/HVA previews use model-based framing; VXL rendering is faster, and unit-palette selection is more reliable."
                ),
                self.tr(
                    "Choose backgrounds for image, video, and voxel previews; status text adapts for contrast, and optional asset boundaries are available for SHP, VXL/HVA, and video previews."
                ),
                self.tr(
                    "Added MIX operations to create an archive from selected items by moving or copying them, and to extract an archive into a same-name folder."
                ),
                self.tr(
                    "File Explorer commands can create a MIX or extract supported containers in lightweight mode, and can be grouped under a submenu."
                ),
                self.tr(
                    "Added in-app File Explorer context actions: blank space in a folder listing opens that folder; a filesystem item or tab opens its containing folder with the target selected."
                ),
                self.tr(
                    "MIX entry previews now use detected content types, so supported files can preview even when their stored filename extension is misleading."
                ),
                self.tr(
                    "Unified table row selection and hover styles across the application; status colors remain readable in normal, hovered, and selected rows, and table headers are resizable and fill the available width by default."
                ),
                self.tr(
                    "Browser filtering recalculates alternating row backgrounds from visible rows and restores a temporarily hidden selection to view when its filter is re-enabled."
                ),
                self.tr(
                    "Browser and search tables support secondary sorting with Shift-click; sorting keeps selected rows selected and visible."
                ),
                self.tr(
                    "Press Enter to open the current table row, just like double-click; Enter does nothing when multiple rows are selected."
                ),
                self.tr(
                    "Added an in-app interaction guide for less-visible actions; detailed sorting instructions are in the ? button of each table header."
                ),
                self.tr(
                    "Lightweight archive dialogs show per-item validation, let users edit MIX item names, and can be configured to appear only when conflicts or errors need attention."
                ),
                self.tr(
                    "Archive creation and extraction are available through the CLI and MCP interfaces as well as the desktop UI."
                ),
            )
        if end_version == "1.0.0b1":
            return (self.tr("Resolved some issues."),)
        if end_version == "1.0.0":
            return (
                self.tr(
                    "Removed redundant output-device re-detection during VLC playback, fixing the audio dropouts caused by that logic while still following the system's active output device."
                ),
                self.tr(
                    "Fixed seeking and resuming audio or video previews after playback ends."
                ),
                self.tr(
                    "With external output devices, playback may still lose its opening audio segment; uninterrupted playback is unaffected."
                ),
                self.tr(
                    "Only supported file types are previewed; rapid selection changes wait briefly before starting a preview, keeping file switching responsive."
                ),
                self.tr(
                    "Video previews now distinguish media preparation from a ready video that has not started playing."
                ),
                self.tr(
                    "Startup and first folder or MIX opening are faster; the preview surface is prepared before the first browser tab."
                ),
                self.tr(
                    "Fixed inconsistent widget styling between source and packaged builds, and corrected rounded corners in progress windows."
                ),
                self.tr("Windows file-handler status messages are clearer."),
                self.tr(
                    "Preferences, imported palettes, the optional community database, and persistent default-app samples now live under the portable user-data folder beside the executable."
                ),
                self.tr(
                    "Version 1.0.0 reads data only from user-data and does not import older files automatically. Before first launch, copy these items from beside the old executable to beside the new executable: RA2AYRMB.ini -> user-data/RA2AYRMB.ini; user-palettes/ -> user-data/user-palettes/; name-sources/ -> user-data/name-sources/; system-integration/ -> user-data/system-integration/. For future updates, copy the entire user-data/ folder."
                ),
            )
        return ()

    def _show_history(self) -> None:
        self._heading.setText(self.tr("Release history"))
        self._pages.setCurrentIndex(1)
        self._history_button.hide()
        self._back_button.show()

    def _show_latest(self) -> None:
        self._heading.setText(
            self.tr("What's new in {0}").format(
                format_display_version(__version__)
            )
        )
        self._pages.setCurrentIndex(0)
        self._history_button.show()
        self._back_button.hide()
