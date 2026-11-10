from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from mix_browser import __version__
from mix_browser.shared.application_identity import (
    APPLICATION_FULL_NAME,
    GITHUB_PROJECT_URL,
)


# @arch mix-browser.about-dialog component | en: Presents application identity, implementation technologies, and supported interfaces | zh: 展示程序信息、实现技术与支持的接口
class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("About {0}").format(APPLICATION_FULL_NAME))
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        identity_layout = QHBoxLayout()
        application_icon = QLabel(self)
        application_icon.setFixedSize(64, 64)
        application_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_path = Path(__file__).resolve().parents[2] / "data" / "icons" / "MIX-EXE.ico"
        icon_pixmap = QIcon(str(icon_path)).pixmap(QSize(64, 64))
        if not icon_pixmap.isNull():
            application_icon.setPixmap(icon_pixmap)
        identity_layout.addWidget(application_icon)

        name = QLabel(APPLICATION_FULL_NAME, self)
        name.setStyleSheet("font-size: 20px; font-weight: 600;")
        identity_layout.addWidget(name, 1)
        layout.addLayout(identity_layout)

        version = re.fullmatch(r"(\d+(?:\.\d+)*)b(\d+)", __version__)
        if version:
            beta_number = int(version.group(2))
            version_text = f"{version.group(1)} beta"
            if beta_number:
                version_text = f"{version_text} {beta_number}"
        else:
            version_text = __version__
        version_label = QLabel(
            self.tr("Version: {0}").format(version_text),
            self,
        )
        license_label = QLabel(self.tr("License: MIT"), self)
        author_label = QLabel(
            self.tr("Author: {0}").format("KAINEYLB小卡"),
            self,
        )
        metadata_layout = QHBoxLayout()
        metadata_layout.addWidget(version_label)
        metadata_layout.addSpacing(16)
        metadata_layout.addWidget(license_label)
        metadata_layout.addSpacing(16)
        metadata_layout.addWidget(author_label)
        metadata_layout.addStretch(1)
        layout.addLayout(metadata_layout)

        project_started_label = QLabel(self.tr("Project started: October 31, 2026"), self)
        layout.addWidget(project_started_label)

        github_row = QHBoxLayout()
        github_icon = QLabel(self)
        github_icon.setFixedSize(20, 20)
        github_icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        icon_path = Path(__file__).resolve().parents[2] / "data" / "icons" / "github.svg"
        try:
            icon_data = icon_path.read_bytes()
        except OSError:
            icon_data = b""
        icon_color = (
            self.palette()
            .color(QPalette.ColorRole.ButtonText)
            .name()
            .encode("ascii")
        )
        icon_renderer = QSvgRenderer(
            QByteArray(icon_data.replace(b"#181717", icon_color))
        )
        if icon_renderer.isValid():
            icon_pixmap = QPixmap(github_icon.size())
            icon_pixmap.fill(Qt.GlobalColor.transparent)
            icon_painter = QPainter(icon_pixmap)
            icon_renderer.render(icon_painter)
            icon_painter.end()
            github_icon.setPixmap(icon_pixmap)
        github_row.addWidget(github_icon)

        github_link = QLabel(self)
        github_link.setText(f'<a href="{GITHUB_PROJECT_URL}">{GITHUB_PROJECT_URL}</a>')
        github_link.setOpenExternalLinks(True)
        github_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        github_link.setWordWrap(True)
        github_row.addWidget(github_link, 1)
        layout.addLayout(github_row)

        description = QLabel(
            self.tr(
                "Browse and manage Red Alert 2 and Yuri's Revenge MIX archives "
                "alongside local game files."
            ),
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        technology_stack = QGroupBox(self.tr("Technology Stack"), self)
        technology_layout = QVBoxLayout(technology_stack)
        technology_text = QLabel(
            self.tr("Language: Python 3.10+\nGUI framework: PySide6"),
            technology_stack,
        )
        technology_text.setWordWrap(True)
        technology_layout.addWidget(technology_text)
        layout.addWidget(technology_stack)

        application_interfaces = QGroupBox(self.tr("Application Interfaces"), self)
        interfaces_layout = QVBoxLayout(application_interfaces)
        interfaces_text = QLabel(
            self.tr(
                "Desktop: mix-browser\n"
                "CLI: mix-browser-cli, with structured JSON output\n"
                "MCP: mix-browser-mcp (Model Context Protocol), using local stdio\n\n"
                "CLI and MCP expose directory and MIX operations, recursive search, "
                "type detection, and supported preview data."
            ),
            application_interfaces,
        )
        interfaces_text.setWordWrap(True)
        interfaces_layout.addWidget(interfaces_text)
        layout.addWidget(application_interfaces)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
