"""Package an already smoke-tested local preview; never publish or install it."""
from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def main():
    from ha_windows_bridge import __version__
    directory = ROOT / "dist" / "v2-alpha"
    application = directory / "HA Windows Bridge"
    if not (application / "HA Windows Bridge.exe").is_file():
        raise FileNotFoundError("Build the v2 preview before packaging")
    with ZipFile(directory / f"HA-Windows-Bridge-{__version__}-win64.zip", "w", ZIP_DEFLATED) as archive:
        for path in sorted(application.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(application))
        archive.write(ROOT / "LICENSE", "LICENSE")
        archive.write(ROOT / "docs" / "V2_QUICKSTART.md", "START.md")
    with ZipFile(directory / f"HA-Windows-Bridge-HA-Integration-{__version__}.zip", "w", ZIP_DEFLATED) as archive:
        component = ROOT / "custom_components" / "ha_windows_bridge"
        for path in sorted(component.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, path.relative_to(ROOT))
        archive.write(ROOT / "LICENSE", "LICENSE")
        archive.write(ROOT / "docs" / "V2_QUICKSTART.md", "START.md")
    for path in sorted(directory.glob("*.zip")):
        print(path)


if __name__ == "__main__":
    main()
