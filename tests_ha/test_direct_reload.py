"""Real HA reload/dispatch with a fake, credential-checking socket boundary."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import queue
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import websocket
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.config_entries import SOURCE_MQTT, ConfigEntryState
from test_runtime import DOMAIN, announcement, mqtt_info
from test_runtime import wire as wire

from ha_windows_bridge.communication.schema import Capability
from ha_windows_bridge.communication.state import ConnectionState
from ha_windows_bridge.config import AppConfig, HomeAssistantConfig
from ha_windows_bridge.core.events import EventBus


@pytest.fixture
def client(monkeypatch):
    # The default TopicProtocol constructor imports Windows audio via discovery.
    # Supply a protocol explicitly, while running the exact transport source.
    protocol_import = ModuleType("ha_windows_bridge.communication.protocol")
    protocol_import.TopicProtocol = None
    source = Path(__file__).parents[1] / "ha_windows_bridge/communication/home_assistant.py"
    spec = importlib.util.spec_from_file_location("ha_windows_bridge.communication._isolated_client", source)
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as seam:
        seam.setitem(sys.modules, protocol_import.__name__, protocol_import)
        spec.loader.exec_module(module)
    return module


class SocketBoundary:
    """Fake auth accepts one synthetic credential; HA dispatch is unmodified."""

    def __init__(self, hass):
        self.hass = hass
        self.sockets = []
        self.permission = True
        self.token = "isolated-synthetic-token"

    def create(self, *_args, **_kwargs):
        sock = FakeSocket(self)
        self.sockets.append(sock)
        return sock


class FakeSocket:
    def __init__(self, boundary):
        self.boundary = boundary
        self.frames = queue.Queue()
        self.frames.put({"type": "auth_required"})
        self.sent = []
        self.closed = False
        self.connection = None

    def send(self, raw):
        value = json.loads(raw)
        self.sent.append(value)
        if value["type"] == "auth":
            accepted = value["access_token"] == self.boundary.token
            self.frames.put({"type": "auth_ok" if accepted else "auth_invalid"})
            if accepted:
                self.boundary.hass.loop.call_soon_threadsafe(self._make_connection)
            return
        self.boundary.hass.loop.call_soon_threadsafe(self._dispatch, value)

    def _make_connection(self):
        self.connection = ActiveConnection(
            logging.getLogger("isolated-direct-reload"), self.boundary.hass,
            self._receive, SimpleNamespace(
                name="Isolated test", id="synthetic-user",
                permissions=SimpleNamespace(check_entity=lambda *_args: self.boundary.permission),
            ), None, "127.0.0.1",
        )

    def _dispatch(self, value):
        assert self.connection is not None
        self.connection.async_handle(value)

    def _receive(self, raw):
        self.frames.put(json.loads(raw) if isinstance(raw, (str, bytes)) else raw)

    def recv(self):
        try:
            return json.dumps(self.frames.get(timeout=1))
        except queue.Empty:
            raise websocket.WebSocketTimeoutException() from None

    def settimeout(self, _timeout):
        pass

    def close(self, **_kwargs):
        self.closed = True
        if self.connection is not None:
            self.boundary.hass.loop.call_soon_threadsafe(self.connection.async_handle_close)


async def configured(hass):
    payload = announcement()
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload),
    )
    entry = (await hass.config_entries.flow.async_configure(flow["flow_id"], {}))["result"]
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED
    return entry, payload


def transport(boundary, client):
    config = AppConfig(
        device_id="phase0_pc", overlay_enabled=True,
        home_assistant=HomeAssistantConfig(
            enabled=True, url="http://isolated.invalid", token=boundary.token,
        ),
    )
    protocol = SimpleNamespace(
        session="isolated-stable-session",
        capabilities=lambda: SimpleNamespace(capabilities=(Capability("overlay.show", ("direct",)),)),
    )
    return client.HomeAssistantTransport(
        config, EventBus(), lambda _value: None,
        socket_factory=boundary.create, protocol=protocol,
    )


async def discover(hass, payload):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=mqtt_info(payload),
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort" and result["reason"] == "already_configured"


async def heartbeat_error(transport, monkeypatch, client):
    times = iter((100.0, 131.0))
    monkeypatch.setattr(client, "time", SimpleNamespace(monotonic=lambda: next(times)))
    with pytest.raises(client.HomeAssistantConnectionError) as error:
        await asyncio.to_thread(transport._read_events, transport._socket, 1)
    return error.value


async def test_reload_proof_unchanged_credentials_reconnect_and_old_callbacks_are_isolated(hass, wire, monkeypatch, client):
    entry, payload = await configured(hass)
    boundary = SocketBoundary(hass)
    direct = transport(boundary, client)
    direct._epoch = direct.machine.begin()
    await asyncio.to_thread(direct._connect)
    assert direct.machine.connected(direct._epoch)
    first = boundary.sockets[0]
    old_runtime = entry.runtime_data
    old_disconnect = first.connection.subscriptions[1]
    assert old_runtime.owner is first.connection and old_runtime.available
    # A changed discovery must still reload the real entry.
    payload["device"]["sw_version"] = "isolated-changed-version"
    await discover(hass, payload)
    current = entry.runtime_data
    assert current is not old_runtime and old_runtime._closed
    assert current.owner is None and not current.available
    assert not first.closed and first.connection.subscriptions == {}
    # HA auth identity still exists; only the integration lease was removed.
    assert first.connection.user.id == "synthetic-user"
    error = await heartbeat_error(direct, monkeypatch, client)
    assert error.code == "session_expired"
    assert not error.authentication and not error.configuration
    assert direct.machine.failed(direct._epoch, error.code)
    assert direct.machine.status.state == ConnectionState.RETRY_WAIT
    direct._close_socket()
    assert first.closed
    assert direct.machine.retry(direct._epoch)
    await asyncio.to_thread(direct._connect)
    assert direct.machine.connected(direct._epoch)
    second = boundary.sockets[1]
    assert current.owner is second.connection and current.available
    assert first.sent[0] == second.sent[0] == {"type": "auth", "access_token": boundary.token}
    assert first.sent[1]["session"] == second.sent[1]["session"] == direct.protocol.session
    old_disconnect()
    old_runtime._expired(None)
    assert current.owner is second.connection and 1 in second.connection.subscriptions
    direct._close_socket()
    await hass.async_block_till_done()


async def test_identical_discovery_preserves_live_direct_owner(hass, wire, client):
    entry, payload = await configured(hass)
    boundary = SocketBoundary(hass)
    direct = transport(boundary, client)
    await asyncio.to_thread(direct._connect)
    current = entry.runtime_data
    try:
        await discover(hass, payload)
        assert entry.runtime_data is current
        assert not current._closed and current.owner is boundary.sockets[0].connection
    finally:
        direct._close_socket()
        await hass.async_block_till_done()


async def test_reloaded_lease_heartbeat_reports_expiry_separately_from_authorization(hass, wire, client):
    entry, payload = await configured(hass)
    boundary = SocketBoundary(hass)
    direct = transport(boundary, client)
    await asyncio.to_thread(direct._connect)
    sock = boundary.sockets[0]
    try:
        payload["device"]["sw_version"] = "isolated-changed-version"
        await discover(hass, payload)
        sock.connection.async_handle({"id": 2, "type": "ha_windows_bridge/heartbeat", "device_id": "phase0_pc"})
        response = json.loads(await asyncio.to_thread(sock.recv))
        assert response["error"]["code"] == "session_expired"
        assert entry.runtime_data.owner is None
    finally:
        direct._close_socket()
        await hass.async_block_till_done()
