"""Button platform for Hisense TV remote key shortcuts.

The default set is intentionally small (``DEFAULT_BUTTONS``); the full list
below can be selected per TV in the integration options. Power and
Wake-on-LAN are not buttons: they duplicate ``media_player.turn_on`` /
``media_player.turn_off``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .const import CONF_BUTTONS, DEFAULT_BUTTONS
from .entity import HisenseTvEntity

if TYPE_CHECKING:
    from .__init__ import HisenseConfigEntry


@dataclass(frozen=True, kw_only=True)
class HisenseButtonEntityDescription(ButtonEntityDescription):
    """Describes Hisense TV button entity."""

    key_command: str
    # Human label used by the options-flow multi-select.
    label: str


BUTTON_DESCRIPTIONS: tuple[HisenseButtonEntityDescription, ...] = (
    # Navigation
    HisenseButtonEntityDescription(
        key="home", translation_key="button_home", icon="mdi:home",
        key_command="KEY_HOME", label="Home",
    ),
    HisenseButtonEntityDescription(
        key="back", translation_key="button_back", icon="mdi:keyboard-backspace",
        key_command="KEY_RETURNS", label="Back",
    ),
    HisenseButtonEntityDescription(
        key="ok", translation_key="button_ok", icon="mdi:checkbox-blank-circle-outline",
        key_command="KEY_OK", label="OK",
    ),
    HisenseButtonEntityDescription(
        key="up", translation_key="button_up", icon="mdi:arrow-up",
        key_command="KEY_UP", label="Up",
    ),
    HisenseButtonEntityDescription(
        key="down", translation_key="button_down", icon="mdi:arrow-down",
        key_command="KEY_DOWN", label="Down",
    ),
    HisenseButtonEntityDescription(
        key="left", translation_key="button_left", icon="mdi:arrow-left",
        key_command="KEY_LEFT", label="Left",
    ),
    HisenseButtonEntityDescription(
        key="right", translation_key="button_right", icon="mdi:arrow-right",
        key_command="KEY_RIGHT", label="Right",
    ),
    HisenseButtonEntityDescription(
        key="menu", translation_key="button_menu", icon="mdi:menu",
        key_command="KEY_MENU", label="Menu",
    ),
    HisenseButtonEntityDescription(
        key="info", translation_key="button_info", icon="mdi:information-outline",
        key_command="KEY_INFO", label="Info",
    ),
    HisenseButtonEntityDescription(
        key="guide", translation_key="button_guide", icon="mdi:television-guide",
        key_command="KEY_EPG", label="Guide (EPG)",
    ),
    HisenseButtonEntityDescription(
        key="source", translation_key="button_source", icon="mdi:video-input-hdmi",
        key_command="KEY_SOURCES", label="Source",
    ),
    HisenseButtonEntityDescription(
        key="settings", translation_key="button_settings", icon="mdi:cog",
        key_command="KEY_SETTINGS", label="Settings",
    ),
    # Volume & channels
    HisenseButtonEntityDescription(
        key="volume_up", translation_key="button_volume_up", icon="mdi:volume-high",
        key_command="KEY_VOLUMEUP", label="Volume up",
    ),
    HisenseButtonEntityDescription(
        key="volume_down", translation_key="button_volume_down", icon="mdi:volume-low",
        key_command="KEY_VOLUMEDOWN", label="Volume down",
    ),
    HisenseButtonEntityDescription(
        key="mute", translation_key="button_mute", icon="mdi:volume-mute",
        key_command="KEY_MUTE", label="Mute",
    ),
    HisenseButtonEntityDescription(
        key="channel_up", translation_key="button_channel_up", icon="mdi:arrow-up-bold-box-outline",
        key_command="KEY_CHANNELUP", label="Channel up",
    ),
    HisenseButtonEntityDescription(
        key="channel_down", translation_key="button_channel_down", icon="mdi:arrow-down-bold-box-outline",
        key_command="KEY_CHANNELDOWN", label="Channel down",
    ),
    # App shortcuts
    HisenseButtonEntityDescription(
        key="netflix", translation_key="button_netflix", icon="mdi:netflix",
        key_command="KEY_NETFLIX", label="Netflix",
    ),
    HisenseButtonEntityDescription(
        key="youtube", translation_key="button_youtube", icon="mdi:youtube",
        key_command="KEY_YOUTUBE", label="YouTube",
    ),
    HisenseButtonEntityDescription(
        key="prime_video", translation_key="button_prime_video", icon="mdi:amazon",
        key_command="KEY_PRIME", label="Prime Video",
    ),
    HisenseButtonEntityDescription(
        key="disney", translation_key="button_disney", icon="mdi:castle",
        key_command="KEY_DISNEY", label="Disney+",
    ),
    HisenseButtonEntityDescription(
        key="plex", translation_key="button_plex", icon="mdi:plex",
        key_command="KEY_PLEX", label="Plex",
    ),
)

BUTTON_KEYS: frozenset[str] = frozenset(d.key for d in BUTTON_DESCRIPTIONS)


def selected_button_descriptions(options: Mapping) -> list[HisenseButtonEntityDescription]:
    """Return the descriptions for the keys chosen in the entry options."""
    chosen = options.get(CONF_BUTTONS, DEFAULT_BUTTONS)
    selected = {str(key) for key in chosen} & BUTTON_KEYS
    return [d for d in BUTTON_DESCRIPTIONS if d.key in selected]


async def async_setup_entry(hass, entry: "HisenseConfigEntry", async_add_entities) -> None:  # noqa: ANN001
    """Set up the Hisense TV button entities selected in the options."""
    async_add_entities(
        [HisenseTvButton(entry, description) for description in selected_button_descriptions(entry.options)]
    )


class HisenseTvButton(HisenseTvEntity, ButtonEntity):
    """Representation of a Hisense TV remote key button."""

    entity_description: HisenseButtonEntityDescription

    def __init__(
        self,
        entry: "HisenseConfigEntry",
        description: HisenseButtonEntityDescription,
    ) -> None:
        super().__init__(entry, f"btn-{description.key}")
        self.entity_description = description

    @property
    def available(self) -> bool:
        return self._client.connected

    async def async_press(self) -> None:
        """Handle the button press by sending the remote key."""
        await self._client.send_key(self.entity_description.key_command)
