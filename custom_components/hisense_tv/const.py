"""Constants for the Hisense TV integration.

Protocol values were reverse engineered from the Hisense RemoteNOW app
(com.universal.remote.ms, v5.01.011) and cross checked against
https://github.com/Krazy998/mqtt-hisensetv and
https://github.com/sehaas/ha_hisense_tv.
"""

from __future__ import annotations

DOMAIN = "hisense_tv"
MANUFACTURER = "Hisense"

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
DEFAULT_PORT = 36669
DEFAULT_NAME = "Hisense TV"
CONNECT_TIMEOUT = 5.0
KEEPALIVE = 45
PROBE_TIMEOUT = 6.0
PAIRING_TIMEOUT = 12.0
RECONNECT_MIN = 2.0
RECONNECT_MAX = 60.0

# Shared RemoteNOW MQTT credentials (ConfigureUtils c()/d(), double base64).
MQTT_USERNAME = "hisenseservice"
MQTT_PASSWORD = "multimqttservice"

CLIENT_ID_PREFIX = "ha-hisense"

# The APK switches to ssl:// when transport_protocol >= 1001 (MqttConnectManager).
TLS_TRANSPORT_MIN = 1001

CLIENT_CERT_FILE = "certs/hisense_client.pem"

# Wake-on-LAN (WakeupManager: 5 packets, 100 ms apart, UDP port 33129).
WOL_PORT = 33129
WOL_REPEAT = 5
WOL_INTERVAL = 0.1

# ---------------------------------------------------------------------------
# Topics (TopicToRemoteService / TopicToTvUIService / TopicToTvPlatformService)
# ---------------------------------------------------------------------------
TOPIC_TV_ROOT = "/remoteapp/tv"
TOPIC_MOBILE_ROOT = "/remoteapp/mobile"
TOPIC_CLIENT_BROADCAST = "broadcast"

SERVICE_REMOTE = "remote_service"
SERVICE_UI = "ui_service"
SERVICE_PLATFORM = "platform_service"

SUBSCRIBE_BROADCAST = f"{TOPIC_MOBILE_ROOT}/{TOPIC_CLIENT_BROADCAST}/#"


def tv_action(service: str, client_id: str, action: str) -> str:
    """Build a command topic: /remoteapp/tv/<service>/<cid>/actions/<action>."""
    return f"{TOPIC_TV_ROOT}/{service}/{client_id}/actions/{action}"


def subscribe_own(client_id: str) -> str:
    """Build the per-client feedback filter."""
    return f"{TOPIC_MOBILE_ROOT}/{client_id}/#"


ACTION_SEND_KEY = "sendkey"
ACTION_INPUT = "input"
ACTION_GET_TV_STATE = "gettvstate"
ACTION_SOURCE_LIST = "sourcelist"
ACTION_CHANGE_SOURCE = "changesource"
ACTION_LAUNCH_APP = "launchapp"
ACTION_CHANGE_VOLUME = "changevolume"
ACTION_GET_VOLUME = "getvolume"
ACTION_CAPABILITY = "capability"
ACTION_APP_VERSION = "appversion"
ACTION_AUTHENTICATION_CODE = "authenticationcode"
ACTION_AUTHENTICATION_CODE_CLOSE = "authenticationcodeclose"

# Feedback *topic segments* (last part of /remoteapp/mobile/... topics).
# Firmware variants differ ("volume" vs "volumechange"), hence alias sets.
TOPIC_FUNC_STATE = "state"
TOPIC_FUNC_VOLUMES = frozenset({"volume", "volumechange", "getvolume"})
TOPIC_FUNC_SOURCE_LIST = "sourcelist"
TOPIC_FUNC_APP_LIST = "applist"
TOPIC_FUNC_PAIRING_REQUIRED = "authentication"
TOPIC_FUNC_AUTH_RESULT = "authenticationcode"
TOPIC_FUNC_AUTH_TOAST = "authenticationcodetoast"
TOPIC_FUNC_AUTH_CLOSE = "authenticationcodeclose"
TOPIC_FUNC_CAPABILITY = "capability"
TOPIC_FUNC_APP_VERSION = "appversion"

