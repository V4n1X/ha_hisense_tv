"""Async MQTT client for the Hisense TV broker (aiomqtt).

Reproduces MqttConnectManager/MqttCmdManager of the RemoteNOW app:
- connect to tcp:// or ssl:// on the TV (port 36669 by default)
- shared credentials, stable per-client identifier
- subscribe to /remoteapp/mobile/broadcast/# and /remoteapp/mobile/<cid>/#
- publish actions to /remoteapp/tv/<service>/<cid>/actions/<action>
- dispatch feedback by last topic segment
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import ssl
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable

from .const import (
    ACTION_APP_VERSION,
    ACTION_AUTHENTICATION_CODE,
    ACTION_AUTHENTICATION_CODE_CLOSE,
    ACTION_CAPABILITY,
    ACTION_CHANGE_SOURCE,
    ACTION_CHANGE_VOLUME,
    ACTION_GET_TV_STATE,
    ACTION_GET_VOLUME,
    ACTION_INPUT,
    ACTION_LAUNCH_APP,
    ACTION_SEND_KEY,
    ACTION_SOURCE_LIST,
    CLIENT_CERT_FILE,
    CONNECT_TIMEOUT,
    DISPATCH_APPS,
    DISPATCH_AUTH_RESULT,
    DISPATCH_AUTH_TOAST,
    DISPATCH_CAPABILITY,
    DISPATCH_CONNECTION,
    DISPATCH_PAIRING_REQUIRED,
    DISPATCH_SOURCES,
    DISPATCH_STATE,
    DISPATCH_VOLUME,
    KEEPALIVE,
    RECONNECT_MAX,
    RECONNECT_MIN,
    SERVICE_PLATFORM,
    SERVICE_REMOTE,
    SERVICE_UI,
    SUBSCRIBE_BROADCAST,
    TOPIC_CLIENT_BROADCAST,
    TOPIC_FUNC_APP_LIST,
    TOPIC_FUNC_APP_VERSION,
    TOPIC_FUNC_AUTH_CLOSE,
    TOPIC_FUNC_AUTH_RESULT,
    TOPIC_FUNC_AUTH_TOAST,
    TOPIC_FUNC_CAPABILITY,
    TOPIC_FUNC_PAIRING_REQUIRED,
    TOPIC_FUNC_SOURCE_LIST,
    TOPIC_FUNC_STATE,
    TOPIC_FUNC_VOLUMES,
    MQTT_PASSWORD,
    MQTT_USERNAME,
    subscribe_own,
    tv_action,
)
from .discovery import async_send_wol
from .models import (
    AuthenResult,
    CapabilityInfo,
    SourceInfo,
    StateUpdate,
    VolumeUpdate,
)

_LOGGER = logging.getLogger(__name__)

EventCallback = Callable[[str, Any], None]


class HisenseTvError(Exception):
    """Base error."""


class CannotConnect(HisenseTvError):
    """TCP/TLS/MQTT connection failed."""


class NotConnected(HisenseTvError):
    """Command attempted while disconnected."""


def default_client_cert_path() -> Path | None:
    """Path to the bundled RemoteNOW client certificate (if present)."""
    path = Path(__file__).parent / CLIENT_CERT_FILE
    return path if path.is_file() else None


def new_client_id() -> str:
    """Stable-enough unique client id; one config entry keeps one forever."""
    return f"ha-hisense-{uuid.uuid4().hex[:12]}"


class HisenseTvClient:
    """Long-lived MQTT connection with automatic reconnect."""

    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        *,
        use_tls: bool | None = None,
        client_cert_path: str | Path | None = None,
        event_callback: EventCallback | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        # None = auto (try tcp, escalate on TLS handshake failure)
        self.use_tls = use_tls
        self.client_cert_path = str(client_cert_path) if client_cert_path else None
        self.on_event = event_callback

        self.connected = False
        self.active_tls = False

        self._client: Any = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._events: deque[tuple[str, Any]] = deque(maxlen=64)

    # -- lifecycle ---------------------------------------------------------

    async def start(self, *, allow_offline: bool = False) -> None:
        """Connect once, then keep the reconnect task running.

        With ``allow_offline`` the initial connection failure (TV powered off
        at HA start) is tolerated: the reconnect loop keeps retrying in the
        background so Wake-on-LAN can power the TV back on.
        """
        try:
            await self._connect_once()
        except CannotConnect:
            if not allow_offline:
                raise
            _LOGGER.debug(
                "%s:%s unreachable at start - reconnect loop keeps retrying",
                self.host,
                self.port,
            )
        self._stopping = False
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._disconnect()

    def _build_ssl_context(self) -> ssl.SSLContext:
        """TOFU-style TLS: accept the TV's self-signed certificate.

        The bundled RemoteNOW client certificate authenticates us when the TV
        requires mutual TLS (e.g. A71 series).
        """
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        cert_path = self.client_cert_path or (
            str(default_client_cert_path()) if default_client_cert_path() else None
        )
        if cert_path and Path(cert_path).is_file():
            try:
                ctx.load_cert_chain(cert_path)
                _LOGGER.debug("Using bundled client certificate: %s", cert_path)
            except ssl.SSLError as err:
                _LOGGER.warning("Could not load client certificate %s: %s", cert_path, err)
        return ctx

    async def _connect_once(self) -> None:
        import aiomqtt  # noqa: PLC0415 - optional dependency

        attempts: list[bool] = [False] if self.use_tls is not True else [True]
        if self.use_tls is None:
            attempts.append(True)

        last_error: Exception | None = None
        for tls in attempts:
            uri_host = self.host
            try:
                # The TV broker speaks MQTT 3.1 (MQIsdp); a 3.1.1 CONNECT is
                # answered with CONNACK "not authorized" on current firmware.
                protocol = None
                try:
                    from aiomqtt import ProtocolVersion  # noqa: PLC0415

                    protocol = ProtocolVersion.V31
                except ImportError:
                    pass
                client = aiomqtt.Client(
                    hostname=uri_host,
                    port=self.port,
                    identifier=self.client_id,
                    username=MQTT_USERNAME,
                    password=MQTT_PASSWORD,
                    tls_context=self._build_ssl_context() if tls else None,
                    protocol=protocol,
                    keepalive=KEEPALIVE,
                )
                await self._open_client(client, CONNECT_TIMEOUT)
            except asyncio.TimeoutError as err:
                last_error = err
                continue
            except OSError as err:
                # TLS handshake failures against a plain broker land here.
                last_error = err
                continue
            except Exception as err:  # noqa: BLE001 - aiomqtt error hierarchy varies
                last_error = err
                continue

            self._client = client
            self.active_tls = tls
            self.connected = True
            for topic in (SUBSCRIBE_BROADCAST, subscribe_own(self.client_id)):
                await client.subscribe(topic)
                _LOGGER.debug("Subscribed: %s", topic)
            self._emit(DISPATCH_CONNECTION, True)
            _LOGGER.debug("Connected to %s:%s (tls=%s)", self.host, self.port, tls)
            return

        raise CannotConnect(f"{self.host}:{self.port}: {last_error}")

    async def _open_client(self, client: Any, timeout: float) -> None:
        """Connect supporting both aiomqtt API generations.

        aiomqtt >= 2.0 removed ``connect()``; the connection is opened via the
        async context manager protocol (``__aenter__``).
        """
        connect = getattr(client, "connect", None)
        if connect is not None:
            await asyncio.wait_for(connect(), timeout=timeout)
        else:
            await asyncio.wait_for(client.__aenter__(), timeout=timeout)

    async def _disconnect(self) -> None:
        was_connected = self.connected
        self.connected = False
        client, self._client = self._client, None
        if client is not None:
            disconnect = getattr(client, "disconnect", None)
            if disconnect is not None:
                with contextlib.suppress(Exception):
                    disconnect()
            else:  # aiomqtt >= 2.0 closes via __aexit__
                with contextlib.suppress(Exception):
                    await client.__aexit__(None, None, None)
        if was_connected:
            self._emit(DISPATCH_CONNECTION, False)

    async def _run_forever(self) -> None:
        """Listen loop with exponential backoff reconnect."""
        backoff = RECONNECT_MIN
        while not self._stopping:
            try:
                if not self.connected:
                    await self._disconnect()
                    await self._connect_once()
                    backoff = RECONNECT_MIN
                assert self._client is not None
                async for message in self._client.messages:
                    try:
                        self._handle_message(str(message.topic), message.payload)
                    except Exception:  # noqa: BLE001 - one bad payload must not kill us
                        _LOGGER.exception("Failed to handle message on %s", message.topic)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect on any transport error
                if self._stopping:
                    return
                if self.connected:
                    await self._disconnect()
                _LOGGER.debug("Connection lost (%s), retrying in %.0fs", err, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX)

    # -- messaging ---------------------------------------------------------

    def recent_events(self) -> list[tuple[str, Any]]:
        """Snapshot of recent feedback events (used during pairing)."""
        return list(self._events)

    def pop_event(self, name: str, after_index: int = 0) -> tuple[Any, int] | None:
        """Return the newest queued event matching name, plus its index."""
        for index in range(len(self._events) - 1, -1, -1):
            event_name, data = self._events[index]
            if event_name == name and index >= after_index:
                return data, index
        return None

    def _emit(self, name: str, data: Any) -> None:
        self._events.append((name, data))
        if self.on_event is not None:
            try:
                self.on_event(name, data)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Event callback failed for %s", name)

    def _handle_message(self, topic: str, payload: bytes | bytearray | str) -> None:
        parts = topic.split("/")
        # /remoteapp/mobile/<ident>/<service>/<...>/<function>
        if len(parts) < 5 or parts[1] != "remoteapp" or parts[2] != "mobile":
            return
        ident = parts[3]
        if ident not in (TOPIC_CLIENT_BROADCAST, self.client_id):
            return
        function = parts[-1].lstrip("/")
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
        _LOGGER.debug("%s <- %s = %s", self.client_id, topic, text[:200])

        if function == TOPIC_FUNC_STATE:
            self._emit(DISPATCH_STATE, StateUpdate.parse(text))
        elif function in TOPIC_FUNC_VOLUMES:
            self._emit(DISPATCH_VOLUME, VolumeUpdate.parse(text))
        elif function == TOPIC_FUNC_SOURCE_LIST:
            self._emit(DISPATCH_SOURCES, SourceInfo.parse_list(text))
        elif function == TOPIC_FUNC_APP_LIST:
            self._emit(DISPATCH_APPS, text)
        elif function == TOPIC_FUNC_PAIRING_REQUIRED:
            self._emit(DISPATCH_PAIRING_REQUIRED, text)
        elif function == TOPIC_FUNC_AUTH_RESULT:
            self._emit(DISPATCH_AUTH_RESULT, AuthenResult.parse(text))
        elif function == TOPIC_FUNC_AUTH_TOAST:
            # NOT a success signal: the TV sends this when the remote slot is
            # already occupied by another device ("device busy" toast).
            self._emit(DISPATCH_AUTH_TOAST, text)
        elif function == TOPIC_FUNC_AUTH_CLOSE:
            _LOGGER.debug("TV closed the pairing dialog")
        elif function == TOPIC_FUNC_CAPABILITY:
            self._emit(DISPATCH_CAPABILITY, CapabilityInfo.parse(text))
        elif function == TOPIC_FUNC_APP_VERSION:
            version = text.strip().strip('"')
            if version:
                self._emit(DISPATCH_APP_VERSION, version)

    async def _publish(self, service: str, action: str, payload: str = "") -> bool:
        if not self.connected or self._client is None:
            raise NotConnected(f"{self.host}:{self.port}")
        topic = tv_action(service, self.client_id, action)
        try:
            await self._client.publish(topic, payload.encode())
            _LOGGER.debug("%s -> %s = %s", self.client_id, topic, payload[:200])
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Publish %s/%s failed: %s", service, action, err)
            return False
        return True

    # -- commands ----------------------------------------------------------

    async def send_key(self, key: str) -> bool:
        return await self._publish(SERVICE_REMOTE, ACTION_SEND_KEY, key)

    async def send_text(self, text: str) -> bool:
        return await self._publish(SERVICE_REMOTE, ACTION_INPUT, text)

    async def set_volume(self, level: int) -> bool:
        level = max(0, min(100, int(level)))
        # Firmware expects a plain number string (RemoteVolumeView: "" + volume).
        return await self._publish(SERVICE_PLATFORM, ACTION_CHANGE_VOLUME, str(level))

    async def get_volume(self) -> bool:
        return await self._publish(SERVICE_PLATFORM, ACTION_GET_VOLUME, "")

    async def get_tv_state(self) -> bool:
        return await self._publish(SERVICE_UI, ACTION_GET_TV_STATE, "")

    async def request_source_list(self) -> bool:
        return await self._publish(SERVICE_UI, ACTION_SOURCE_LIST, "")

    async def select_source(self, source_id: str) -> bool:
        payload = json.dumps({"sourceid": source_id})
        return await self._publish(SERVICE_UI, ACTION_CHANGE_SOURCE, payload)

    async def launch_app(self, url: str, name: str, url_type: int = 37, store_type: int = 0) -> bool:
        payload = json.dumps({"name": name, "urlType": url_type, "storeType": store_type, "url": url})
        return await self._publish(SERVICE_UI, ACTION_LAUNCH_APP, payload)

    async def request_capability(self) -> bool:
        return await self._publish(SERVICE_UI, ACTION_CAPABILITY, "")

    async def request_app_version(self) -> bool:
        return await self._publish(SERVICE_UI, ACTION_APP_VERSION, "")

    async def submit_pairing_code(self, code: str) -> bool:
        payload = json.dumps({"authNum": code})
        return await self._publish(SERVICE_UI, ACTION_AUTHENTICATION_CODE, payload)

    async def cancel_pairing(self) -> bool:
        return await self._publish(SERVICE_UI, ACTION_AUTHENTICATION_CODE_CLOSE, "")

    async def wake_on_lan(self, mac: str) -> None:
        await async_send_wol(mac)


async def wait_for_event(
    client: HisenseTvClient,
    names: frozenset[str] | str,
    timeout: float,
    start_index: int = 0,
) -> tuple[str, Any]:
    """Wait until one of the named events arrives (polling the event ring)."""
    if isinstance(names, str):
        names = frozenset({names})
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        best: tuple[int, str, Any] | None = None
        snapshot = client.recent_events()
        for index in range(len(snapshot) - 1, -1, -1):
            event_name, data = snapshot[index]
            if event_name in names and index >= start_index:
                if best is None or index > best[0]:
                    best = (index, event_name, data)
        if best is not None:
            return best[1], best[2]
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError(f"No {sorted(names)} within {timeout}s")
        await asyncio.sleep(0.05)
