"""Linux-only integration tests using a real Home Assistant bootstrap.

Only MQTT network delivery is replaced; HA loader, config flows, entity
platforms, registries, services, and cleanup all execute their production code.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from homeassistant import bootstrap, loader
from homeassistant.core import HomeAssistant

if sys.platform != "linux":
    raise pytest.UsageError("Run tests_ha in Linux CI with the selected Home Assistant version")


@pytest_asyncio.fixture
async def hass(tmp_path):
    source = Path(__file__).resolve().parents[1] / "custom_components/ha_windows_bridge"
    shutil.copytree(source, tmp_path / "custom_components/ha_windows_bridge",
                    ignore=shutil.ignore_patterns("__pycache__"))
    instance = HomeAssistant(str(tmp_path))
    loader.async_setup(instance)
    config = {"homeassistant": {"name": "Phase 0", "latitude": 52.0, "longitude": 21.0,
                                "elevation": 100, "unit_system": "metric", "time_zone": "UTC",
                                "country": "PL"}, "http": {"server_host": "127.0.0.1"}}
    try:
        assert await bootstrap.async_from_config_dict(config, instance) is instance
        yield instance
    finally:
        await instance.async_stop(force=True)
        await instance.async_block_till_done()
