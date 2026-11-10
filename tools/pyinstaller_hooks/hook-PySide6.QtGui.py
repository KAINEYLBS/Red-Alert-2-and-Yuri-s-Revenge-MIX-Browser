from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [
    (source, destination)
    for source, destination in binaries
    if (
        Path(source).name.casefold() == "qwindows.dll"
        and Path(source).parent.name.casefold() == "platforms"
    )
    or (
        Path(source).name.casefold() == "qico.dll"
        and Path(source).parent.name.casefold() == "imageformats"
    )
]
