"""Remote entity: exposes all RemoteNOW keys via remote.send_command."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.remote import RemoteEntity
from homeassistant.core import callback

from .const import CONF_COMMAND_DELAY, DEFAULT_COMMAND_DELAY, resolve_key
from .data import NotConnected
from .entity import HisenseTvEntity, tv_not_connected_error

if TYPE_CHECKING:
    from .__init__ import HisenseConfigEntry

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry: "HisenseConfigEntry", async_add_entities) -> None:  # noqa: ANN001
    """Set up the Hisense TV remote from a config entry."""
    async_add_entities([HisenseTvRemote(entry)])


class HisenseTvRemote(HisenseTvEntity, RemoteEntity):
    """Full key remote for a Hisense TV."""

    _attr_translation_key = "remote"

    def __init__(self, entry: "HisenseConfigEntry") -> None:
        super().__init__(entry, "remote")

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool | None:
        return self._client.connected

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._wol_enabled():
            await self.async_wake_tv()
        if self._client.connected:
            await self.async_send_command(["power"])

    async def async_send_command(self, commands: list[str], **kwargs: Any) -> None:
        """Send one or more keys.

        Accepts friendly names ("power"), aliases ("back") and raw wire keys
        ("KEY_POWER"). Multiple commands may be comma separated inside a
        single string; ``delay_secs`` paces them like the APK's command queue.
        """
        delay = float(kwargs.get("delay_secs", 0))
        if delay <= 0:
            delay = int(
                self._entry.options.get(CONF_COMMAND_DELAY, DEFAULT_COMMAND_DELAY)
            ) / 1000.0

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

        for index, key in enumerate(expanded):
            try:
                await self._client.send_key(key)
            except NotConnected as err:
                raise tv_not_connected_error(err) from err
            if index < len(expanded) - 1 and delay > 0:
                await asyncio.sleep(delay)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
