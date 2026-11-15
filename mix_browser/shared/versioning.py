from __future__ import annotations

import re


_BETA_VERSION = re.compile(r"(\d+(?:\.\d+)*)b(\d+)")


# @arch mix-browser.display-version utility | en: Formats application versions for user-facing labels | zh: 格式化供界面显示的应用版本号
def format_display_version(version: str) -> str:
    match = _BETA_VERSION.fullmatch(version)
    if match is None:
        return version
    return f"{match.group(1)} beta {match.group(2)}"
