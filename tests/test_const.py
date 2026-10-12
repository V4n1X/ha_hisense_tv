"""Tests for key resolution and topic builders."""

from hisense_tv.const import (
    KEY_COMMANDS,
    SUBSCRIBE_BROADCAST,
    resolve_key,
    subscribe_own,
    tv_action,
)


def test_friendly_names_resolve():
    """Common remote names map to their wire keys."""
    assert resolve_key("power") == "KEY_POWER"
    assert resolve_key("home") == "KEY_HOME"
    assert resolve_key("mute") == "KEY_MUTE"
    assert resolve_key("channel_up") == "KEY_CHANNELUP"


def test_aliases_resolve_to_apk_keys():
    """Community spellings map to firmware-verified keys, never passthrough."""
    # Community docs say KEY_BACK; the APK only knows these two:
    assert resolve_key("back") == "KEY_RETURNS"
    assert resolve_key("key_back") == "KEY_RETURNS"
    assert resolve_key("key_backs") == "KEY_BACKS"
    assert resolve_key("enter") == "KEY_OK"
    assert resolve_key("input") == "KEY_SOURCES"
    assert resolve_key("ff") == "KEY_FORWARDS"


def test_app_and_number_keys():
    """App shortcuts and digit keys resolve as expected."""
    assert resolve_key("netflix") == "KEY_NETFLIX"
    assert resolve_key("youtube") == "KEY_YOUTUBE"
    assert resolve_key("prime") == "KEY_PRIME"
    assert resolve_key("disney") == "KEY_DISNEY"
    assert resolve_key("1") == "KEY_1"
    assert resolve_key("9") == "KEY_9"
    assert resolve_key("guide") == "KEY_EPG"
    assert resolve_key("settings") == "KEY_SETTINGS"


def test_unknown_and_empty():
    """Unknown, empty and whitespace-only tokens resolve to None."""
    assert resolve_key("bogus") is None
    assert resolve_key("") is None
    assert resolve_key("   ") is None


def test_all_command_map_targets_are_valid_wire_keys():
    """Every KEY_COMMANDS target must be a KEY_* token."""
    for friendly, wire in KEY_COMMANDS.items():
        assert wire.startswith("KEY_"), friendly


def test_topic_builders_match_reverse_engineered_scheme():
    """Topic builders reproduce the app's exact topic layout."""
    cid = "AA:BB:CC:DD:EE:FF$normal"
    assert (
        tv_action("remote_service", cid, "sendkey")
        == "/remoteapp/tv/remote_service/AA:BB:CC:DD:EE:FF$normal/actions/sendkey"
    )
    assert subscribe_own(cid) == "/remoteapp/mobile/AA:BB:CC:DD:EE:FF$normal/#"
    assert SUBSCRIBE_BROADCAST == "/remoteapp/mobile/broadcast/#"
