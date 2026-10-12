"""Tests for protocol payload parsers."""

from hisense_tv.models import (
    AuthenResult,
    CapabilityInfo,
    SourceInfo,
    StateUpdate,
    TvState,
    VolumeUpdate,
)

SOURCELIST_SAMPLE = """[
 {"sourceid":"4","sourcename":"HDMI 2","displayname":"HDMI 2","is_signal":"1","is_lock":"0","hotel_mode":"0"},
 {"sourceid":"0","sourcename":"TV","displayname":"TV","is_signal":"1","is_lock":"0","hotel_mode":"0"}
]"""

STATE_SAMPLE = '{"statetype":"sourceswitch","sourceid":"4","sourcename":"HDMI 2","is_signal":1,"is_lock":0,"hotel_mode":0,"displayname":"HDMI 2"}'


def test_volume_level_types_0_and_1():
    """Types 0/1 carry the level; out-of-range values are clamped to 0-100."""
    assert VolumeUpdate.parse('{"volume_type":0,"volume_value":42}').level == 42
    assert VolumeUpdate.parse('{"volume_type":1,"volume_value":7}').level == 7
    update = VolumeUpdate.parse('{"volume_type":0,"volume_value":250}')
    assert update.level == 100  # clamped


def test_volume_mute_type_2():
    """Type 2 carries the mute flag, never a level."""
    muted = VolumeUpdate.parse('{"volume_type":2,"volume_value":1}')
    unmuted = VolumeUpdate.parse('{"volume_type":2,"volume_value":0}')
    assert muted.muted is True and muted.level is None
    assert unmuted.muted is False


def test_volume_garbage_payload_is_noop():
    """Empty or non-JSON payloads produce an empty (no-change) update."""
    update = VolumeUpdate.parse("")
    assert update.level is None and update.muted is None
    assert VolumeUpdate.parse("not json").level is None


def test_sourcelist_parsing_matches_krazy998_sample():
    """The community-captured sourcelist sample parses field by field."""
    sources = SourceInfo.parse_list(SOURCELIST_SAMPLE)
    assert len(sources) == 2
    hdmi2 = sources[0]
    assert hdmi2.sourceid == "4"
    assert hdmi2.label == "HDMI 2"
    assert hdmi2.is_signal is True
    assert sources[1].label == "TV"


def test_state_feedback_with_source_extras():
    """Sourceswitch state messages carry sourceid/sourcename as extras."""
    state = StateUpdate.parse(STATE_SAMPLE)
    assert state.statetype == "sourceswitch"
    assert state.extras["sourceid"] == "4"
    assert state.extras["displayname"] == "HDMI 2"


def test_authen_result_ok_and_fail():
    """result=1 means accepted, anything else rejected with an info string."""
    assert AuthenResult.parse('{"result":1,"info":""}').ok is True
    failed = AuthenResult.parse('{"result":0,"info":"wrong"}')
    assert failed.ok is False and failed.info == "wrong"


def test_capability_parsing():
    """Capability fields map from the camelCase wire names."""
    cap = CapabilityInfo.parse(
        '{"brand":"hisense","deviceid":"dev123","featurecode":"FC","chipplatform":"mtk",'
        '"fake_sleep":1,"fake_sleep_state":0,"audio_capture_supported":1,"screen_capture_supported":0}'
    )
    assert cap.brand == "hisense"
    assert cap.fake_sleep_state == 0
    assert cap.audio_capture_supported is True
    assert cap.screen_capture_supported is False


def test_tv_state_transitions():
    """Applying updates mutates TvState and reports change-vs-dedupe."""
    state = TvState()
    assert state.apply_volume(VolumeUpdate(level=30)) is True
    assert state.volume_level == 30
    assert state.apply_volume(VolumeUpdate(muted=True)) is True
    assert state.muted is True
    assert state.apply_state(StateUpdate.parse(STATE_SAMPLE)) is True
    assert state.source_id == "4"
    assert state.source_name == "HDMI 2"
    assert state.apply_state(StateUpdate.parse('{"statetype":"fake_sleep_0"}')) is True
    assert state.screen_on is False
    # Dedupe: same values again -> no change
    assert state.apply_volume(VolumeUpdate(level=30)) is False
