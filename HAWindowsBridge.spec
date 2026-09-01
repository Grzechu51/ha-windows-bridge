# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def _is_foreign_windows_icu(binary):
    """Reject ICU builds accidentally discovered in an external PATH entry.

    Qt for Windows links against the system ``icuuc.dll``.  Packaging another
    project's version (for example Poppler's versioned ICU) makes QtCore fail
    during startup with ERROR_PROC_NOT_FOUND.
    """
    target_name = str(binary[0]).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return target_name == "icuuc.dll" or target_name.startswith("icudt")

hiddenimports = (
    collect_submodules("pycaw")
    + collect_submodules("dxcam")
    + ["qrcode", "qrcode.image.pil"]
    + collect_submodules("winrt")
)
hiddenimports.append("winrt.windows.foundation")
hiddenimports.append("winrt.windows.foundation.collections")
hiddenimports.append("winrt.windows.media.control")
hiddenimports.append("winrt.windows.storage.streams")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets/icon.png", "assets")] + collect_data_files("qtawesome"),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
a.binaries = [binary for binary in a.binaries if not _is_foreign_windows_icu(binary)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HA Windows Bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon="assets/icon.ico",
    version="assets/version_info.txt",
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HA Windows Bridge",
)
