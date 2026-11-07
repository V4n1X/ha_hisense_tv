"""Data update coordinator for the Hisense TV integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_POLL_INTERVAL
from .data import NotConnected
from .dlna import RENDERING_CONTROL, RenderingControl

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .data import HisenseTvClient
    from .models import TvState

_LOGGER = logging.getLogger(__name__)

MEDIA_RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"
# The TV applies a mute key well within a second (measured live).
MUTE_CONFIRM_DELAY = 1.0


@dataclass(slots=True)
class RuntimeData:
    """Everything the entity platforms need, stored on entry.runtime_data."""

    client: HisenseTvClient
    coordinator: HisenseTvCoordinator
    state: TvState


class HisenseTvCoordinator(DataUpdateCoordinator["TvState"]):
    """Poll fallback for values that are otherwise pushed by the TV.

    The protocol is push-first: volume/source/state feedback arrives
    asynchronously on /remoteapp/mobile/... The poll cycle only requests fresh
    values so a lost push heals within one interval. The mute state is the
    exception: MQTT never carries it, so each poll reads it from the TV's DLNA
    renderer.

    Connection loss is deliberately *not* raised as UpdateFailed: the TV's MQTT
    broker disappears while the set is powered off, which is exactly the OFF
    condition -- entities expose ``client.connected`` via ``available`` so they
    become unavailable instead of reporting stale values.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HisenseTvClient,
        state: TvState,
    ) -> None:
        """Configure the poll interval from the entry options."""
        self.client = client
        self.state = state
        try:
            poll = int(entry.options.get("poll_interval", DEFAULT_POLL_INTERVAL))
        except (TypeError, ValueError):
            poll = DEFAULT_POLL_INTERVAL
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{entry.title} ({entry.data.get('host')})",
            update_interval=timedelta(seconds=max(5, poll)),
        )
        self._rendering_control: RenderingControl | None = None

    @property
    def rendering_control(self) -> RenderingControl:
        """DLNA mute reader, created on first use with Home Assistant's session."""
        if self._rendering_control is None:
            self._rendering_control = RenderingControl(
                async_get_clientsession(self.hass),
                self.client.host,
                self._announced_description,
            )
        return self._rendering_control

    async def _announced_description(self) -> str | None:
        """Renderer description URL from Home Assistant's SSDP cache, if any."""
        try:
            from homeassistant.components import ssdp  # noqa: PLC0415

            for search_target in (RENDERING_CONTROL, MEDIA_RENDERER):
                for info in await ssdp.async_get_discovery_info_by_st(
                    self.hass, search_target
                ):
                    location = info.ssdp_location or ""
                    if urlparse(location).hostname == self.client.host:
                        return location
        except Exception as err:  # noqa: BLE001 - SSDP is optional here
            _LOGGER.debug("%s: no SSDP renderer location: %s", self.name, err)
        return None

    async def async_refresh_mute(self) -> None:
        """Read the mute state from the DLNA renderer and publish a change."""
        if not self.client.connected:
            return
        muted = await self.rendering_control.async_get_mute()
        if muted is not None and muted != self.state.muted:
            self.state.muted = muted
            self.async_update_listeners()

    async def _async_confirm_mute(self) -> None:
        await asyncio.sleep(MUTE_CONFIRM_DELAY)
        await self.async_refresh_mute()

    @callback
    def async_schedule_mute_check(self) -> None:
        """Replace the optimistic mute state with the TV's own shortly."""
        assert self.config_entry is not None
        self.config_entry.async_create_background_task(
            self.hass, self._async_confirm_mute(), "hisense_tv_mute_check"
        )

    async def _async_update_data(self) -> TvState:
        if not self.client.connected:
            _LOGGER.debug("%s: TV offline - keeping last snapshot", self.name)
            return self.state
        try:
            await self.client.get_volume()
            await self.client.get_tv_state()
        except NotConnected:
            _LOGGER.debug("%s: poll lost connection - waiting for reconnect", self.name)
            return self.state
        await self.async_refresh_mute()
        # Push-first protocol: the poll only triggers fresh values; the TV's
        # push feedback updates the shared state and wakes listeners via the
        # event callback, so no settle sleep is needed here.
        _LOGGER.debug(
            "%s: poll requested (tv_state=%s volume=%s muted=%s sources=%d)",
            self.name,
            self.state.tv_state,
            self.state.volume_level,
            self.state.muted,
            len(self.state.source_list),
        )
        return self.state
