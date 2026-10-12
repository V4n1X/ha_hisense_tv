"""Entry setup and push-feedback handling against a real Home Assistant core.

The MQTT client is replaced by a recording fake and the entity platforms are
not forwarded, so the tests exercise ``async_setup_entry``'s event handling,
the device registry and the reauth plumbing without a TV.
"""

from __future__ import annotations

import importlib
import sys

import pytest

if getattr(sys.modules.get("homeassistant"), "__hisense_test_stub__", False):
    pytest.skip("real Home Assistant package not installed", allow_module_level=True)

from homeassistant import config_entries
from homeassistant.helpers import device_registry as dr, issue_registry as ir

pytestmark = pytest.mark.asyncio

DOMAIN = "hisense_tv"
HOST = "192.0.2.10"
WIFI_MAC = "AA:BB:CC:DD:EE:FF"

data_mod = importlib.import_module("custom_components.hisense_tv.data")
discovery = importlib.import_module("custom_components.hisense_tv.discovery")
const = importlib.import_module("custom_components.hisense_tv.const")


class FakeClient(data_mod.HisenseTvClient):
    """Client that connects instantly and records publishes."""

    instances: list[FakeClient] = []

    def __init__(self, *args, **kwargs) -> None:
        """Record the instance for the test to drive."""
        super().__init__(*args, **kwargs)
        self.stopped = False
        self.sent: list[str] = []
        FakeClient.instances.append(self)

    async def start(self, *, allow_offline: bool = False) -> None:
        """Pretend the TV answered."""
        self.connected = True
        self._emit(const.DISPATCH_CONNECTION, True)

    async def stop(self) -> None:
        """Remember the shutdown."""
        self.stopped = True
        self.connected = False

    async def _publish(self, service: str, action: str, payload: str = "") -> bool:
        self.sent.append(action)
        return True


@pytest.fixture
def setup_env(hass, monkeypatch, ha_integration):
    """Fake client/SSDP and no platform forwarding."""
    FakeClient.instances = []
    found: list[discovery.DiscoveredTV] = []

    async def fake_discover(timeout: float = 4.0):
        return list(found)

    async def forward(entry, platforms) -> None:
        return None

    async def unload(entry, platforms) -> bool:
        return True

    monkeypatch.setattr(ha_integration, "HisenseTvClient", FakeClient)
    monkeypatch.setattr(discovery, "async_discover_tvs", fake_discover)
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", forward)
    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", unload)
    return found


async def _setup(hass, data: dict | None = None):
    entry = config_entries.ConfigEntry(
        data={
            "host": HOST,
            "port": 36669,
            "name": "Wohnzimmer TV",
            "use_tls": False,
            "uuid": "client-1",
            "client_id": "client-1",
        }
        | (data or {}),
        domain=DOMAIN,
        title="Wohnzimmer TV",
        source="user",
        unique_id=None,
        version=1,
        minor_version=1,
        options={},
        discovery_keys={},
        subentries_data=[],
    )
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    return entry, FakeClient.instances[-1]


def _devices(hass, entry):
    return dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)


async def test_connection_loss_updates_entities_immediately(hass, setup_env):
    """Entities must not wait for the next poll to show the TV as off."""
    entry, client = await _setup(hass, {"mac_wifi": WIFI_MAC})
    calls: list[None] = []
    entry.runtime_data.coordinator.async_add_listener(lambda: calls.append(None))

    client.on_event(const.DISPATCH_CONNECTION, False)

    assert calls == [None]
    assert entry.runtime_data.state.connected is False


async def test_pairing_lost_starts_a_single_reauth_flow(hass, setup_env):
    """The TV forgetting us starts one reauth flow with HA's own repair issue."""
    entry, client = await _setup(hass, {"mac_wifi": WIFI_MAC})

    client.on_event(const.DISPATCH_PAIRING_REQUIRED, "")
    client.on_event(const.DISPATCH_PAIRING_REQUIRED, "")
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    issues = ir.async_get(hass).issues
    assert ("homeassistant", f"config_entry_reauth_{DOMAIN}_{entry.entry_id}") in issues
    assert not [key for key in issues if key[0] == DOMAIN]


async def test_app_version_feedback_patches_the_device(hass, setup_env):
    """The TV's firmware version lands in the device registry when it arrives."""
    entry, client = await _setup(hass, {"mac_wifi": WIFI_MAC})

    client.on_event(const.DISPATCH_APP_VERSION, "V0000.01.00N.Q0115")

    (device,) = _devices(hass, entry)
    assert device.sw_version == "V0000.01.00N.Q0115"


async def test_learning_the_mac_keeps_a_single_device(hass, setup_env):
    """SSDP enrichment of a manual entry must not create a second device."""
    setup_env.append(discovery.DiscoveredTV(host=HOST, mac_wifi=WIFI_MAC))

    entry, _client = await _setup(hass)
    await hass.async_block_till_done()

    assert entry.data["mac_wifi"] == WIFI_MAC
    (device,) = _devices(hass, entry)
    assert (DOMAIN, WIFI_MAC) in device.identifiers
    assert (dr.CONNECTION_NETWORK_MAC, WIFI_MAC.lower()) in device.connections


async def test_failed_unload_keeps_the_connection(
    hass, setup_env, ha_integration, monkeypatch
):
    """When the platforms refuse to unload, the entry keeps working."""
    entry, client = await _setup(hass, {"mac_wifi": WIFI_MAC})

    async def refuse(entry, platforms) -> bool:
        return False

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", refuse)

    assert await ha_integration.async_unload_entry(hass, entry) is False
    assert client.stopped is False
    assert entry.runtime_data is not None