# Internal dispatch event names (what callbacks/waiters see).
DISPATCH_CONNECTION = "connection"
DISPATCH_STATE = "state"
DISPATCH_VOLUME = "volume"
DISPATCH_SOURCES = "source_list"
DISPATCH_APPS = "app_list"
DISPATCH_PAIRING_REQUIRED = "pairing_required"
DISPATCH_AUTH_RESULT = "authentication_result"
DISPATCH_AUTH_TOAST = "authentication_toast"

# Event sets the config flow waits on. Kept next to the dispatcher names so
# tests can assert they always match (regression guard: the pairing step once
# waited on the raw topic segment instead of the dispatch name).
PROBE_WAIT_EVENTS = frozenset({DISPATCH_PAIRING_REQUIRED})
AUTH_WAIT_EVENTS = frozenset({DISPATCH_AUTH_RESULT})
DISPATCH_CAPABILITY = "capability"
DISPATCH_APP_VERSION = "app_version"

# statetype values seen in /state feedback (manager.c.d dispatch table).
STATE_TYPE_SOURCESWITCH = "sourceswitch"
STATE_TYPE_LIVETV = "livetv"
STATE_TYPE_APP = "app"
STATE_TYPE_INPUT = "input"
STATE_TYPE_FAKE_SLEEP_OFF = "fake_sleep_0"
STATE_TYPE_FAKE_SLEEP_ON = "fake_sleep_1"

VOLUME_TYPE_LEVEL = (0, 1)
VOLUME_TYPE_MUTE = 2

# ---------------------------------------------------------------------------
# Keys (RemoteKeyBase) with friendly names used by remote.send_command
# ---------------------------------------------------------------------------
KEY_COMMANDS: dict[str, str] = {
    # Power & Navigation
    "power": "KEY_POWER",
    "home": "KEY_HOME",
    "menu": "KEY_MENU",
    "exit": "KEY_EXIT",
    "back": "KEY_RETURNS",
    "ok": "KEY_OK",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "info": "KEY_INFO",
    "settings": "KEY_SETTINGS",
    "tools": "KEY_TOOLS",
    "guide": "KEY_EPG",
    "epg": "KEY_EPG",
    "sources": "KEY_SOURCES",
    "source": "KEY_SOURCES",
    "tvs": "KEY_TVS",
    "livetv": "KEY_LIVETV",
    "last": "KEY_LAST",
    "aspect": "KEY_ASPECT",
    "3d": "KEY_3D",
    "cc": "KEY_CC",
    "pvr": "KEY_PVR",
    "favorite": "KEY_FAVORITE",
    "teletext": "KEY_TEXT",
    "text": "KEY_TEXT",
    "subtitle": "KEY_SUBTITLE",
    "audio": "KEY_AUDIO",
    "sleep": "KEY_SLEEP",
    "picture": "KEY_PICTURE",
    "sound": "KEY_SOUND",

    # Volume & Channel
    "volume_up": "KEY_VOLUMEUP",
    "volume_down": "KEY_VOLUMEDOWN",
    "mute": "KEY_MUTE",
    "channel_up": "KEY_CHANNELUP",
    "channel_down": "KEY_CHANNELDOWN",

    # Media Playback
    "play": "KEY_PLAY",
    "pause": "KEY_PAUSE",
    "stop": "KEY_STOP",
    "rewind": "KEY_BACKS",
    "forward": "KEY_FORWARDS",
    "previous": "KEY_PREVIOUS",
    "next": "KEY_NEXT",
    "record": "KEY_RECORD",
    "zoom_in": "KEY_ZOOMIN",
    "zoom_out": "KEY_ZOOMOUT",

    # Color Buttons
    "red": "KEY_RED",
    "green": "KEY_GREEN",
    "yellow": "KEY_YELLOW",
    "blue": "KEY_BLUE",

    # Number Keys
    "0": "KEY_0",
    "1": "KEY_1",
    "2": "KEY_2",
    "3": "KEY_3",
    "4": "KEY_4",
    "5": "KEY_5",
    "6": "KEY_6",
    "7": "KEY_7",
    "8": "KEY_8",
    "9": "KEY_9",

    # Quick App Launch Keys (Hardware Remote shortcuts)
    "netflix": "KEY_NETFLIX",
    "youtube": "KEY_YOUTUBE",
    "prime": "KEY_PRIME",
    "prime_video": "KEY_PRIME",
    "disney": "KEY_DISNEY",
    "app": "KEY_APP",
    "browser": "KEY_BROWSER",
    "deezer": "KEY_DEEZER",
    "rakuten": "KEY_RAKUTEN",
    "plex": "KEY_PLEX",
}

