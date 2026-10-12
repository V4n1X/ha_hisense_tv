"""Entity behaviour tests (media player, remote, buttons) against real HA classes.

The entity platforms import Home Assistant's media_player/remote/button
components, which the stub mode does not provide, so these run only with the
real package installed.
"""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

if getattr(sys.modules.get("homeassistant"), "__hisense_test_stub__", False):
    pytest.skip("real Home Assistant package not installed", allow_module_level=True)

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

pytestmark = pytest.mark.asyncio

data_mod = importlib.import_module("custom_components.hisense_tv.data")
discovery = importlib.import_module("custom_components.hisense_tv.discovery")
models = importlib.import_module("custom_components.hisense_tv.models")
media_player = importlib.import_module("custom_components.hisense_tv.media_player")
remote = importlib.import_module("custom_components.hisense_tv.remote")
button = importlib.import_module("custom_components.hisense_tv.button")

WIFI_MAC = "AA:BB:CC:DD:EE:FF"


class RecordingClient(data_mod.HisenseTvClient):
    """Real client whose publishes and WOL packets are recorded, not sent."""

    def __init__(self) -> None:
        """Start disconnected with empty recordings."""
        super().__init__("192.0.2.10", 36669, "test-client")
        self.sent: list[tuple[str, str]] = []
        self.woken: list[str] = []

    async def _publish(self, service: str, action: str, payload: str = "") -> bool:
        if not self.connected:
            raise data_mod.NotConnected(self.host)
        self.sent.append((action, payload))
        return True

    async def wake_on_lan(self, mac: str) -> None:
        """Validate like the real packet builder, then record."""
        discovery.build_magic_packet(mac)
        self.woken.append(mac)

    @property
    def keys(self) -> list[str]:
        """Remote keys sent so far."""
        return [payload for action, payload in self.sent if action == "sendkey"]


def _entry(*, data: dict | None = None, options: dict | None = None):
    client = RecordingClient()
    state = models.TvState()
    runtime = SimpleNamespace(
        client=client,
        state=state,
        coordinator=SimpleNamespace(async_add_listener=lambda *_a, **_k: None),
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Wohnzimmer TV",
        data={"host": "192.0.2.10", "port": 36669, "mac_wifi": WIFI_MAC} | (data or {}),
        options={"command_delay": 0} | (options or {}),
        runtime_data=runtime,
    )
    return entry, client, state


def _player(**kwargs):
    entry, client, state = _entry(**kwargs)
    entity = media_player.HisenseTvMediaPlayer(entry)
    entity.async_write_ha_state = lambda: None
    return entity, client, state


def _remote(**kwargs):
    entry, client, state = _entry(**kwargs)
    return remote.HisenseTvRemote(entry), client, state


# ---------------------------------------------------------------------------
# power: KEY_POWER is a toggle, so it must only be sent when it changes state
# ---------------------------------------------------------------------------


async def test_turn_on_does_not_toggle_a_running_tv():
    """turn_on on a TV that is already on must not switch it off."""
    player, client, state = _player()
    client.connected = True
    state.screen_on = True

    await player.async_turn_on()

    assert client.keys == []


async def test_turn_on_wakes_a_fake_sleeping_tv_with_the_power_key():
    """A connected TV in fake sleep is switched on with KEY_POWER."""
    player, client, state = _player()
    client.connected = True
    state.screen_on = False

    await player.async_turn_on()

    assert client.keys == ["KEY_POWER"]


async def test_turn_on_uses_wake_on_lan_while_disconnected():
    """An unreachable TV is woken via WOL; no key can be sent."""
    player, client, _state = _player()

    await player.async_turn_on()

    assert client.woken == [WIFI_MAC]
    assert client.keys == []


async def test_wake_on_lan_skips_an_invalid_mac():
    """A malformed stored MAC must not prevent waking via the other one."""
    player, client, _state = _player(
        data={"mac_wifi": "not-a-mac", "mac_ethernet": "00:11:22:33:44:55"}
    )

    await player.async_turn_on()

    assert client.woken == ["00:11:22:33:44:55"]


async def test_turn_off_an_offline_tv_is_a_noop():
    """Turning off a TV that is already off must not raise."""
    player, client, _state = _player()

    await player.async_turn_off()

    assert client.keys == []


