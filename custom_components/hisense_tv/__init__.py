"""The Hisense TV integration.

Controls Hisense Vidaa TVs through the MQTT broker built into the TV,
replicating the protocol of the official RemoteNOW app.
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import monotonic as time_monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_CHIP_PLATFORM,
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

if TYPE_CHECKING:
    from .discovery import DiscoveredTV

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.SENSOR,
    Platform.BUTTON,
]

type HisenseConfigEntry = ConfigEntry[RuntimeData]


def bundled_client_cert() -> Path | None:
    """Bundled RemoteNOW client certificate (mutual TLS on newer models)."""
    return default_client_cert_path()


def _register_device(hass: HomeAssistant, entry: HisenseConfigEntry) -> None:
    """Create/update the registry device immediately at setup time."""
    registry = dr.async_get(hass)
    identifier = (DOMAIN, entry_unique_id(entry))
    # The identity is derived (MAC > UDN > uuid > host), so it changes when a
    # manually added TV later reveals its MAC. Move the entry's device to the
    # new identifier instead of letting get_or_create add a second device.
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    if len(devices) == 1 and identifier not in devices[0].identifiers:
        registry.async_update_device(devices[0].id, new_identifiers={identifier})
    data = entry.data
    kwargs: dict = {
        "config_entry_id": entry.entry_id,
        "identifiers": {identifier},
        "connections": device_connections(entry),
        "manufacturer": MANUFACTURER,
        "model": str(data.get(CONF_MODEL_NAME) or "").strip() or DEFAULT_NAME,
        "name": entry.title or DEFAULT_NAME,
    }
    if data.get(CONF_TV_VERSION):
        kwargs["sw_version"] = str(data[CONF_TV_VERSION])
    if data.get(CONF_PLATFORM_VERSION):
        kwargs["hw_version"] = f"platform {data[CONF_PLATFORM_VERSION]}"
    if data.get(CONF_CHIP_PLATFORM):
        kwargs["hw_version"] = f"chip {data[CONF_CHIP_PLATFORM]}"
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

    def _on_event(name: str, payload: Any) -> None:
        """Apply push feedback to the shared TvState and refresh listeners."""
        nonlocal _last_reauth_request, _last_metadata_request
        runtime: RuntimeData | None = getattr(entry, "runtime_data", None)
        if runtime is None:
            return
        changed = False

        if name == DISPATCH_STATE and isinstance(payload, StateUpdate):
            changed = runtime.state.apply_state(payload)
            _LOGGER.debug(
                "%s: state update applied=%s (%s)",
                entry.title,
                changed,
                payload.statetype,
            )
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
            _LOGGER.debug(
                "%s: source list updated (%d entries)", entry.title, len(payload)
            )
        elif name == DISPATCH_APPS and isinstance(payload, list):
            changed = runtime.state.apply_apps(payload)
            _LOGGER.debug(
                "%s: app list updated (%d entries)", entry.title, len(payload)
            )
        elif name == DISPATCH_CONNECTION:
            runtime.state.connected = bool(payload)
            # Availability and the OFF state follow the connection; without
            # this the entities would lag until the next poll.
            changed = True
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
            # Persist the chip platform so hw_version survives HA restarts
            # (and fresh registry devices) even when the TV is off.
            if (
                payload.chip_platform
                and entry.data.get(CONF_CHIP_PLATFORM) != payload.chip_platform
            ):
                hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_CHIP_PLATFORM: payload.chip_platform},
                )
            _refresh_device_metadata(hass, entry)
        elif name == DISPATCH_APP_VERSION and payload:
            runtime.state.app_version = str(payload)
            changed = True
            _refresh_device_metadata(hass, entry)
        elif name == DISPATCH_PAIRING_REQUIRED:
            # The TV no longer knows us (reset/firmware update): start the
            # reauth flow so the user can re-pair with a fresh PIN. Home
            # Assistant raises its own repair issue for it and ignores the
            # request while a reauth flow is already open; the throttle only
            # keeps a pushing TV from re-opening a flow the user dismissed.
            now = time_monotonic()
            if now - _last_reauth_request > 60:
                _last_reauth_request = now
                _LOGGER.info(
                    "%s: TV requests pairing - starting reauth flow", entry.title
                )
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
        entry.async_create_background_task(
            hass,
            _async_background_metadata_enrichment(hass, entry),
            "hisense_tv_metadata_enrichment",
        )

    return True


def _fill_missing(new_data: dict, discovered: DiscoveredTV, key: str) -> None:
    """Copy discovered.<key> into new_data[key] when new_data has no value."""
    value = getattr(discovered, key, None)
    if value and not new_data.get(key):
        new_data[key] = value


async def _async_background_metadata_enrichment(
    hass: HomeAssistant,
    entry: HisenseConfigEntry,
) -> None:
    """Enrich entry data via SSDP (MACs, model, versions) once, in the background.

    Runs only when the entry has no MAC (usually added via manual IP). Best
    effort: any failure is logged at debug level and otherwise ignored.
    """
    from .discovery import async_discover_tvs  # noqa: PLC0415

    try:
        discovered = await async_discover_tvs(timeout=6.0)
        host = entry.data.get("host")
        tv = next((item for item in discovered if item.host == host), None)
        if tv is None:
            return
        new_data = dict(entry.data)
        _fill_missing(new_data, tv, CONF_MAC_WIFI)
        _fill_missing(new_data, tv, CONF_MAC_ETHERNET)
        _fill_missing(new_data, tv, CONF_MODEL_NAME)
        _fill_missing(new_data, tv, CONF_TV_VERSION)
        _fill_missing(new_data, tv, CONF_TRANSPORT_PROTOCOL)
        platform = (tv.extras or {}).get("platform")
        if platform and not new_data.get(CONF_PLATFORM_VERSION):
            new_data[CONF_PLATFORM_VERSION] = str(platform)
        if new_data != entry.data:
            hass.config_entries.async_update_entry(entry, data=new_data)
            _register_device(hass, entry)
            _refresh_device_metadata(hass, entry)
    except Exception as ex:  # noqa: BLE001
        _LOGGER.debug("%s: background metadata enrichment: %s", entry.title, ex)


def _refresh_device_metadata(hass: HomeAssistant, entry: HisenseConfigEntry) -> None:
    """Patch sw/hw version in the registry once capability feedback arrives."""
    runtime: RuntimeData | None = getattr(entry, "runtime_data", None)
    if runtime is None:
        return
    registry = dr.async_get(hass)
    # Scoped-by-entry lookup: identifiers are only unique per config entry
    # since the 2026.9 device registry rework (async_get_device is deprecated
    # and will be removed in 2027.8).
    device = registry.async_get_device_by_identifier(
        (DOMAIN, entry_unique_id(entry)), entry.entry_id
    )
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
    if not unload_ok:
        # Platforms are still loaded and use the client - keep it running.
        return False
    runtime: RuntimeData | None = getattr(entry, "runtime_data", None)
    if runtime is not None:
        await runtime.client.stop()
        entry.runtime_data = None
    return True
