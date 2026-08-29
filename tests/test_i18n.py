from __future__ import annotations

import logging

from ha_windows_bridge.i18n import LocalizedFormatter, set_active_language


def test_new_log_records_follow_current_language() -> None:
    formatter = LocalizedFormatter("%(message)s")
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "Zapisano konfigurację",
        (),
        None,
    )

    set_active_language("en")
    assert formatter.format(record) == "Configuration saved"
    set_active_language("pl")
    assert formatter.format(record) == "Zapisano konfigurację"
