"""Tests for the device-metadata helpers in the integration's ``__init__``.

Covers the background SSDP enrichment of a manually added entry and the
registry refresh that patches sw/hw versions once the TV reports them. The
device registry and config entries are replaced by small recording fakes, so
the tests run with and without the real Home Assistant package.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

import hisense_tv
from hisense_tv import (
    _async_background_metadata_enrichment,
    _fill_missing,
    _refresh_device_metadata,
)
from hisense_tv.const import (
    CONF_MAC_ETHERNET,
    CONF_MAC_WIFI,
    CONF_MODEL_NAME,
    CONF_PLATFORM_VERSION,
    CONF_TRANSPORT_PROTOCOL,
    CONF_TV_VERSION,
    DOMAIN,
)
from hisense_tv.discovery import DiscoveredTV
from hisense_tv.models import CapabilityInfo, TvState

HOST = "192.0.2.10"
WIFI_MAC = "AA:BB:CC:DD:EE:FF"
ETHERNET_MAC = "00:11:22:33:44:55"
TV_VERSION = "V0000.01.00N.P0226"


class FakeDeviceRegistry:
    """Device registry stand-in that records every call."""

    def __init__(self, device: object | None) -> None:
        """Start with the device a lookup should return (None = unknown)."""
        self.device = device
        self.created: list[dict] = []
        self.lookups: list[tuple[object, str]] = []
        self.updates: list[tuple[str, dict]] = []

    def async_get_or_create(self, **kwargs: object) -> object | None:
        """Record a device creation request."""
        self.created.append(kwargs)
        return self.device

    def async_get_device_by_identifier(
        self, identifier: object, entry_id: str
    ) -> object | None:
        """Record the entry-scoped lookup and return the preset device."""
        self.lookups.append((identifier, entry_id))
        return self.device

    def async_update_device(self, device_id: str, **updates: object) -> None:
        """Record a device update."""
        self.updates.append((device_id, updates))


class FakeConfigEntries:
    """Config entry manager that applies updates like the real one."""

    def __init__(self) -> None:
        """Start without recorded updates."""
        self.updates: list[dict] = []

    def async_update_entry(self, entry: FakeEntry, *, data: dict) -> None:
        """Replace the entry data and remember the call."""
        entry.data = data
        self.updates.append(data)


class FakeHass:
    """Minimal hass exposing only the config entry manager."""

    def __init__(self) -> None:
        """Wire the config entry manager."""
        self.config_entries = FakeConfigEntries()


class FakeEntry:
    """Config entry stand-in with the attributes the helpers touch."""

    def __init__(
        self, data: dict | None = None, runtime_data: object | None = None
    ) -> None:
        """Create an entry for HOST, optionally with extra data/runtime data."""
        self.entry_id = "entry-1"
        self.title = "Wohnzimmer TV"
        self.data = {"host": HOST, "port": 36669, "client_id": "cid"} | (data or {})
        self.runtime_data = runtime_data


@pytest.fixture
def registry(monkeypatch) -> FakeDeviceRegistry:
    """Route the integration's device registry access to a recording fake."""
    fake = FakeDeviceRegistry(device=SimpleNamespace(id="device-1"))
    monkeypatch.setattr(hisense_tv, "dr", SimpleNamespace(async_get=lambda _hass: fake))
    return fake


def _runtime(
    app_version: str | None = None, chip_platform: str | None = None
) -> SimpleNamespace:
    """Runtime data with a TvState; chip_platform=None means no capability yet."""
    state = TvState()
    state.app_version = app_version
    if chip_platform is not None:
        state.capability = CapabilityInfo()
        state.capability.chip_platform = chip_platform
    return SimpleNamespace(state=state)


def _discovery_returns(monkeypatch, result: list[DiscoveredTV] | Exception) -> None:
    """Replace the SSDP discovery with a canned result (or failure)."""

    async def fake_discover(timeout: float = 4.0) -> list[DiscoveredTV]:
        """Return the canned TVs or raise the canned exception."""
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("hisense_tv.discovery.async_discover_tvs", fake_discover)


