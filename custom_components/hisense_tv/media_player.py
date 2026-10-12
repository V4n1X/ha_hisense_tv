"""Media player entity for Hisense TVs."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, KEY_COMMANDS, MEDIA_PLAYER_KEYS
from .data import NotConnected
from .entity import HisenseTvEntity, tv_not_connected_error

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .__init__ import HisenseConfigEntry

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HisenseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Hisense TV media player from a config entry."""
    async_add_entities([HisenseTvMediaPlayer(entry)])


class HisenseTvMediaPlayer(HisenseTvEntity, MediaPlayerEntity):
    """Representation of a Hisense TV."""

    _attr_name = None
    _attr_supported_features = SUPPORTED_FEATURES

    _SOURCE_RETRY_SECONDS = 60.0

    def __init__(self, entry: HisenseConfigEntry) -> None:
        """Initialize the media player and its source-retry throttle."""
        super().__init__(entry, "media-player")
        self._source_requested_at: float | None = None

    @property
    def should_poll(self) -> bool:
        """Push-only: coordinator listeners wake the entity."""
        return False

    @property
    def available(self) -> bool:
        """Keep available so WOL can power the TV on while disconnected."""
        return True

    @property
    def state(self) -> MediaPlayerState:
        """Map connection/screen/tv_state onto HA media player states."""
        if not self._client.connected:
            return MediaPlayerState.OFF
        if self._tv_state.screen_on is False:
            return MediaPlayerState.ON
        tv_state = self._tv_state.tv_state or ""
        if tv_state in ("mediadmp", "mediadlna", "livetv"):
            return MediaPlayerState.PLAYING
        if tv_state == "tshift":
            return MediaPlayerState.PAUSED
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        """Volume as 0.0-1.0 (protocol reports 0-100)."""
        if self._tv_state.volume_level is None:
            return None
        return round(self._tv_state.volume_level / 100.0, 2)

    @property
    def is_volume_muted(self) -> bool | None:
        """Whether the TV reports muted audio."""
        return self._tv_state.muted

    @property
    def source(self) -> str | None:
        """Human label of the active source or app."""
        current = self._tv_state.current_source()
        return current.label if current else self._tv_state.source_name

    @property
    def source_list(self) -> list[str]:
        """Selectable labels: inputs plus installed apps."""
        names = [source.label for source in self._tv_state.source_list]
        names.extend(app.name for app in self._tv_state.app_list)
        return names

    async def async_turn_on(self) -> None:
        """Wake via WOL, or the power key for a TV in fake sleep."""
        await self.async_power_on()

    async def async_turn_off(self) -> None:
        """Send the power key to a running TV (a toggle; state feedback confirms)."""
        await self.async_power_off()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set absolute volume and echo it locally (dedupe handled in TvState)."""
        # round(x) without ndigits already returns an int.
        level = round(max(0.0, min(1.0, volume)) * 100)
        try:
            await self._client.set_volume(level)
        except NotConnected as err:
            raise tv_not_connected_error(err) from err
        # Optimistic echo protection handled by state.apply_volume dedupe.
        self._tv_state.volume_level = level
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        """Send the volume-up key."""
        await self._send_key(KEY_COMMANDS["volume_up"])

    async def async_volume_down(self) -> None:
        """Send the volume-down key."""
        await self._send_key(KEY_COMMANDS["volume_down"])

    async def async_mute_volume(self, mute: bool) -> None:
        """Reach the requested mute state with the protocol's toggle key.

        The toggle is skipped when the TV already reports the requested
        state; with an unknown state it is sent once.
        """
        if self._tv_state.muted is not None and self._tv_state.muted == mute:
            return
        await self._send_key(KEY_COMMANDS["mute"])

    async def async_media_play(self) -> None:
        """Send the play key."""
        await self._send_key(MEDIA_PLAYER_KEYS["play"])

    async def async_media_pause(self) -> None:
        """Send the pause key."""
        await self._send_key(MEDIA_PLAYER_KEYS["pause"])

    async def async_media_stop(self) -> None:
        """Send the stop key."""
        await self._send_key(MEDIA_PLAYER_KEYS["stop"])

    async def async_media_next_track(self) -> None:
        """Send the next-track key."""
        await self._send_key(MEDIA_PLAYER_KEYS["next_track"])

    async def async_media_previous_track(self) -> None:
        """Send the previous-track key."""
        await self._send_key(MEDIA_PLAYER_KEYS["previous_track"])

    async def async_select_source(self, source: str) -> None:
        """Switch to a source label or launch an app by name."""
        try:
            for item in self._tv_state.source_list:
                if item.label == source:
                    await self._client.select_source(item.sourceid)
                    return
            for app in self._tv_state.app_list:
                if app.name == source:
                    await self._client.launch_app(
                        app.url, app.name, app.url_type, app.store_type
                    )
                    return
        except NotConnected as err:
            raise tv_not_connected_error(err) from err
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_source",
            translation_placeholders={"source": source},
        )

    async def _async_request_source_list(self) -> None:
        """Background source-list request; the TV may drop off meanwhile."""
        with contextlib.suppress(NotConnected):
            await self._client.request_source_list()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh source list lazily while connected.

        Uses a time-based throttle instead of a one-shot flag: a request can
        silently fail when the TV is still waking up, and the old permanent
        flag meant the source list stayed empty forever after that.
        """
        super()._handle_coordinator_update()
        if not (self._client.connected and not self._tv_state.source_list):
            return
        now = time.monotonic()
        if (
            self._source_requested_at is not None
            and now - self._source_requested_at < self._SOURCE_RETRY_SECONDS
        ):
            return
        self._source_requested_at = now
        self.hass.async_create_task(self._async_request_source_list())
