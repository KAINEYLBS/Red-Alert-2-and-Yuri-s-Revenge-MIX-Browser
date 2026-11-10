from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from mix_browser.features.archive.type_detection import (
    CONTENT_TYPE_SUFFIX_OVERRIDES,
    detect_content_type_for_suffix,
)


# @arch mix-browser.directory-entry model | en: Describes a filesystem entry shown by the browser | zh: 描述浏览器列出的文件系统条目
@dataclass(frozen=True)
class DirectoryEntry:
    path: Path
    is_directory: bool
    file_type: str
    size: int
    modified: float


# @arch mix-browser.directory-listing service | en: Lists and classifies the direct children of a directory | zh: 列出并识别目录的直接子项
def load_directory_entries(directory: Path) -> tuple[DirectoryEntry, ...]:
    entries = []
    for path in directory.iterdir():
        try:
            metadata = path.stat()
            is_directory = stat.S_ISDIR(metadata.st_mode)
            if is_directory:
                file_type = "Folder"
            else:
                raw_suffix = path.suffix.casefold()
                suffix = raw_suffix[1:].upper()
                expected_content_type = CONTENT_TYPE_SUFFIX_OVERRIDES.get(raw_suffix)
                if suffix and expected_content_type is None:
                    file_type = suffix
                else:
                    with path.open("rb") as source:
                        prefix = source.read(128)
                    file_type = (
                        detect_content_type_for_suffix(
                            prefix,
                            metadata.st_size,
                            raw_suffix,
                        )
                        or suffix
                        or "File"
                    )
            entries.append(
                DirectoryEntry(
                    path=path,
                    is_directory=is_directory,
                    file_type=file_type,
                    size=metadata.st_size,
                    modified=metadata.st_mtime,
                )
            )
        except OSError:
            continue
    entries.sort(key=lambda item: (not item.is_directory, item.path.name.casefold()))
    return tuple(entries)
