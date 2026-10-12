"""Config flow tests against a real Home Assistant core.

These drive the flows through Home Assistant's own flow manager, so they catch
what the stub-based unit tests cannot: HA rejecting ``async_create_entry`` in
reconfigure/reauth flows, unique-id handling, DHCP routing and flow removal.
Skipped when the real Home Assistant package is not installed.
"""

from __future__ import annotations

import importlib
import sys

import pytest

if getattr(sys.modules.get("homeassistant"), "__hisense_test_stub__", False):
    pytest.skip("real Home Assistant package not installed", allow_module_level=True)

pytestmark = pytest.mark.asyncio

from homeassistant import config_entries  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo  # noqa: E402
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo  # noqa: E402

DOMAIN = "hisense_tv"
HOST = "192.0.2.10"
NEW_HOST = "192.0.2.20"
WIFI_MAC = "AA:BB:CC:DD:EE:FF"
PIN = "1234"

cf = importlib.import_module("custom_components.hisense_tv.config_flow")
data_mod = importlib.import_module("custom_components.hisense_tv.data")
models = importlib.import_module("custom_components.hisense_tv.models")
discovery = importlib.import_module("custom_components.hisense_tv.discovery")
const = importlib.import_module("custom_components.hisense_tv.const")


class FakeTvClient(data_mod.HisenseTvClient):
    """Real client with the network replaced by a scripted TV.

    Inheriting keeps the real event ring and ``wait_for_event`` under test;
    only connecting and publishing are faked.
    """

    instances: list[FakeTvClient] = []
    pairing_required = False
    reachable = True
    noise_before_pin = 0

    def __init__(self, *args, **kwargs) -> None:
        """Record every client the flow creates."""
        super().__init__(*args, **kwargs)
        self.stopped = False
        FakeTvClient.instances.append(self)

    async def start(self, *, allow_offline: bool = False) -> None:
        """Connect instantly, or fail like an unreachable TV."""
        if not FakeTvClient.reachable:
            raise data_mod.CannotConnect(self.host)
        self.connected = True

    async def stop(self) -> None:
        """Remember that the flow cleaned up the probe connection."""
        self.stopped = True
        self.connected = False

    async def get_tv_state(self) -> bool:
        """A TV that does not know us answers with an /authentication push."""
        if FakeTvClient.pairing_required:
            self._emit(const.DISPATCH_PAIRING_REQUIRED, "")
        return True

    async def submit_pairing_code(self, code: str) -> bool:
        """Broadcast noise first (busy TV), then the auth result."""
        for _ in range(FakeTvClient.noise_before_pin):
            self._emit(const.DISPATCH_STATE, models.StateUpdate("sourceswitch"))
        result = models.AuthenResult(result=1 if code == PIN else 0)
        self._emit(const.DISPATCH_AUTH_RESULT, result)
        return True

    async def cancel_pairing(self) -> bool:
        """Closing the PIN dialog always succeeds."""
        return True

    def push(self, name: str, data: object) -> None:
        """Simulate an unsolicited push from the TV."""
        self._emit(name, data)


def _tv(host: str = HOST, mac: str = WIFI_MAC) -> discovery.DiscoveredTV:
    return discovery.DiscoveredTV(
        host=host,
        name="Wohnzimmer TV",
        model_name="65A71FS",
        mac_wifi=mac,
        udn="uuid:tv-1",
    )


@pytest.fixture
def tv_network(monkeypatch, ha_integration):
    """Fake client + SSDP; entry setup is a no-op so reloads stay offline."""
    FakeTvClient.instances = []
    FakeTvClient.pairing_required = False
    FakeTvClient.reachable = True
    FakeTvClient.noise_before_pin = 0
    found: list[discovery.DiscoveredTV] = []

    async def fake_discover(timeout: float = 4.0) -> list[discovery.DiscoveredTV]:
        return list(found)

    async def fake_fetch(location: str, timeout: float = 5.0):
        return found[0] if found else None

    async def setup_ok(hass, entry) -> bool:
        return True

    # Every import of config_flow.py registers its class in HANDLERS. The
    # unit tests import the same file as ``hisense_tv.config_flow``, which
    # would otherwise replace the patched ``custom_components`` handler.
    monkeypatch.setitem(config_entries.HANDLERS, DOMAIN, cf.HisenseTvConfigFlow)
    monkeypatch.setattr(cf, "HisenseTvClient", FakeTvClient)
    monkeypatch.setattr(cf, "async_discover_tvs", fake_discover)
    monkeypatch.setattr(cf, "fetch_description", fake_fetch)
    monkeypatch.setattr(ha_integration, "async_setup_entry", setup_ok)
    monkeypatch.setattr(ha_integration, "async_unload_entry", setup_ok)
    return found


async def _add_entry(hass, data: dict | None = None, unique_id: str | None = None):
    entry = config_entries.ConfigEntry(
        data={
            "host": HOST,
            "port": 36669,
            "name": "Wohnzimmer TV",
            "use_tls": False,
            "uuid": "old-client",
            "client_id": "old-client",
        }
        | (data or {}),
        domain=DOMAIN,
        title="Wohnzimmer TV",
        source="user",
        unique_id=unique_id,
        version=1,
        minor_version=1,
        options={},
        discovery_keys={},
        subentries_data=[],
    )
    await hass.config_entries.async_add(entry)
    return entry


