from __future__ import annotations

import locale
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from mix_browser.features.archive.domain import MixArchiveIndex, MixEntry, read_mix_entry_prefix
from mix_browser.features.browser.file_type_support import (
    DOCUMENT_PREVIEW_SUFFIXES as _DOCUMENT_SUFFIXES,
    MAX_TEXT_PREVIEW_BYTES as _MAX_DOCUMENT_PREVIEW_BYTES,
)


# @arch mix-browser.decoded-document model | en: Holds decoded text and its line-ending summary | zh: 保存解码文本及其换行符摘要
@dataclass(frozen=True)
class DecodedDocument:
    text: str
    line_endings: str
    message: str | None = None


# @arch mix-browser.document-preview-result model | en: Holds document preview bytes and detected text metadata | zh: 保存文档预览字节与检测到的文本信息
@dataclass(frozen=True)
class DocumentPreviewResult:
    data: bytes = b""
    detected_encoding: str = "ansi"
    text: str = ""
    line_endings: str = "Unknown"
    message: str | None = None
    truncated: bool = False


# @arch mix-browser.document-preview service | en: Reads and decodes text entries from MIX archives | zh: 从 MIX 归档读取并解码文本条目
def load_document_preview(archive: MixArchiveIndex, entry: MixEntry) -> DocumentPreviewResult:
    suffix = Path(entry.name or "").suffix.casefold()
    if (entry.file_type or "").upper() not in {"INI", "TXT"} and suffix not in _DOCUMENT_SUFFIXES:
        return DocumentPreviewResult(
            message=QCoreApplication.translate(
                "DocumentPreviewPane",
                "Document preview is not available for this file type.",
            )
        )

    data = read_mix_entry_prefix(archive, entry, max_bytes=_MAX_DOCUMENT_PREVIEW_BYTES)
    if data is None:
        return DocumentPreviewResult(
            message=QCoreApplication.translate(
                "DocumentPreviewPane", "The document could not be read from the archive."
            )
        )

    truncated = entry.size > len(data)
    encoding = _detect_encoding(data, truncated=truncated)
    decoded = decode_document(data, encoding, truncated=truncated)
    return DocumentPreviewResult(
        data=data,
        detected_encoding=encoding,
        text=decoded.text,
        line_endings=decoded.line_endings,
        message=decoded.message,
        truncated=truncated,
    )


# @arch mix-browser.document-decoder service | en: Decodes text using a requested codec and summarizes line endings | zh: 使用指定编码解码文本并汇总换行符
def decode_document(data: bytes, encoding: str, *, truncated: bool = False) -> DecodedDocument:
    payload = data
    if payload.startswith(b"\xef\xbb\xbf"):
        payload = payload[3:]
    elif payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        payload = payload[2:]

    try:
        text = payload.decode(_codec_name(encoding), errors="replace")
    except LookupError:
        return DecodedDocument(
            "",
            "Unknown",
            QCoreApplication.translate(
                "DocumentPreviewPane", "Encoding is not available: {0}"
            ).format(encoding),
        )
    if not _looks_like_text(text):
        return DecodedDocument(
            "",
            "Unknown",
            QCoreApplication.translate(
                "DocumentPreviewPane",
                "This entry does not appear to contain readable text.",
            ),
        )
    return DecodedDocument(text, _line_ending_summary(text, sample=truncated))


def _detect_encoding(data: bytes, *, truncated: bool) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8"
    if data.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if data.startswith(b"\xfe\xff"):
        return "utf-16-be"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if truncated and exc.end >= len(data) - 4:
            return "utf-8"
        return "ansi"
    return "utf-8" if any(byte >= 0x80 for byte in data) else "ansi"


def _codec_name(encoding: str) -> str:
    if encoding == "ansi":
        if sys.platform == "win32":
            import ctypes

            return f"cp{ctypes.windll.kernel32.GetACP()}"
        return locale.getpreferredencoding(False) or "cp1252"
    return encoding


def _looks_like_text(text: str) -> bool:
    if "\0" in text:
        return False
    if not text:
        return True
    readable = sum(character.isprintable() or character in "\r\n\t\f" for character in text)
    return readable / len(text) >= 0.9


def _line_ending_summary(text: str, *, sample: bool) -> str:
    crlf_count = text.count("\r\n")
    remainder = text.replace("\r\n", "")
    endings = []
    if crlf_count:
        endings.append("CRLF")
    if "\n" in remainder:
        endings.append("LF")
    if "\r" in remainder:
        endings.append("CR")
    if not endings:
        summary = "None"
    elif len(endings) == 1:
        summary = endings[0]
    else:
        summary = f"Mixed ({', '.join(endings)})"
    return f"{summary} (sample)" if sample else summary