KEY_ALIASES: dict[str, str] = {
    # Community docs sometimes use KEY_BACK; the APK only knows KEY_BACKS /
    # KEY_RETURNS -- accept both spellings and map to firmware-verified keys.
    "return": "KEY_RETURNS",
    "returns": "KEY_RETURNS",
    "key_returns": "KEY_RETURNS",
    "key_back": "KEY_RETURNS",
    "key_backs": "KEY_BACKS",
    "enter": "KEY_OK",
    "select": "KEY_OK",
    "input": "KEY_SOURCES",
    "ch_up": "KEY_CHANNELUP",
    "ch_down": "KEY_CHANNELDOWN",
    "vol_up": "KEY_VOLUMEUP",
    "vol_down": "KEY_VOLUMEDOWN",
    "ff": "KEY_FORWARDS",
    "fr": "KEY_BACKS",
    "amazon": "KEY_PRIME",
    "amazon_prime": "KEY_PRIME",
    "disney_plus": "KEY_DISNEY",
    "disneyplus": "KEY_DISNEY",
}

MEDIA_PLAYER_KEYS: dict[str, str] = {
    "play": "KEY_PLAY",
    "pause": "KEY_PAUSE",
    "stop": "KEY_STOP",
    "next_track": "KEY_NEXT",
    "previous_track": "KEY_PREVIOUS",
}


def resolve_key(command: str) -> str | None:
    """Resolve a friendly name, alias or raw KEY_* token to a wire key."""
    token = command.strip()
    if not token:
        return None
    lowered = token.lower()
    # Aliases win over raw passthrough so community spellings like "key_back"
    # map to firmware-verified keys instead of being sent verbatim.
    alias = KEY_ALIASES.get(lowered)
    if alias:
        return alias
    key = KEY_COMMANDS.get(lowered)
    if key:
        return key
    if lowered.startswith("key_"):
        return token.upper()
    return None


# ---------------------------------------------------------------------------
# Config entry keys
# ---------------------------------------------------------------------------
CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"
CONF_USE_TLS = "use_tls"
CONF_CLIENT_ID = "client_id"
CONF_UUID = "uuid"
CONF_MAC_WIFI = "mac_wifi"
CONF_MAC_ETHERNET = "mac_ethernet"
CONF_MODEL_NAME = "model_name"
CONF_TV_VERSION = "tv_version"
CONF_PLATFORM_VERSION = "platform"
CONF_REGION = "region"
CONF_COUNTRY = "country"
CONF_LANGUAGE = "language"
CONF_TRANSPORT_PROTOCOL = "transport_protocol"
CONF_UDN = "udn"

CONF_POLL_INTERVAL = "poll_interval"
CONF_ENABLE_WOL = "enable_wol"
CONF_COMMAND_DELAY = "command_delay"
CONF_BUTTONS = "buttons"

# Buttons created by default. Power and Wake-on-LAN are deliberately absent:
# both are already covered by media_player.turn_on / media_player.turn_off.
# The full selectable list lives in button.BUTTON_DESCRIPTIONS; users can
# change the selection in the integration options.
DEFAULT_BUTTONS: tuple[str, ...] = ("home", "back", "source", "settings", "info")

DEFAULT_POLL_INTERVAL = 30
DEFAULT_ENABLE_WOL = True
DEFAULT_COMMAND_DELAY = 30
