"""Tests for the applist feature: parsing, dedupe and TvState handling."""

from __future__ import annotations

import json

from hisense_tv.models import AppInfo, TvState


def test_parse_app_list_from_dicts():
    """Standard wire format: list of dicts with name/url/urlType/storeType."""
    payload = json.dumps(
        [
            {"name": "Netflix", "url": "netflix", "urlType": 2, "storeType": 0},
            {"name": "YouTube", "url": "youtube", "urlType": 37, "storeType": 1},
        ]
    )
    apps = AppInfo.parse_list(payload)
    assert [app.name for app in apps] == ["Netflix", "YouTube"]
    assert apps[0].url == "netflix"
    assert apps[0].url_type == 2
    assert apps[1].store_type == 1


def test_parse_app_list_alternative_key_spellings():
    """Firmware variants use appName/appUrl and snake_case spellings."""
    payload = json.dumps(
        [
            {"appName": "Prime Video", "appUrl": "prime"},
            {"app_name": "Disney", "url_type": 5},
        ]
    )
    apps = AppInfo.parse_list(payload)
    assert [app.name for app in apps] == ["Prime Video", "Disney"]
    assert apps[0].url == "prime"
    assert apps[1].url_type == 5


def test_parse_app_list_plain_strings():
    """Plain strings become app names with a derived launch url."""
    apps = AppInfo.parse_list(json.dumps(["Netflix", "  ", ""]))
    assert [app.name for app in apps] == ["Netflix"]
    assert apps[0].url == "netflix"


def test_parse_app_list_wrapped_dict():
    """Some firmwares wrap the list: {"applist": [...]}."""
    payload = json.dumps({"applist": [{"name": "Plex"}]})
    apps = AppInfo.parse_list(payload)
    assert [app.name for app in apps] == ["Plex"]


def test_parse_app_list_dedupe_case_insensitive():
    """Duplicate apps (any casing) appear exactly once."""
    payload = json.dumps([{"name": "Netflix"}, {"name": "netflix"}, {"name": "YouTube"}])
    apps = AppInfo.parse_list(payload)
    assert [app.name for app in apps] == ["Netflix", "YouTube"]


def test_parse_app_list_invalid_payloads_return_empty():
    """Garbage, empty and non-list payloads yield no apps and must not raise."""
    assert AppInfo.parse_list(None) == []
    assert AppInfo.parse_list("") == []
    assert AppInfo.parse_list("not json") == []
    assert AppInfo.parse_list(json.dumps({"foo": "bar"})) == []


def test_parse_app_list_skips_entries_without_name():
    """Dict entries without any name variant are dropped, others kept."""
    payload = json.dumps([{"url": "no-name-here"}, {"name": "Netflix"}])
    apps = AppInfo.parse_list(payload)
    assert [app.name for app in apps] == ["Netflix"]


def test_apply_apps_stores_list_and_reports_change():
    state = TvState()
    apps = [AppInfo(name="Netflix"), AppInfo(name="YouTube")]
    assert state.apply_apps(apps) is True
    assert state.app_list == apps
    # identical list -> no change signal
    assert state.apply_apps([AppInfo(name="Netflix"), AppInfo(name="YouTube")]) is False
    # changed list -> change signal
    assert state.apply_apps([]) is True
    assert state.app_list == []
