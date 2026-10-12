"""Tests for the MQTT feedback dispatcher (no broker required)."""

from hisense_tv.data import HisenseTvClient
from hisense_tv.models import AuthenResult, StateUpdate, VolumeUpdate

CID = "ha-hisense-test1234"


def make_client() -> tuple[HisenseTvClient, list]:
    """Build a client whose events are collected into a list."""
    events: list[tuple[str, object]] = []
    client = HisenseTvClient("127.0.0.1", 36669, CID)
    client.on_event = lambda name, data: events.append((name, data))
    return client, events


def test_state_dispatch_from_broadcast():
    """ui_service/state broadcasts dispatch a parsed StateUpdate."""
    client, events = make_client()
    client._handle_message(
        "/remoteapp/mobile/broadcast/ui_service/state",
        b'{"statetype":"sourceswitch","sourceid":"4","sourcename":"HDMI 2"}',
    )
    assert len(events) == 1
    name, data = events[0]
    assert name == "state"
    assert isinstance(data, StateUpdate)
    assert data.statetype == "sourceswitch"


def test_volume_alias_dispatch_for_own_client():
    """Both firmware spellings (volume/volumechange) dispatch volume updates."""
    # Firmware variants use either /volume or /volumechange.
    client, events = make_client()
    client._handle_message(
        f"/remoteapp/mobile/{CID}/platform_service/volume",
        b'{"volume_type":0,"volume_value":25}',
    )
    client._handle_message(
        "/remoteapp/mobile/broadcast/ui_service/volumechange",
        b'{"volume_type":2,"volume_value":1}',
    )
    kinds = [name for name, _ in events]
    assert kinds == ["volume", "volume"]
    assert isinstance(events[0][1], VolumeUpdate) and events[0][1].level == 25
    assert isinstance(events[1][1], VolumeUpdate) and events[1][1].muted is True


def test_pairing_and_auth_result_flow():
    """/authentication requests pairing, /authenticationcode carries the result."""
    client, events = make_client()
    client._handle_message(
        "/remoteapp/mobile/broadcast/ui_service/authentication", b"{}"
    )
    client._handle_message(
        f"/remoteapp/mobile/{CID}/ui_service/authenticationcode",
        b'{"result":1,"info":"ok"}',
    )
    names = [name for name, _ in events]
    assert names == ["pairing_required", "authentication_result"]
    assert isinstance(events[1][1], AuthenResult) and events[1][1].ok


def test_auth_toast_is_not_a_success_signal():
    """The toast means the remote slot is busy ("device busy"), never success.

    Verified against live firmware: the TV pushes /authenticationcodetoast
    while showing "connected device is busy" - pairing is still pending.
    """
    client, events = make_client()
    client._handle_message(
        f"/remoteapp/mobile/{CID}/ui_service/authenticationcodetoast",
        b"",
    )
    assert len(events) == 1
    name, payload = events[0]
    assert name == "authentication_toast"
    assert not isinstance(payload, AuthenResult)


def test_foreign_client_ids_are_ignored():
    """Messages addressed to other clients produce no events."""
    client, events = make_client()
    client._handle_message(
        "/remoteapp/mobile/someoneelse/ui_service/state",
        b'{"statetype":"app"}',
    )
    assert events == []


def test_irrelevant_topics_are_ignored():
    """Non-feedback topics and garbage produce no events."""
    client, events = make_client()
    client._handle_message(
        "/remoteapp/tv/remote_service/x/actions/sendkey", b"KEY_POWER"
    )
    client._handle_message("garbage", b"x")
    assert events == []


def test_pop_event_returns_newest_match():
    """pop_event honours the after_index marker when polling."""
    client, _events = make_client()
    client._handle_message(
        "/remoteapp/mobile/broadcast/ui_service/state", b'{"statetype":"app"}'
    )
    found = client.pop_event("state")
    assert found is not None
    data, index = found
    assert data.statetype == "app"

    marker = index
    client._handle_message(
        "/remoteapp/mobile/broadcast/ui_service/state", b'{"statetype":"livetv"}'
    )
    newer = client.pop_event("state", after_index=marker + 1)
    assert newer is not None
    assert newer[0].statetype == "livetv"
    # Nothing new after the latest marker:
    assert client.pop_event("state", after_index=len(client.recent_events())) is None


def test_config_flow_wait_event_names_match_dispatcher():
    """Regression: the config flow must wait on the dispatcher's event names.

    The pairing step once waited on the raw topic segment
    ("authenticationcode") instead of the dispatch name
    ("authentication_result"), so even a correct PIN timed out.
    """
    from hisense_tv.const import (
        AUTH_WAIT_EVENTS,
        DISPATCH_AUTH_RESULT,
        DISPATCH_PAIRING_REQUIRED,
        PROBE_WAIT_EVENTS,
    )

    assert frozenset({DISPATCH_PAIRING_REQUIRED}) == PROBE_WAIT_EVENTS
    assert frozenset({DISPATCH_AUTH_RESULT}) == AUTH_WAIT_EVENTS
    assert DISPATCH_AUTH_RESULT != "authenticationcode"


def test_auth_toast_uses_dedicated_dispatch_name():
    """The busy toast must never surface as an AuthenResult success."""
    client, events = make_client()
    client._handle_message(
        f"/remoteapp/mobile/{CID}/ui_service/authenticationcodetoast",
        b"",
    )
    names = [name for name, _ in events]
    assert "authentication_result" not in names
    assert names == ["authentication_toast"]
