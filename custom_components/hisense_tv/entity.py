"""Shared entity plumbing for the Hisense TV integration.

Single home for the device-registry helpers and the common entity base so
the platform modules do not duplicate device_info / Wake-on-LAN handling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENABLE_WOL,
    CONF_MAC_ETHERNET,
    CONF_MAC_WIFI,
    CONF_MODEL_NAME,
    CONF_PLATFORM_VERSION,
    CONF_TV_VERSION,
    CONF_UDN,
    CONF_UUID,
    DEFAULT_ENABLE_WOL,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
)
from .discovery import format_mac

if TYPE_CHECKING:
    from .__init__ import HisenseConfigEntry


def entry_unique_id(entry: "HisenseConfigEntry") -> str:
    """Stable unique id: MAC first (device identity), else UDN, else uuid, else host.

    The client UUID is an MQTT handle, not a device identity: re-pairing (reauth)
    generates a fresh one, so keying the registry on it would duplicate the
    device. MAC/UDN survive re-pairing, so they come first.
    """
    return str(
        entry.data.get(CONF_MAC_WIFI)
        or entry.data.get(CONF_MAC_ETHERNET)
        or entry.data.get(CONF_UDN)
        or entry.data.get(CONF_UUID)
        or f"{entry.data.get('host')}:{entry.data.get('port', 36669)}"
    )


def device_connections(entry: "HisenseConfigEntry") -> set[tuple[str, str]]:
    """MAC connections for the device registry."""
    connections: set[tuple[str, str]] = set()
    for key in (CONF_MAC_WIFI, CONF_MAC_ETHERNET):
        mac = entry.data.get(key)
        if mac:
            connections.add((dr.CONNECTION_NETWORK_MAC, format_mac(str(mac))))
    return connections


def build_device_info(entry: "HisenseConfigEntry") -> dr.DeviceInfo:
    """Shared DeviceInfo so every entity lands on one registry device."""
    data = entry.data
    model = str(data.get(CONF_MODEL_NAME) or "").strip() or DEFAULT_NAME
    sw_version = str(data[CONF_TV_VERSION]) if data.get(CONF_TV_VERSION) else None
    hw_version = f"platform {data[CONF_PLATFORM_VERSION]}" if data.get(CONF_PLATFORM_VERSION) else None
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None and runtime.state.capability:
        cap = runtime.state.capability
        if not hw_version and cap.chip_platform:
            hw_version = f"chip {cap.chip_platform}"

    return dr.DeviceInfo(
        identifiers={(DOMAIN, entry_unique_id(entry))},
        manufacturer=MANUFACTURER,
        model=model,
        name=entry.title or DEFAULT_NAME,
        connections=device_connections(entry),
        sw_version=sw_version,
        hw_version=hw_version,
    )


def tv_not_connected_error(err: Exception) -> HomeAssistantError:
    """Translated 'TV not connected' error for the frontend."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="tv_not_connected",
        translation_placeholders={"error": str(err)},
    )


class HisenseTvEntity(CoordinatorEntity):
    """Common base: shared device info, client access and WOL helpers."""

    _attr_has_entity_name = True

    def __init__(self, entry: "HisenseConfigEntry", unique_suffix: str) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinator)
        self._entry = entry
        self._client = runtime.client
        self._tv_state = runtime.state
        self._attr_unique_id = f"{entry.entry_id}-{unique_suffix}"

    @property
    def device_info(self) -> dr.DeviceInfo:
        """One shared registry device for every entity of the entry."""
        return build_device_info(self._entry)

    def _wake_mac(self) -> str | None:
        """First configured MAC (WiFi preferred, then Ethernet)."""
        for key in (CONF_MAC_WIFI, CONF_MAC_ETHERNET):
            mac = self._entry.data.get(key)
            if mac:
                return str(mac)
        return None

    def _wol_enabled(self) -> bool:
        """Whether Wake-on-LAN power-on is enabled in the options."""
        return bool(self._entry.options.get(CONF_ENABLE_WOL, DEFAULT_ENABLE_WOL))

    async def async_wake_tv(self) -> None:
        """Send WOL packets to every configured MAC (works while the TV is off)."""
        for key in (CONF_MAC_WIFI, CONF_MAC_ETHERNET):
            mac = self._entry.data.get(key)
            if mac:
                await self._client.wake_on_lan(str(mac))
