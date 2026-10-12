"""Diagnostics support for the Hisense TV integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_UUID, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .__init__ import HisenseConfigEntry

REDACT_KEYS = {"client_id", CONF_UUID, "mac_wifi", "mac_ethernet", "udn"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HisenseConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry (credentials redacted)."""
    runtime = getattr(entry, "runtime_data", None)
    state = runtime.state if runtime is not None else None
    client = runtime.client if runtime is not None else None

    capability: dict[str, Any] = {}
    if state is not None and state.capability is not None:
        cap = state.capability
        capability = {
            "brand": cap.brand,
            "device_id": cap.device_id,
            "feature_code": cap.feature_code,
            "chip_platform": cap.chip_platform,
            "fake_sleep": cap.fake_sleep,
            "audio_capture_supported": cap.audio_capture_supported,
            "screen_capture_supported": cap.screen_capture_supported,
        }

    return {
        "entry": {
            "domain": DOMAIN,
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), REDACT_KEYS),
            "options": dict(entry.options),
        },
        "connection": {
            "connected": bool(client and client.connected),
            "tls": bool(client and client.active_tls),
            "host": entry.data.get("host"),
            "port": entry.data.get("port"),
        },
        "state": (
            {
                "volume_level": state.volume_level,
                "muted": state.muted,
                "source_id": state.source_id,
                "source_name": state.source_name,
                "source_list_size": len(state.source_list),
                "tv_state": state.tv_state,
                "screen_on": state.screen_on,
                "app_version": state.app_version,
            }
            if state is not None
            else None
        ),
        "capability": capability,
    }
