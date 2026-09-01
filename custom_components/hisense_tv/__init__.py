"""The Hisense TV integration.

Controls Hisense Vidaa TVs through the MQTT broker built into the TV,
replicating the protocol of the official RemoteNOW app.
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import monotonic as time_monotonic

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_MAC_ETHERNET,
    CONF_MAC_WIFI,
    CONF_MODEL_NAME,
    CONF_PLATFORM_VERSION,
    CONF_TRANSPORT_PROTOCOL,
    CONF_TV_VERSION,
    DEFAULT_NAME,
    DISPATCH_APP_VERSION,
    DISPATCH_APPS,
    DISPATCH_CAPABILITY,
    DISPATCH_CONNECTION,
    DISPATCH_PAIRING_REQUIRED,
    DISPATCH_SOURCES,
    DISPATCH_STATE,
    DISPATCH_VOLUME,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import HisenseTvCoordinator, RuntimeData
from .data import HisenseTvClient, default_client_cert_path
from .entity import device_connections, entry_unique_id
from .models import CapabilityInfo, StateUpdate, TvState

_LOGGER = logging.getLogger(__name__)

# Note: repairs is NOT an entity platform. HA calls the module-level
# async_create_fix_flow() in repairs.py directly; no forwarding needed.
PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.SENSOR,
    Platform.BUTTON,
]

if TYPE_CHECKING:
    from typing import TypeAlias

    HisenseConfigEntry: TypeAlias = ConfigEntry[RuntimeData]
else:
    HisenseConfigEntry = ConfigEntry


def bundled_client_cert() -> Path | None:
    """Bundled RemoteNOW client certificate (mutual TLS on newer models)."""
    return default_client_cert_path()


def _register_device(hass: HomeAssistant, entry: HisenseConfigEntry) -> None:
    """Create/update the registry device immediately at setup time."""
    registry = dr.async_get(hass)
    data = entry.data
    kwargs: dict = {
        "config_entry_id": entry.entry_id,
        "identifiers": {(DOMAIN, entry_unique_id(entry))},
        "connections": device_connections(entry),
        "manufacturer": MANUFACTURER,
        "model": str(data.get(CONF_MODEL_NAME) or "").strip() or DEFAULT_NAME,
        "name": entry.title or DEFAULT_NAME,
    }
    if data.get(CONF_TV_VERSION):
        kwargs["sw_version"] = str(data[CONF_TV_VERSION])
    if data.get(CONF_PLATFORM_VERSION):
        kwargs["hw_version"] = f"platform {data[CONF_PLATFORM_VERSION]}"
    registry.async_get_or_create(**kwargs)


async def async_setup_entry(hass: HomeAssistant, entry: HisenseConfigEntry) -> bool:
    """Set up a Hisense TV from a config entry."""
    cert_path = bundled_client_cert() or default_client_cert_path()
    _last_reauth_request = 0.0
    _last_metadata_request = 0.0
    coordinator: HisenseTvCoordinator | None = None

    async def _request_tv_metadata() -> None:
        """Ask the TV for capability/appversion; answers patch sw/hw version."""
        try:
            await client.request_capability()
            await client.request_app_version()
            await client.request_source_list()
            await client.request_app_list()
        except Exception as ex:  # noqa: BLE001 - must never break the connection loop
            _LOGGER.debug("%s: metadata request failed: %s", entry.title, ex)

    def _on_event(name: str, payload) -> None:  # noqa: ANN001 - Any payload
        """Apply push feedback to the shared TvState and refresh listeners."""
        nonlocal _last_reauth_request, _last_metadata_request
        runtime: RuntimeData | None = getattr(entry, "runtime_data", None)
        if runtime is None:
            return
        changed = False

        if name == DISPATCH_STATE and isinstance(payload, StateUpdate):
            changed = runtime.state.apply_state(payload)
            _LOGGER.debug("%s: state update applied=%s (%s)", entry.title, changed, payload.statetype)
        elif name == DISPATCH_VOLUME:
            changed = runtime.state.apply_volume(payload)
            _LOGGER.debug(
                "%s: volume update applied=%s (level=%s muted=%s)",
                entry.title,
                changed,
                getattr(payload, "level", None),
                getattr(payload, "muted", None),
            )
        elif name == DISPATCH_SOURCES:
            runtime.state.apply_sources(payload)
            changed = True
            _LOGGER.debug("%s: source list updated (%d entries)", entry.title, len(payload))
        elif name == DISPATCH_APPS and isinstance(payload, list):
            changed = runtime.state.apply_apps(payload)
            _LOGGER.debug("%s: app list updated (%d entries)", entry.title, len(payload))
        elif name == DISPATCH_CONNECTION:
            runtime.state.connected = bool(payload)
            if payload:
                # On every (re)connect ask for capability/appversion. This used
                # to run once during setup - but since setup now completes
                # offline when the TV is powered off, the request would never
                # happen and hw_version (chip platform) stayed empty.
                now = time_monotonic()
                if now - _last_metadata_request > 60:
                    _last_metadata_request = now
                    entry.async_create_background_task(
                        hass,
                        _request_tv_metadata(),
                        "hisense_tv_metadata_request",
                    )
        elif name == DISPATCH_CAPABILITY and isinstance(payload, CapabilityInfo):
            runtime.state.capability = payload
            changed = True
            _refresh_device_metadata(hass, entry)
        elif name == DISPATCH_APP_VERSION and payload:
            runtime.state.app_version = str(payload)
            changed = True
        elif name == DISPATCH_PAIRING_REQUIRED:
            # The TV no longer knows us (reset/firmware update): start the
            # reauth flow so the user can re-pair with a fresh PIN.
            now = time_monotonic()
            if now - _last_reauth_request > 60:
                _last_reauth_request = now
                _LOGGER.info("%s: TV requests pairing - starting reauth flow", entry.title)
                from .repairs import async_create_pairing_lost_issue  # noqa: PLC0415

                async_create_pairing_lost_issue(hass, entry)
                entry.async_start_reauth(hass)
            return

        if changed and coordinator is not None:
            coordinator.async_update_listeners()

    client = HisenseTvClient(
        host=str(entry.data["host"]),
        port=int(entry.data.get("port") or 36669),
        client_id=str(entry.data["client_id"]),
        use_tls=entry.data.get("use_tls"),
        client_cert_path=cert_path,
        event_callback=_on_event,
    )
    state = TvState()
    coordinator = HisenseTvCoordinator(hass, entry, client, state)
    runtime = RuntimeData(client=client, coordinator=coordinator, state=state)
    entry.runtime_data = runtime  # before start(): early events need runtime

    # A TV that is powered off is *not* a setup error: its MQTT broker is
    # simply gone. Complete setup anyway so Wake-on-LAN can turn the TV on;
    # the reconnect loop retries in the background and entities report
    # unavailable via client.connected until the TV answers again.
    await client.start(allow_offline=True)
    if not client.connected:
        _LOGGER.warning(
            "%s: TV unreachable at %s:%s - setup continues offline, "
            "entities stay unavailable until the TV reconnects",
            entry.title,
            entry.data.get("host"),
            entry.data.get("port", 36669),
        )

    _register_device(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # If network/hardware metadata is missing (e.g. added via manual IP),
    # query SSDP in the background to discover MAC addresses and model info.
    if not entry.data.get(CONF_MAC_WIFI) and not entry.data.get(CONF_MAC_ETHERNET):
        async def _async_background_metadata_enrichment() -> None:
            from .discovery import async_discover_tvs  # noqa: PLC0415
            try:
                discovered = await async_discover_tvs(timeout=6.0)
                host = entry.data.get("host")
                tv = next((item for item in discovered if item.host == host), None)
                if tv:
                    new_data = dict(entry.data)
                    if tv.mac_wifi and not new_data.get(CONF_MAC_WIFI):
                        new_data[CONF_MAC_WIFI] = tv.mac_wifi
                    if tv.mac_ethernet and not new_data.get(CONF_MAC_ETHERNET):
                        new_data[CONF_MAC_ETHERNET] = tv.mac_ethernet
                    if tv.model_name and not new_data.get(CONF_MODEL_NAME):
                        new_data[CONF_MODEL_NAME] = tv.model_name
                    if tv.tv_version and not new_data.get(CONF_TV_VERSION):
                        new_data[CONF_TV_VERSION] = tv.tv_version
                    if tv.transport_protocol and not new_data.get(CONF_TRANSPORT_PROTOCOL):
                        new_data[CONF_TRANSPORT_PROTOCOL] = tv.transport_protocol
                    platform = (tv.extras or {}).get("platform")
                    if platform and not new_data.get(CONF_PLATFORM_VERSION):
                        new_data[CONF_PLATFORM_VERSION] = str(platform)
                    if new_data != entry.data:
                        hass.config_entries.async_update_entry(entry, data=new_data)
                        _register_device(hass, entry)
                        _refresh_device_metadata(hass, entry)
            except Exception as ex:  # noqa: BLE001
                _LOGGER.debug("%s: background metadata enrichment: %s", entry.title, ex)

        # async_create_background_task keeps the task reference on the entry
        # (HA >= 2024.3) so it cannot be garbage-collected mid-flight.
        entry.async_create_background_task(
            hass,
            _async_background_metadata_enrichment(),
            "hisense_tv_metadata_enrichment",
        )

    return True


def _refresh_device_metadata(hass: HomeAssistant, entry: HisenseConfigEntry) -> None:
    """Patch sw/hw version in the registry once capability feedback arrives."""
    runtime: RuntimeData | None = getattr(entry, "runtime_data", None)
    if runtime is None:
        return
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, entry_unique_id(entry))})
    if device is None:
        return
    updates: dict[str, str] = {}
    if runtime.state.app_version:
        updates["sw_version"] = str(runtime.state.app_version)
    elif entry.data.get(CONF_TV_VERSION):
        updates["sw_version"] = str(entry.data[CONF_TV_VERSION])

    cap = runtime.state.capability
    if cap is not None:
        if cap.chip_platform:
            updates["hw_version"] = f"chip {cap.chip_platform}"
        elif entry.data.get(CONF_PLATFORM_VERSION):
            updates["hw_version"] = f"platform {entry.data[CONF_PLATFORM_VERSION]}"
    if updates:
        registry.async_update_device(device.id, **updates)


async def async_unload_entry(hass: HomeAssistant, entry: HisenseConfigEntry) -> bool:
    """Unload platforms and close the MQTT connection cleanly."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    runtime: RuntimeData | None = getattr(entry, "runtime_data", None)
    if runtime is not None:
        await runtime.client.stop()
        entry.runtime_data = None
    return unload_ok
