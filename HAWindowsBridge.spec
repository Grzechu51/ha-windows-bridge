# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("pycaw") + collect_submodules("winrt")
hiddenimports.append("winrt.windows.foundation")
hiddenimports.append("winrt.windows.foundation.collections")
hiddenimports.append("winrt.windows.media.control")
hiddenimports.append("winrt.windows.storage.streams")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets/icon.png", "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
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
