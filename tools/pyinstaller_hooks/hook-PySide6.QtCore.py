from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
datas = [
    (source, destination)
    for source, destination in datas
    if Path(source).name == "qtbase_zh_CN.qm"
]
