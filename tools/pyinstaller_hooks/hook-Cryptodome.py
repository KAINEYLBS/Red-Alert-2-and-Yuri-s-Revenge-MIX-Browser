from pathlib import Path

from PyInstaller.compat import EXTENSION_SUFFIXES
from PyInstaller.utils.hooks import get_module_file_attribute


cipher_directory = Path(get_module_file_attribute("Cryptodome.Cipher")).parent
binaries = []
for module_name in ("_raw_blowfish", "_raw_ecb"):
    for suffix in EXTENSION_SUFFIXES:
        for source in cipher_directory.glob(f"{module_name}{suffix}"):
            binaries.append((str(source), "Cryptodome/Cipher"))

if {Path(source).name.split(".", 1)[0] for source, _ in binaries} != {
    "_raw_blowfish",
    "_raw_ecb",
}:
    raise RuntimeError("PyCryptodome Blowfish and ECB native modules were not found.")
