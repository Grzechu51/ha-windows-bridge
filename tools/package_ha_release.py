"""Build the HA source ZIP without caches and refresh release checksums."""
from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from ha_windows_bridge import __version__

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "dist"
    component = ROOT / "custom_components" / "ha_windows_bridge"
    with ZipFile(output / f"HA-Windows-Bridge-HA-Integration-{__version__}.zip", "w", ZIP_DEFLATED) as archive:
        for path in sorted(component.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, path.relative_to(ROOT))
        for name in ("hacs.json", "HOME_ASSISTANT_INTEGRATION.md", "LICENSE"):
            archive.write(ROOT / name, name)
        archive.write(ROOT / "docs" / "V2_QUICKSTART.md", "START.md")
    names = [f"HA-Windows-Bridge-{__version__}-win64.zip",
             f"HA-Windows-Bridge-HA-Integration-{__version__}.zip",
             f"HA-Windows-Bridge-Setup-{__version__}.exe"]
    checksums = []
    for name in names:
        with (output / name).open("rb") as stream:
            checksums.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {name}")
    (output / f"SHA256SUMS-{__version__}.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print("HA package and release checksums updated")


if __name__ == "__main__":
    main()