def _full_tv() -> DiscoveredTV:
    """A discovered TV at HOST carrying all the metadata the enrichment copies."""
    return DiscoveredTV(
        host=HOST,
        mac_wifi=WIFI_MAC,
        mac_ethernet=ETHERNET_MAC,
        model_name="HE88L5V",
        tv_version=TV_VERSION,
        transport_protocol=2100,
        extras={"platform": "1"},
    )


# ---------------------------------------------------------------------------
# _fill_missing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        CONF_MAC_WIFI,
        CONF_MAC_ETHERNET,
        CONF_MODEL_NAME,
        CONF_TV_VERSION,
        CONF_TRANSPORT_PROTOCOL,
    ],
)
def test_fill_missing_keys_are_discovered_tv_attributes(key):
    """The enrichment looks values up by entry key, so the names must line up."""
    assert key in {field.name for field in dataclasses.fields(DiscoveredTV)}


def test_fill_missing_copies_into_empty_slot():
    """An absent or empty entry value is filled from the discovered TV."""
    tv = DiscoveredTV(host=HOST, mac_wifi=WIFI_MAC, model_name="HE88L5V")
    data = {CONF_MAC_WIFI: ""}

    _fill_missing(data, tv, CONF_MAC_WIFI)
    _fill_missing(data, tv, CONF_MODEL_NAME)

    assert data == {CONF_MAC_WIFI: WIFI_MAC, CONF_MODEL_NAME: "HE88L5V"}


def test_fill_missing_never_overwrites_or_stores_blanks():
    """Existing values win, and an empty discovered value adds nothing."""
    tv = DiscoveredTV(host=HOST, mac_wifi=WIFI_MAC, mac_ethernet="")
    data = {CONF_MAC_WIFI: "11:22:33:44:55:66"}

    _fill_missing(data, tv, CONF_MAC_WIFI)
    _fill_missing(data, tv, CONF_MAC_ETHERNET)

    assert data == {CONF_MAC_WIFI: "11:22:33:44:55:66"}


# ---------------------------------------------------------------------------
# _refresh_device_metadata
# ---------------------------------------------------------------------------


def test_refresh_without_runtime_data_does_not_touch_the_registry(registry):
    """An entry that is not set up (or already unloaded) is left alone."""
    _refresh_device_metadata(FakeHass(), FakeEntry(runtime_data=None))

    assert registry.lookups == []
    assert registry.updates == []


def test_refresh_looks_up_the_device_scoped_to_the_entry(registry):
    """Identifiers are unique per config entry only, so the entry id is passed."""
    entry = FakeEntry({CONF_MAC_WIFI: WIFI_MAC}, runtime_data=_runtime())

    _refresh_device_metadata(FakeHass(), entry)

    assert registry.lookups == [((DOMAIN, WIFI_MAC), "entry-1")]


def test_refresh_unknown_device_is_a_noop(registry):
    """No registry device yet means nothing to patch."""
    registry.device = None
    entry = FakeEntry(runtime_data=_runtime(app_version="V1", chip_platform="mtk"))

    _refresh_device_metadata(FakeHass(), entry)

    assert registry.updates == []


@pytest.mark.parametrize(
    ("entry_data", "runtime", "expected"),
    [
        pytest.param(
            {},
            _runtime(app_version="V1", chip_platform="mtk"),
            {"sw_version": "V1", "hw_version": "chip mtk"},
            id="push-feedback-wins",
        ),
        pytest.param(
            {CONF_TV_VERSION: TV_VERSION},
            _runtime(),
            {"sw_version": TV_VERSION},
            id="sw-version-falls-back-to-entry",
        ),
        pytest.param(
            {CONF_PLATFORM_VERSION: "1"},
            _runtime(chip_platform=""),
            {"hw_version": "platform 1"},
            id="hw-version-falls-back-to-platform",
        ),
        pytest.param(
            {CONF_PLATFORM_VERSION: "1"},
            _runtime(),
            {},
            id="no-capability-no-hw-version",
        ),
    ],
)
def test_refresh_patches_versions(registry, entry_data, runtime, expected):
    """sw/hw versions follow the TV's push feedback, then the stored entry data."""
    entry = FakeEntry(entry_data, runtime_data=runtime)

    _refresh_device_metadata(FakeHass(), entry)

    assert registry.updates == ([("device-1", expected)] if expected else [])