def _entries(hass):
    return hass.config_entries.async_entries(DOMAIN)


async def _start_reconfigure(hass, entry):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )


# ---------------------------------------------------------------------------
# reconfigure
# ---------------------------------------------------------------------------


async def test_reconfigure_updates_the_existing_entry(hass, tv_network):
    """A new address updates the entry in place instead of creating a second one."""
    entry = await _add_entry(hass, {"mac_wifi": WIFI_MAC}, unique_id=WIFI_MAC)

    result = await _start_reconfigure(hass, entry)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": NEW_HOST, "port": 36669}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert len(_entries(hass)) == 1
    assert entry.data["host"] == NEW_HOST
    assert FakeTvClient.instances[-1].stopped


async def test_reconfigure_through_the_pairing_step(hass, tv_network):
    """A TV that asks for a PIN during reconfigure still updates in place."""
    entry = await _add_entry(hass, {"mac_wifi": WIFI_MAC}, unique_id=WIFI_MAC)
    FakeTvClient.pairing_required = True

    result = await _start_reconfigure(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": NEW_HOST, "port": 36669}
    )
    assert result["step_id"] == "pairing"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pin": PIN}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert len(_entries(hass)) == 1
    assert entry.data["host"] == NEW_HOST


# ---------------------------------------------------------------------------
# user flow: unique id, duplicates, pairing
# ---------------------------------------------------------------------------


async def test_manual_setup_sets_unique_id_and_blocks_duplicates(hass, tv_network):
    """A manually added TV gets the MAC as unique id; adding it again aborts."""
    tv_network.append(_tv())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": 36669}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == WIFI_MAC

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": 36669}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(_entries(hass)) == 1


async def test_manual_setup_without_ssdp_blocks_same_host(hass, tv_network):
    """Without SSDP metadata the host still identifies an existing entry."""
    await _add_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": 36669}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(_entries(hass)) == 1


async def test_pairing_succeeds_after_a_burst_of_broadcasts(hass, tv_network):
    """More than 64 pushes before the auth result must not hide it."""
    FakeTvClient.pairing_required = True

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": 36669}
    )
    assert result["step_id"] == "pairing"

    # Fill the event ring to its limit while the user reads the PIN.
    probe = FakeTvClient.instances[-1]
    for _ in range(80):
        probe.push(const.DISPATCH_STATE, models.StateUpdate("sourceswitch"))
    FakeTvClient.noise_before_pin = 10

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pin": PIN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_abandoned_pairing_closes_the_probe_connection(hass, tv_network):
    """Closing the PIN dialog must not leave an MQTT connection running."""
    FakeTvClient.pairing_required = True

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": 36669}
    )
    assert result["step_id"] == "pairing"

    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()

    assert FakeTvClient.instances[-1].stopped


# ---------------------------------------------------------------------------
# DHCP (registered_devices) and SSDP
# ---------------------------------------------------------------------------


async def test_dhcp_updates_the_host_of_a_known_tv(hass, tv_network):
    """A registered TV on a new IP updates the entry and offers no new setup."""
    entry = await _add_entry(hass, {"mac_wifi": WIFI_MAC}, unique_id=WIFI_MAC)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(ip=NEW_HOST, hostname="tv", macaddress="aabbccddeeff"),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == NEW_HOST
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_dhcp_for_a_known_tv_on_the_same_ip(hass, tv_network):
    """A lease renewal on the same IP is silently ignored."""
    entry = await _add_entry(hass, {"mac_wifi": WIFI_MAC}, unique_id=WIFI_MAC)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_DHCP},
        data=DhcpServiceInfo(ip=HOST, hostname="tv", macaddress="aabbccddeeff"),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == HOST


async def test_ssdp_ignores_a_manually_added_tv(hass, tv_network):
    """SSDP must not offer a TV that was added by IP (entry without unique id)."""
    await _add_entry(hass)
    tv_network.append(_tv())

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_SSDP},
        data=SsdpServiceInfo(
            ssdp_usn="uuid:tv-1",
            ssdp_st="upnp:rootdevice",
            upnp={},
            ssdp_location=f"http://{HOST}:38400/MediaServer/rendererdevicedesc.xml",
        ),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# reauth
# ---------------------------------------------------------------------------


async def test_reauth_repairs_the_entry_in_place(hass, tv_network):
    """Re-pairing stores a fresh client id on the same entry."""
    entry = await _add_entry(hass, {"mac_wifi": WIFI_MAC}, unique_id=WIFI_MAC)
    FakeTvClient.pairing_required = True

    entry.async_start_reauth(hass)
    entry.async_start_reauth(hass)  # duplicate requests collapse into one flow
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1

    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {})
    assert result["step_id"] == "pairing"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"pin": PIN}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert len(_entries(hass)) == 1
    assert entry.data["client_id"] != "old-client"
    assert entry.data["client_id"] == entry.data["uuid"]
