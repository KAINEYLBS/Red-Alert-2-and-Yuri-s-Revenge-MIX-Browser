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


_PREVIOUS_RELEASE_VERSION = "1.0.0b1"
_RELEASE_HISTORY = (
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
            items = f"<li>{escape(self.tr('Resolved some issues.'))}</li>"
            sections.append(f"<h3>{escape(heading)}</h3><ul>{items}</ul>")
        browser.setHtml("".join(sections))
        layout.addWidget(browser, 1)
        return page

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