# ---------------------------------------------------------------------------
# _async_background_metadata_enrichment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrichment_stores_metadata_and_refreshes_the_device(
    registry, monkeypatch
):
    """The TV at the entry's host fills every gap, then the device is refreshed."""
    other = DiscoveredTV(host="192.0.2.99", mac_wifi="FF:FF:FF:FF:FF:FF")
    _discovery_returns(monkeypatch, [other, _full_tv()])
    hass = FakeHass()
    entry = FakeEntry(runtime_data=_runtime(chip_platform="mtk"))

    await _async_background_metadata_enrichment(hass, entry)

    assert len(hass.config_entries.updates) == 1
    assert entry.data[CONF_MAC_WIFI] == WIFI_MAC
    assert entry.data[CONF_MAC_ETHERNET] == ETHERNET_MAC
    assert entry.data[CONF_MODEL_NAME] == "HE88L5V"
    assert entry.data[CONF_TV_VERSION] == TV_VERSION
    assert entry.data[CONF_TRANSPORT_PROTOCOL] == 2100
    assert entry.data[CONF_PLATFORM_VERSION] == "1"
    # Registered under the freshly learned MAC, then patched via the scoped lookup.
    assert registry.created[0]["identifiers"] == {(DOMAIN, WIFI_MAC)}
    assert registry.lookups == [((DOMAIN, WIFI_MAC), "entry-1")]
    assert registry.updates == [
        ("device-1", {"sw_version": TV_VERSION, "hw_version": "chip mtk"})
    ]


@pytest.mark.asyncio
async def test_enrichment_keeps_values_the_entry_already_has(registry, monkeypatch):
    """Discovery only fills gaps; user-visible values are never overwritten."""
    _discovery_returns(monkeypatch, [_full_tv()])
    hass = FakeHass()
    entry = FakeEntry({CONF_MODEL_NAME: "My TV"}, runtime_data=_runtime())

    await _async_background_metadata_enrichment(hass, entry)

    assert entry.data[CONF_MODEL_NAME] == "My TV"
    assert entry.data[CONF_MAC_WIFI] == WIFI_MAC


@pytest.mark.asyncio
async def test_enrichment_ignores_other_hosts(registry, monkeypatch):
    """A scan that only finds other TVs changes nothing."""
    _discovery_returns(monkeypatch, [DiscoveredTV(host="192.0.2.99", mac_wifi="X")])
    hass = FakeHass()

    await _async_background_metadata_enrichment(
        hass, FakeEntry(runtime_data=_runtime())
    )

    assert hass.config_entries.updates == []
    assert registry.created == []


@pytest.mark.asyncio
async def test_enrichment_without_new_information_skips_the_update(
    registry, monkeypatch
):
    """An entry that already has everything is not rewritten."""
    _discovery_returns(monkeypatch, [_full_tv()])
    complete = {
        CONF_MAC_WIFI: WIFI_MAC,
        CONF_MAC_ETHERNET: ETHERNET_MAC,
        CONF_MODEL_NAME: "HE88L5V",
        CONF_TV_VERSION: TV_VERSION,
        CONF_TRANSPORT_PROTOCOL: 2100,
        CONF_PLATFORM_VERSION: "1",
    }
    hass = FakeHass()

    await _async_background_metadata_enrichment(
        hass, FakeEntry(complete, runtime_data=_runtime())
    )

    assert hass.config_entries.updates == []
    assert registry.created == []


@pytest.mark.asyncio
async def test_enrichment_swallows_discovery_failures(registry, monkeypatch):
    """Best effort: an unreachable network must never break setup."""
    _discovery_returns(monkeypatch, OSError("network unreachable"))
    hass = FakeHass()

    await _async_background_metadata_enrichment(
        hass, FakeEntry(runtime_data=_runtime())
    )

    assert hass.config_entries.updates == []
