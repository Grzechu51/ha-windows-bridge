from __future__ import annotations

from ha_windows_bridge.updater import parse_release


def test_release_parser_detects_newer_semantic_version() -> None:
    result = parse_release(
        {
            "tag_name": "v1.2.0",
            "html_url": "https://github.com/Grzechu51/ha-windows-bridge/releases/tag/v1.2.0",
        },
        "1.1.0",
    )

    assert result.available is True
    assert result.latest_version == "1.2.0"
    assert result.release_url.endswith("/tag/v1.2.0")
    assert result.error == ""


def test_release_parser_rejects_untrusted_or_invalid_urls() -> None:
    result = parse_release(
        {"tag_name": "v1.1.0", "html_url": "https://example.invalid/download.exe"},
        "1.1.0",
    )

    assert result.available is False
    assert result.release_url == ""


def test_release_parser_handles_invalid_payload() -> None:
    result = parse_release({"tag_name": "nightly", "html_url": ""}, "1.1.0")

    assert result.available is False
    assert result.error
