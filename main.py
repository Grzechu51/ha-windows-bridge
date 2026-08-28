from __future__ import annotations

import sys


def _run() -> int:
    try:
        from ha_windows_bridge.app import main
    except ImportError:
        # A packaged smoke test must fail without opening PyInstaller's
        # interactive traceback dialog, otherwise a broken release build can
        # block CI indefinitely.
        if "--smoke-test" in sys.argv:
            return 86
        raise
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
