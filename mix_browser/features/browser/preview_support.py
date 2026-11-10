from __future__ import annotations

from PySide6.QtCore import QT_TRANSLATE_NOOP, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mix_browser.features.browser.file_type_support import (
    MAX_DAT_PREVIEW_BYTES,
    MAX_IMAGE_PREVIEW_BYTES,
    MAX_IMAGE_PREVIEW_PIXELS,
    MAX_MEDIA_PREVIEW_BYTES,
    MAX_TEXT_PREVIEW_BYTES,
    PREVIEW_FORMAT_GROUPS,
)


def _mib_text(size_bytes: int) -> str:
    return f"{size_bytes // (1024 * 1024)} MiB"


# @arch mix-browser.preview-support-dialog component | en: Lists file formats and limits available in the preview pane | zh: 列出预览区支持的文件格式和限制
class PreviewSupportDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Preview Support"))
        self.setMinimumSize(620, 480)
        available = self.screen().availableGeometry()
        self.resize(
            max(self.minimumWidth(), min(760, available.width() - 32)),
            max(self.minimumHeight(), min(680, available.height() - 64)),
        )

        layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)

        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        formats_group = QGroupBox(self.tr("Supported formats"), content)
        formats_layout = QFormLayout(formats_group)
        formats_layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        formats_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        formats_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        for label, suffixes in PREVIEW_FORMAT_GROUPS:
            self._add_format_row(formats_layout, label, ", ".join(suffixes))
        content_layout.addWidget(formats_group)

        details_group = QGroupBox(self.tr("Details"), content)
        details_layout = QVBoxLayout(details_group)
        detail_messages = (
            (
                QT_TRANSLATE_NOOP(
                    "PreviewSupportDialog",
                    "PAL previews support Westwood raw, JASC, and RIFF palettes.",
                ),
                (),
            ),
            (
                QT_TRANSLATE_NOOP(
                    "PreviewSupportDialog",
                    "MMP files are previewed as PCX only when their content has a valid PCX signature.",
                ),
                (),
            ),
            (
                QT_TRANSLATE_NOOP(
                    "PreviewSupportDialog",
                    "DAT preview supports recognized XCC MIX name databases only; entries larger than {0} cannot be previewed.",
                ),
                (_mib_text(MAX_DAT_PREVIEW_BYTES),),
            ),
            (
                QT_TRANSLATE_NOOP(
                    "PreviewSupportDialog",
                    "SHP and PCX previews are limited to {0:,} decoded pixels. SHP, PCX, and VXL entries larger than {1} cannot be previewed.",
                ),
                (
                    MAX_IMAGE_PREVIEW_PIXELS,
                    _mib_text(MAX_IMAGE_PREVIEW_BYTES),
                ),
            ),
            (
                QT_TRANSLATE_NOOP(
                    "PreviewSupportDialog",
                    "VXL previews show voxel geometry without HVA transforms or limb animation. HVA files have no standalone preview.",
                ),
                (),
            ),
            (
                QT_TRANSLATE_NOOP(
                    "PreviewSupportDialog",
                    "Text entries are truncated at {0}. WAV and Bink entries larger than {1} cannot be previewed.",
                ),
                (
                    _mib_text(MAX_TEXT_PREVIEW_BYTES),
                    _mib_text(MAX_MEDIA_PREVIEW_BYTES),
                ),
            ),
            (
                QT_TRANSLATE_NOOP(
                    "PreviewSupportDialog",
                    "Directories and MIX archives are browsed as containers; they do not have a preview of their own.",
                ),
                (),
            ),
        )
        for source, arguments in detail_messages:
            text = self.tr(source).format(*arguments) if arguments else self.tr(source)
            label = QLabel(text, details_group)
            label.setWordWrap(True)
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            details_layout.addWidget(label)
        content_layout.addWidget(details_group)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_format_row(
        self,
        layout: QFormLayout,
        label: str,
        formats: str,
    ) -> None:
        value = QLabel(formats, layout.parentWidget())
        value.setMinimumWidth(0)
        value.setWordWrap(True)
        value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        value.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        layout.addRow(self.tr(label), value)