async def test_turn_off_sends_the_power_key():
    """A running TV is switched off with KEY_POWER."""
    player, client, state = _player()
    client.connected = True
    state.screen_on = True

    await player.async_turn_off()

    assert client.keys == ["KEY_POWER"]


# ---------------------------------------------------------------------------
# mute: the protocol only knows a toggle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("muted", "request_mute", "expected"),
    [
        pytest.param(True, True, [], id="already-muted"),
        pytest.param(False, False, [], id="already-unmuted"),
        pytest.param(False, True, ["KEY_MUTE"], id="mute"),
        pytest.param(True, False, ["KEY_MUTE"], id="unmute"),
        pytest.param(None, True, ["KEY_MUTE"], id="unknown-state"),
    ],
)
async def test_mute_only_toggles_when_needed(muted, request_mute, expected):
    """mute(true) on a muted TV must not unmute it."""
    player, client, state = _player()
    client.connected = True
    state.muted = muted

    await player.async_mute_volume(request_mute)

    assert client.keys == expected


# ---------------------------------------------------------------------------
# errors surface as translated Home Assistant errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda p: p.async_volume_up(), id="volume_up"),
        pytest.param(lambda p: p.async_volume_down(), id="volume_down"),
        pytest.param(lambda p: p.async_mute_volume(True), id="mute"),
        pytest.param(lambda p: p.async_media_play(), id="play"),
        pytest.param(lambda p: p.async_set_volume_level(0.5), id="set_volume"),
    ],
)
async def test_commands_on_an_offline_tv_raise_a_translated_error(call):
    """No raw NotConnected may leak out of a service call."""
    player, _client, _state = _player()

    with pytest.raises(HomeAssistantError) as err:
        await call(player)

    assert err.value.translation_key == "tv_not_connected"


async def test_select_source_on_an_offline_tv_raises_a_translated_error():
    """Switching inputs while offline gives the translated error."""
    player, _client, state = _player()
    state.source_list = [models.SourceInfo(sourceid="4", sourcename="HDMI 2")]

    with pytest.raises(HomeAssistantError) as err:
        await player.async_select_source("HDMI 2")

    assert err.value.translation_key == "tv_not_connected"


async def test_select_unknown_source_is_a_validation_error():
    """An unknown source name is a user error, not a silent log line."""
    player, client, _state = _player()
    client.connected = True

    with pytest.raises(ServiceValidationError) as err:
        await player.async_select_source("HDMI 9")

    assert err.value.translation_key == "unknown_source"


async def test_button_press_on_an_offline_tv_raises_a_translated_error():
    """Buttons report the translated error instead of NotConnected."""
    entry, _client, _state = _entry()
    entity = button.HisenseTvButton(entry, button.BUTTON_DESCRIPTIONS[0])

    with pytest.raises(HomeAssistantError) as err:
        await entity.async_press()

    assert err.value.translation_key == "tv_not_connected"


async def test_source_list_refresh_tolerates_a_lost_connection():
    """The background source-list request must swallow a NotConnected."""
    player, _client, _state = _player()

    await player._async_request_source_list()  # noqa: SLF001


# ---------------------------------------------------------------------------
# remote
# ---------------------------------------------------------------------------


async def test_remote_send_command_honours_num_repeats():
    """remote.send_command repeats the whole sequence num_repeats times."""
    entity, client, _state = _remote()
    client.connected = True

    await entity.async_send_command(["volume_up", "ok"], num_repeats=3, delay_secs=0)

    assert client.keys == ["KEY_VOLUMEUP", "KEY_OK"] * 3


async def test_remote_turn_off_sends_the_power_key():
    """remote.turn_off is implemented (ToggleEntity default raises)."""
    entity, client, state = _remote()
    client.connected = True
    state.screen_on = True

    await entity.async_turn_off()

    assert client.keys == ["KEY_POWER"]


async def test_remote_turn_on_does_not_toggle_a_running_tv():
    """remote.turn_on on a running TV must not switch it off."""
    entity, client, state = _remote()
    client.connected = True
    state.screen_on = True

    await entity.async_turn_on()

    assert client.keys == []
