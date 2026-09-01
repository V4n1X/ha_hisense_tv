"""Media player entity for Hisense TVs."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import callback

from .const import KEY_COMMANDS, MEDIA_PLAYER_KEYS
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
    hass,
    entry: "HisenseConfigEntry",
    async_add_entities: "AddConfigEntryEntitiesCallback",
) -> None:
    """Set up the Hisense TV media player from a config entry."""
    async_add_entities([HisenseTvMediaPlayer(entry)])


class HisenseTvMediaPlayer(HisenseTvEntity, MediaPlayerEntity):
    """Representation of a Hisense TV."""

    _attr_name = None
    _attr_supported_features = SUPPORTED_FEATURES

    _SOURCE_RETRY_SECONDS = 60.0

    def __init__(self, entry: "HisenseConfigEntry") -> None:
        super().__init__(entry, "media-player")
        self._source_requested_at: float | None = None

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        # Keep media_player available so the user can turn on the TV via Wake-on-LAN
        # when the TV is off/disconnected.
        return True

    @property
    def state(self) -> MediaPlayerState:
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
        if self._tv_state.volume_level is None:
            return None
        return round(self._tv_state.volume_level / 100.0, 2)

    @property
    def is_volume_muted(self) -> bool | None:
        return self._tv_state.muted

    @property
    def source(self) -> str | None:
        current = self._tv_state.current_source()
        return current.label if current else self._tv_state.source_name

    @property
    def source_list(self) -> list[str]:
        names = [source.label for source in self._tv_state.source_list]
        names.extend(app.name for app in self._tv_state.app_list)
        return names

    async def _send(self, key: str) -> None:
        await self._client.send_key(key)

    async def async_turn_on(self) -> None:
        if self._wol_enabled():
            await self.async_wake_tv()
        if self._client.connected:
            await self._send(KEY_COMMANDS["power"])

    async def async_turn_off(self) -> None:
        # KEY_POWER is a toggle; the TV confirms via state feedback.
        try:
            await self._send(KEY_COMMANDS["power"])
        except NotConnected as err:
            raise tv_not_connected_error(err) from err

    async def async_set_volume_level(self, volume: float) -> None:
        level = int(round(max(0.0, min(1.0, volume)) * 100))
        try:
            await self._client.set_volume(level)
        except NotConnected as err:
            raise tv_not_connected_error(err) from err
        # Optimistic echo protection handled by state.apply_volume dedupe.
        self._tv_state.volume_level = level
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        await self._send(KEY_COMMANDS["volume_up"])
        # Optimistic single-step feedback; the TV's volumechange push corrects it.
        if self._tv_state.volume_level is not None:
            self._tv_state.volume_level = min(100, self._tv_state.volume_level + 1)
            self.async_write_ha_state()

    async def async_volume_down(self) -> None:
        await self._send(KEY_COMMANDS["volume_down"])
        if self._tv_state.volume_level is not None:
            self._tv_state.volume_level = max(0, self._tv_state.volume_level - 1)
            self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        await self._send(KEY_COMMANDS["mute"])
        # KEY_MUTE is a toggle; reflect the expected state instantly.
        if self._tv_state.muted is None:
            self._tv_state.muted = True  # first toggle: assume it was unmuted
        else:
            self._tv_state.muted = mute
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        try:
            await self._send(MEDIA_PLAYER_KEYS["play"])
        except NotConnected as err:
            raise tv_not_connected_error(err) from err

    async def async_media_pause(self) -> None:
        try:
            await self._send(MEDIA_PLAYER_KEYS["pause"])
        except NotConnected as err:
            raise tv_not_connected_error(err) from err

    async def async_media_stop(self) -> None:
        try:
            await self._send(MEDIA_PLAYER_KEYS["stop"])
        except NotConnected as err:
            raise tv_not_connected_error(err) from err

    async def async_media_next_track(self) -> None:
        try:
            await self._send(MEDIA_PLAYER_KEYS["next_track"])
        except NotConnected as err:
            raise tv_not_connected_error(err) from err

    async def async_media_previous_track(self) -> None:
        try:
            await self._send(MEDIA_PLAYER_KEYS["previous_track"])
        except NotConnected as err:
            raise tv_not_connected_error(err) from err

    async def async_select_source(self, source: str) -> None:
        for item in self._tv_state.source_list:
            if item.label == source:
                await self._client.select_source(item.sourceid)
                # Instant feedback; the TV's sourceswitch push corrects if needed.
                self._tv_state.source_id = item.sourceid
                self._tv_state.source_name = item.label
                self.async_write_ha_state()
                return
        for app in self._tv_state.app_list:
            if app.name == source:
                await self._client.launch_app(app.url, app.name, app.url_type, app.store_type)
                self._tv_state.source_id = app.url
                self._tv_state.source_name = app.name
                self.async_write_ha_state()
                return
        _LOGGER.warning("Unknown source %s", source)

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
        self.hass.async_create_task(self._client.request_source_list())
