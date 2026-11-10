from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from mix_browser.features.browser.document_data import (
    DecodedDocument,
    DocumentPreviewResult,
    decode_document,
)


# @arch mix-browser.document-preview-pane component | en: Presents decoded document text in the preview area | zh: 在预览区呈现解码后的文档文本
class DocumentPreviewPane(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(280)

        self.content = QPlainTextEdit(self)
        self.content.setReadOnly(True)
        self.content.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.content.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.content.setPlaceholderText(self.tr("Select a text document to preview."))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.content, 1)

    def show_empty(self) -> None:
        self.content.clear()
        self.content.setPlaceholderText(self.tr("Select a text document to preview."))

    def show_loading(self) -> None:
        self.content.clear()
        self.content.setPlaceholderText(self.tr("Loading preview..."))

    def show_result(self, result: DocumentPreviewResult, encoding: str) -> DecodedDocument:
        if encoding == result.detected_encoding:
            decoded = DecodedDocument(result.text, result.line_endings, result.message)
        else:
            decoded = decode_document(result.data, encoding, truncated=result.truncated)
        self.content.setPlaceholderText("")
        self.content.setPlainText(self.tr(decoded.message) if decoded.message else decoded.text)
        return decoded
