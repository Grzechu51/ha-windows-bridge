from __future__ import annotations

import os
import sys
import traceback
from contextlib import suppress
from pathlib import Path


def _run() -> int:
    try:
        from ha_windows_bridge.desktop import main
    except ImportError:
        # A packaged smoke test must fail without opening PyInstaller's
        # interactive traceback dialog, otherwise a broken release build can
        # block CI indefinitely.
        if "--smoke-test" in sys.argv:
            diagnostic_path = os.environ.get("HA_WINDOWS_BRIDGE_SMOKE_LOG", "").strip()
            if diagnostic_path:
                with suppress(OSError):
                    Path(diagnostic_path).write_text(traceback.format_exc(), encoding="utf-8")
            return 86
        raise
    try:
        return main()
    except Exception:
        if "--smoke-test" not in sys.argv:
            raise
        diagnostic_path = os.environ.get("HA_WINDOWS_BRIDGE_SMOKE_LOG", "").strip()
        if diagnostic_path:
            with suppress(OSError):
                Path(diagnostic_path).write_text(traceback.format_exc(), encoding="utf-8")
        return 87


if __name__ == "__main__":
    raise SystemExit(_run())
