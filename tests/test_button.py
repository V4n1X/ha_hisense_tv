"""Tests for Hisense TV button entities."""

from __future__ import annotations

from hisense_tv.button import (
    BUTTON_DESCRIPTIONS,
    selected_button_descriptions,
)
from hisense_tv.const import CONF_BUTTONS, DEFAULT_BUTTONS, KEY_COMMANDS


def test_button_descriptions_match_valid_keys():
    """All button entities map to valid KEY_* tokens."""
    for desc in BUTTON_DESCRIPTIONS:
        assert desc.key_command.startswith("KEY_")
        assert desc.key_command in KEY_COMMANDS.values()


def test_no_duplicate_power_or_wol_buttons():
    """Power and Wake-on-LAN are covered by media_player and must not be buttons."""
    keys = {desc.key for desc in BUTTON_DESCRIPTIONS}
    assert "power" not in keys
    assert "wake_on_lan" not in keys


def test_default_buttons_are_valid_subset():
    """DEFAULT_BUTTONS must reference existing descriptions."""
    keys = {desc.key for desc in BUTTON_DESCRIPTIONS}
    assert set(DEFAULT_BUTTONS) <= keys
    # Deliberately small default set.
    assert len(DEFAULT_BUTTONS) <= 6


def test_defaults_create_only_default_buttons():
    """Without options, exactly the default buttons are created."""
    descs = selected_button_descriptions({})
    assert [d.key for d in descs] == [key for key in BUTTON_DESCRIPTIONS_KEYS_DEFAULT()]


def BUTTON_DESCRIPTIONS_KEYS_DEFAULT():  # noqa: N802 - helper kept local
    return [d.key for d in selected_button_descriptions({CONF_BUTTONS: list(DEFAULT_BUTTONS)})]


def test_options_filter_selection():
    """Only the selected keys produce entities."""
    descs = selected_button_descriptions({CONF_BUTTONS: ["home", "netflix"]})
    assert [d.key for d in descs] == ["home", "netflix"]


def test_options_filter_unknown_keys_ignored():
    """Unknown keys (e.g. removed buttons from older versions) are dropped."""
    descs = selected_button_descriptions({CONF_BUTTONS: ["home", "wake_on_lan", "power", "bogus"]})
    assert [d.key for d in descs] == ["home"]


def test_options_empty_selection_creates_no_buttons():
    """An explicit empty selection creates no button entities."""
    assert selected_button_descriptions({CONF_BUTTONS: []}) == []
