"""Sensor platform for the Hisense TV integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import EntityCategory

from .entity import HisenseTvEntity

if TYPE_CHECKING:
    from .__init__ import HisenseConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry: "HisenseConfigEntry", async_add_entities) -> None:  # noqa: ANN001
    """Set up Hisense TV sensors from a config entry."""
    async_add_entities(
        [
            HisenseVolumeSensor(entry),
            HisenseSourceSensor(entry),
            HisenseStateSensor(entry),
        ]
    )


class _HisenseSensorBase(HisenseTvEntity, SensorEntity):
    """Common plumbing: shared device + availability tied to the connection."""

    def __init__(self, entry: "HisenseConfigEntry", suffix: str) -> None:
        super().__init__(entry, suffix)
        self._state_obj = entry.runtime_data.state

    @property
    def available(self) -> bool:
        return self._client.connected


class HisenseVolumeSensor(_HisenseSensorBase):
    """Current volume level as reported by the TV (0-100 %)."""

    _attr_translation_key = "volume"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: "HisenseConfigEntry") -> None:
        super().__init__(entry, "volume")

    @property
    def native_value(self) -> int | None:
        return self._state_obj.volume_level


class HisenseSourceSensor(_HisenseSensorBase):
    """Currently selected source/input."""

    _attr_translation_key = "source"

    def __init__(self, entry: "HisenseConfigEntry") -> None:
        super().__init__(entry, "source")

    @property
    def native_value(self) -> str | None:
        current = self._state_obj.current_source()
        if current is not None:
            return current.label
        return self._state_obj.source_name


class HisenseStateSensor(_HisenseSensorBase):
    """Raw statetype pushed by the TV (sourceswitch, app, livetv, ...)."""

    _attr_translation_key = "tv_state"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: "HisenseConfigEntry") -> None:
        super().__init__(entry, "tv-state")

    @property
    def native_value(self) -> str | None:
        return self._state_obj.tv_state

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        cap = self._state_obj.capability
        attrs: dict[str, object] = {
            "app_version": self._state_obj.app_version,
            "screen_on": self._state_obj.screen_on,
        }
        if cap is not None:
            attrs.update(
                {
                    "brand": cap.brand,
                    "device_id": cap.device_id,
                    "feature_code": cap.feature_code,
                    "chip_platform": cap.chip_platform,
                    "audio_capture_supported": cap.audio_capture_supported,
                    "screen_capture_supported": cap.screen_capture_supported,
                }
            )
        return attrs
