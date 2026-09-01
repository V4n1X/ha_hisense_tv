"""Data models and payload parsers for the Hisense TV protocol."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .const import VOLUME_TYPE_LEVEL, VOLUME_TYPE_MUTE


def _loads(payload: str | bytes | None) -> Any:
    """Best-effort JSON decode; the TV occasionally sends empty payloads."""
    if not payload:
        return None
    try:
        return json.loads(payload)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class SourceInfo:
    """One entry of a ui_service/sourcelist response (zhnstruction SourceInfo)."""

    sourceid: str = ""
    sourcename: str = ""
    displayname: str = ""
    is_signal: bool = False
    is_lock: bool = False
    hotel_mode: str = ""

    @property
    def label(self) -> str:
        return self.displayname or self.sourcename or self.sourceid

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceInfo:
        def _str(key: str) -> str:
            value = data.get(key)
            return "" if value is None else str(value)

        return cls(
            sourceid=_str("sourceid"),
            sourcename=_str("sourcename"),
            displayname=_str("displayname"),
            is_signal=str(data.get("is_signal", "")).lower() in ("1", "true"),
            is_lock=str(data.get("is_lock", "")).lower() in ("1", "true"),
            hotel_mode=_str("hotel_mode"),
        )

    @classmethod
    def parse_list(cls, payload: str | bytes | None) -> list[SourceInfo]:
        data = _loads(payload)
        if not isinstance(data, list):
            return []
        return [cls.from_dict(item) for item in data if isinstance(item, dict)]


@dataclass(slots=True)
class AppInfo:
    """One entry of a ui_service/applist response (installed TV apps).

    The exact wire format is reverse engineered and varies between firmware
    generations, so parsing is deliberately defensive: dicts with any known
    key spelling are accepted, plain strings are treated as app names with a
    derived launch url, and anything else is skipped.
    """

    name: str
    url: str = ""
    url_type: int = 37
    store_type: int = 0

    @classmethod
    def parse(cls, data: Any) -> AppInfo | None:
        if isinstance(data, str):
            name = data.strip()
            return cls(name=name, url=name.lower().replace(" ", "")) if name else None
        if not isinstance(data, dict):
            return None

        def _first(*keys: str) -> str:
            for key in keys:
                value = data.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return ""

        name = _first("name", "appName", "app_name", "displayname")
        if not name:
            return None
        url = _first("url", "appUrl", "app_url") or name.lower().replace(" ", "")
        return cls(
            name=name,
            url=url,
            url_type=_to_int(data.get("urlType", data.get("url_type")), 37),
            store_type=_to_int(data.get("storeType", data.get("store_type")), 0),
        )

    @classmethod
    def parse_list(cls, payload: str | bytes | None) -> list[AppInfo]:
        data = _loads(payload)
        if isinstance(data, dict):
            # Some firmwares wrap the list: {"applist": [...]} / {"data": [...]}
            data = next((v for v in data.values() if isinstance(v, list)), None)
        if not isinstance(data, list):
            return []
        apps: list[AppInfo] = []
        seen: set[str] = set()
        for item in data:
            app = cls.parse(item)
            if app is not None and app.name.lower() not in seen:
                seen.add(app.name.lower())
                apps.append(app)
        return apps


@dataclass(slots=True)
class VolumeUpdate:
    """platform_service volume feedback.

    volume_type 0/1 carry the level (0-100); type 2 carries the mute flag in
    volume_value (1 = muted). See RemoteActivity.onEventMainThread.
    """

    level: int | None = None
    muted: bool | None = None

    @classmethod
    def parse(cls, payload: str | bytes | None) -> VolumeUpdate:
        data = _loads(payload)
        update = cls()
        if not isinstance(data, dict):
            return update
        try:
            vtype = int(data.get("volume_type"))
            value = int(data.get("volume_value"))
        except (TypeError, ValueError):
            return update
        if vtype == VOLUME_TYPE_MUTE:
            update.muted = bool(value)
        elif vtype in VOLUME_TYPE_LEVEL:
            update.level = max(0, min(100, value))
        return update


@dataclass(slots=True)
class StateUpdate:
    """ui_service/state feedback: {"statetype": "...", ...extras}.

    On sourceswitch the payload also carries sourceid/sourcename/is_signal/
    is_lock/hotel_mode/displayname (see Krazy998 sample).
    """

    statetype: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, payload: str | bytes | None) -> StateUpdate:
        data = _loads(payload)
        if not isinstance(data, dict):
            return cls()
        statetype = str(data.get("statetype") or "")
        extras = {k: v for k, v in data.items() if k != "statetype"}
        return cls(statetype, extras)


@dataclass(slots=True)
class AuthenResult:
    """Response to an authenticationcode publish: {"result": 0|1, "info": "..."}."""

    result: int = -1
    info: str = ""

    @property
    def ok(self) -> bool:
        return self.result == 1

    @classmethod
    def parse(cls, payload: str | bytes | None) -> AuthenResult:
        data = _loads(payload)
        if not isinstance(data, dict):
            return cls()
        try:
            result = int(data.get("result", -1))
        except (TypeError, ValueError):
            result = -1
        return cls(result=result, info=str(data.get("info") or ""))


@dataclass(slots=True)
class CapabilityInfo:
    """Subset of zhnstruction.capability.CapabilityTvInfo worth keeping."""

    brand: str = ""
    device_id: str = ""
    feature_code: str = ""
    chip_platform: str = ""
    fake_sleep: int = 0
    fake_sleep_state: int = 1
    audio_capture_supported: bool = False
    screen_capture_supported: bool = False

    @classmethod
    def parse(cls, payload: str | bytes | None) -> CapabilityInfo:
        data = _loads(payload)
        info = cls()
        if not isinstance(data, dict):
            return info
        info.brand = str(data.get("brand") or "")
        info.device_id = str(data.get("deviceid") or "")
        info.feature_code = str(data.get("featurecode") or "")
        info.chip_platform = str(data.get("chipplatform") or "")
        info.fake_sleep = _to_int(data.get("fake_sleep"), 0)
        info.fake_sleep_state = _to_int(data.get("fake_sleep_state"), 1)
        info.audio_capture_supported = _to_int(data.get("audio_capture_supported")) == 1
        info.screen_capture_supported = _to_int(data.get("screen_capture_supported")) == 1
        return info


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class TvState:
    """Mutable runtime state assembled from push feedback and polls."""

    connected: bool = False
    volume_level: int | None = None
    muted: bool | None = None
    source_id: str | None = None
    source_name: str | None = None
    source_list: list[SourceInfo] = field(default_factory=list)
    app_list: list[AppInfo] = field(default_factory=list)
    tv_state: str | None = None
    screen_on: bool | None = None
    capability: CapabilityInfo | None = None
    app_version: str | None = None

    def apply_volume(self, update: VolumeUpdate) -> bool:
        changed = False
        if update.level is not None and update.level != self.volume_level:
            self.volume_level = update.level
            changed = True
        if update.muted is not None and update.muted != self.muted:
            self.muted = update.muted
            changed = True
        return changed

    def apply_state(self, update: StateUpdate) -> bool:
        changed = False
        if update.statetype:
            if update.statetype != self.tv_state:
                self.tv_state = update.statetype
                changed = True
            if update.statetype == "fake_sleep_0":
                self.screen_on = False
                changed = True
            elif update.statetype == "fake_sleep_1":
                self.screen_on = True
                changed = True
        extras = update.extras
        source_id = extras.get("sourceid")
        if source_id is not None:
            new_id = str(source_id)
            if new_id != self.source_id:
                self.source_id = new_id
                changed = True
        for key in ("sourcename", "displayname"):
            if extras.get(key):
                name = str(extras[key])
                if name != self.source_name:
                    self.source_name = name
                    changed = True
                break
        return changed

    def apply_sources(self, sources: list[SourceInfo]) -> bool:
        self.source_list = sources
        return True

    def apply_apps(self, apps: list[AppInfo]) -> bool:
        if apps == self.app_list:
            return False
        self.app_list = apps
        return True

    def current_source(self) -> SourceInfo | None:
        for source in self.source_list:
            if self.source_id and source.sourceid == self.source_id:
                return source
        return None
