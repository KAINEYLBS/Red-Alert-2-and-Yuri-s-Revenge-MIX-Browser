# -----------------------------------------------------------------------------
# Copyright (c) 2024, PyInstaller Development Team.
#
# Distributed under the terms of the GNU General Public License (version 2
# or later) with exception for distributing the bootloader.
#
# SPDX-License-Identifier: GPL-2.0-or-later WITH Bootloader-exception
# -----------------------------------------------------------------------------

import fnmatch
from pathlib import Path

from PyInstaller.utils.hooks.setuptools import setuptools_info


datas = [
    (source, destination)
    for source, destination in setuptools_info.vendored_data
    if fnmatch.fnmatch(
        source.replace("\\", "/"),
        "**/setuptools/_vendor/jaraco/text/*",
    )
    and Path(source).name != "Lorem ipsum.txt"
]
