"""Remote entity: exposes all RemoteNOW keys via remote.send_command."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.remote import (
    ATTR_DELAY_SECS,
    ATTR_NUM_REPEATS,
    RemoteEntity,
)
from homeassistant.core import HomeAssistant, callback

from .const import CONF_COMMAND_DELAY, DEFAULT_COMMAND_DELAY, resolve_key
from .entity import HisenseTvEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .__init__ import HisenseConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HisenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Hisense TV remote from a config entry."""
    async_add_entities([HisenseTvRemote(entry)])


class HisenseTvRemote(HisenseTvEntity, RemoteEntity):
    """Full key remote for a Hisense TV."""

    _attr_translation_key = "remote"

    def __init__(self, entry: HisenseConfigEntry) -> None:
        """Create the remote entity for one TV entry."""
        super().__init__(entry, "remote")

    @property
    def should_poll(self) -> bool:
        """Push-only: coordinator listeners wake the entity."""
        return False

    @property
    def available(self) -> bool:
        """Keep available so WOL can power the TV on while disconnected."""
        return True

    @property
    def is_on(self) -> bool | None:
        """The remote is "on" when the MQTT connection is up."""
        return self._client.connected

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Wake via WOL, or the power key for a TV in fake sleep."""
        await self.async_power_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send the power key to a running TV."""
        await self.async_power_off()

    async def async_send_command(self, commands: list[str], **kwargs: Any) -> None:
        """Send one or more keys.

        Accepts friendly names ("power"), aliases ("back") and raw wire keys
        ("KEY_POWER"). Multiple commands may be comma separated inside a
        single string; ``delay_secs`` paces them like the APK's command queue
        and ``num_repeats`` sends the whole sequence that many times.
        """
        delay = float(kwargs.get(ATTR_DELAY_SECS, 0))
        repeats = max(1, int(kwargs.get(ATTR_NUM_REPEATS, 1)))
        if delay <= 0:
            delay = (
                int(self._entry.options.get(CONF_COMMAND_DELAY, DEFAULT_COMMAND_DELAY))
                / 1000.0
            )

        expanded: list[str] = []
        for command in commands:
            for token in str(command).split(","):
                token = token.strip()
                if not token:
                    continue
                key = resolve_key(token)
                if key is None:
                    _LOGGER.warning("Unknown Hisense TV key: %s", token)
                    continue
                expanded.append(key)

        sequence = expanded * repeats
        for index, key in enumerate(sequence):
            await self._send_key(key)
            if index < len(sequence) - 1 and delay > 0:
                await asyncio.sleep(delay)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
