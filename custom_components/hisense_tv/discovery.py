"""SSDP/UPnP discovery for Hisense TVs.

The RemoteNOW app discovers TVs through a native DLNA/UPnP stack. The UPnP
device description carries a ``modelDescription`` element containing a
newline separated key=value block with everything needed to connect:

    transport_protocol=2100
    platform=1
    region=6
    country=DEU
    model_name=65A71FS
    tv_version=...
    language=deu
    macWifi=AABBCCDDEEFF
    macEthernet=001122334455
    voice=1
    mqttport=36669

This module reproduces that without the native library: M-SEARCH on the SSDP
multicast group, HTTP GET on each LOCATION, parse + filter.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .const import DEFAULT_PORT, TLS_TRANSPORT_MIN

_LOGGER = logging.getLogger(__name__)

SSDP_ADDRESS = ("239.255.255.250", 1900)
SEARCH_TARGETS = (
    "ssdp:all",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
)

# Keys we read out of the modelDescription block (DevInfoManager.a/b).
_KEY_MQTT_PORT = "mqttport"
_KEY_TRANSPORT = "transport_protocol"
_INTERESTING_KEYS = (
    _KEY_MQTT_PORT,
    _KEY_TRANSPORT,
    "platform",
    "region",
    "country",
    "model_name",
    "tv_version",
    "language",
    "macwifi",
    "macethernet",
    "voice",
)


@dataclass(slots=True)
class DiscoveredTV:
    """A Hisense TV found via SSDP."""

    host: str
    name: str = ""
    manufacturer: str = ""
    model_name: str = ""
    tv_version: str = ""
    udn: str = ""
    mqtt_port: int = DEFAULT_PORT
    use_tls: bool = False
    mac_wifi: str = ""
    mac_ethernet: str = ""
    transport_protocol: int | None = None
    platform: str = ""
    region: str = ""
    country: str = ""
    language: str = ""
    location: str = ""
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def unique_id(self) -> str:
        """Stable identifier: prefer wifi MAC, then ethernet MAC, then UDN."""
        for mac in (self.mac_wifi, self.mac_ethernet):
            if mac:
                return format_mac(mac)
        return self.udn or f"{self.host}:{self.mqtt_port}"

    @property
    def wake_mac(self) -> str | None:
        """MAC used for Wake-on-LAN (APK prefers wifi, falls back to ethernet)."""
        for mac in (self.mac_wifi, self.mac_ethernet):
            clean = mac.replace(":", "").replace("-", "")
            if clean and set(clean) != {"0"}:
                return format_mac(mac)
        return None


def format_mac(mac: str) -> str:
    """Normalize a raw (often AABBCCDDEEFF) or already formatted MAC."""
    clean = mac.replace(":", "").replace("-", "").strip().upper()
    if len(clean) != 12:
        return mac.upper()
    return ":".join(clean[i : i + 2] for i in range(0, 12, 2))


def parse_ssdp_response(data: bytes) -> dict[str, str]:
    """Parse an SSDP M-SEARCH response into lowercase headers."""
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - never let one packet kill the scan
        return {}
    headers: dict[str, str] = {}
    for line in text.split("\r\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    return headers


def host_from_location(location: str) -> str | None:
    """Extract the host from an SSDP LOCATION URL."""
    try:
        return urlparse(location).hostname
    except ValueError:
        return None


def parse_model_description(text: str) -> dict[str, str]:
    """Parse the newline or delimiter separated key=value block from modelDescription."""
    result: dict[str, str] = {}
    if not text:
        return result
    import re
    tokens = re.split(r"[\r\n;,]+", text)
    for token in tokens:
        token = token.strip()
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            result[key] = value
    return result


def is_hisense_remote_tv(manufacturer: str, description: dict[str, str]) -> bool:
    """Filter rule: must look like a Hisense advertising the remote protocol.

    The presence of mqttport=/transport_protocol= in modelDescription is the
    definitive marker; manufacturer alone would also match non-Vidaa sets.
    """
    if _KEY_MQTT_PORT in description or _KEY_TRANSPORT in description:
        return True
    manu = (manufacturer or "").strip().lower()
    return (manu.startswith("hisense") or manu.startswith("vidaa") or "hisense" in manu or "vidaa" in manu) and bool(description)


def parse_upnp_dict(upnp_dict: dict[str, Any], host: str = "") -> DiscoveredTV | None:
    """Extract DiscoveredTV directly from a parsed UPnP dictionary."""
    values = {str(k).lower(): str(v) for k, v in upnp_dict.items() if v is not None}
    friendly = values.get("friendlyname", "")
    manufacturer = values.get("manufacturer", "")
    udn = values.get("udn", "")
    desc = parse_model_description(values.get("modeldescription", ""))
    if not is_hisense_remote_tv(manufacturer, desc):
        return None

    raw_port = desc.get(_KEY_MQTT_PORT, "")
    try:
        mqtt_port = int(raw_port) if raw_port else DEFAULT_PORT
    except ValueError:
        mqtt_port = DEFAULT_PORT

    raw_trans = desc.get(_KEY_TRANSPORT, "")
    try:
        transport = int(raw_trans) if raw_trans else None
    except ValueError:
        transport = None

    use_tls = transport is not None and transport >= TLS_TRANSPORT_MIN

    tv = DiscoveredTV(
        host=host,
        name=friendly or (f"Hisense TV ({host})" if host else "Hisense TV"),
        manufacturer=manufacturer,
        model_name=desc.get("model_name") or values.get("modelfriendlyname", "") or values.get("modelnumber", ""),
        tv_version=desc.get("tv_version", ""),
        udn=udn,
        region=desc.get("region", ""),
        country=desc.get("country", ""),
        language=desc.get("language", ""),
        mac_wifi=desc.get("macwifi", ""),
        mac_ethernet=desc.get("macethernet", ""),
        mqtt_port=mqtt_port,
        transport_protocol=transport,
        use_tls=use_tls,
        extras=desc,
    )
    return tv


def parse_device_description(xml_bytes: bytes) -> DiscoveredTV | None:
    """Parse a UPnP device description XML into a DiscoveredTV (if Hisense)."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    device = None
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1].lower() == "device":
            device = el
            break
    if device is None:
        return None

    values: dict[str, str] = {}
    for child in device:
        tag = child.tag.rsplit("}", 1)[-1].lower()
        values[tag] = (child.text or "").strip()

    friendly = values.get("friendlyname", "")
    manufacturer = values.get("manufacturer", "")
    udn = values.get("udn", "")

    desc = parse_model_description(values.get("modeldescription", ""))
    if not is_hisense_remote_tv(manufacturer, desc):
        return None

    tv = DiscoveredTV(
        host="",
        name=friendly,
        manufacturer=manufacturer,
        model_name=desc.get("model_name") or values.get("modelfriendlyname", "") or values.get("modelnumber", ""),
        tv_version=desc.get("tv_version", ""),
        udn=udn,
        region=desc.get("region", ""),
        country=desc.get("country", ""),
        language=desc.get("language", ""),
        extras={k: v for k, v in desc.items() if k not in _INTERESTING_KEYS},
    )

    port_raw = desc.get(_KEY_MQTT_PORT, "")
    try:
        tv.mqtt_port = int(port_raw)
    except ValueError:
        tv.mqtt_port = DEFAULT_PORT

    transport_raw = desc.get(_KEY_TRANSPORT, "")
    try:
        tv.transport_protocol = int(transport_raw)
    except ValueError:
        tv.transport_protocol = None
    tv.use_tls = tv.transport_protocol is not None and tv.transport_protocol >= TLS_TRANSPORT_MIN

    tv.mac_wifi = format_mac(desc.get("macwifi", "")) if desc.get("macwifi") else ""
    tv.mac_ethernet = format_mac(desc.get("macethernet", "")) if desc.get("macethernet") else ""

    # The app prefers the ethernet MAC as device identity when present.
    tv.extras.update(
        {
            "voice": desc.get("voice", ""),
            "platform": desc.get("platform", ""),
            "transport": transport_raw,
        }
    )
    return tv


async def fetch_description(location: str, timeout: float = 5.0) -> DiscoveredTV | None:
    """Download and parse a UPnP device description (aiohttp ships with HA)."""
    import aiohttp  # noqa: PLC0415 - keep module importable without HA deps

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(location, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                data = await resp.read()
    except Exception:  # noqa: BLE001 - unreachable TV during scan is normal
        return None
    tv = parse_device_description(data)
    if tv is not None:
        tv.location = location
        tv.host = host_from_location(location) or tv.host
        if not tv.name:
            tv.name = f"Hisense TV ({tv.host})"
    return tv


class _SsdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, results: dict[str, dict[str, str]], done: asyncio.Event) -> None:
        self._results = results
        self._done = done

    def datagram_received(self, data: bytes, _addr) -> None:  # type: ignore[no-untyped-def]
        headers = parse_ssdp_response(data)
        location = headers.get("location")
        if location:
            self._results[location] = headers

    def connection_lost(self, _exc: Exception | None) -> None:
        self._done.set()


async def async_scan(timeout: float = 4.0) -> list[str]:
    """Send M-SEARCH and collect unique LOCATION URLs."""
    loop = asyncio.get_running_loop()
    done = asyncio.Event()
    results: dict[str, dict[str, str]] = {}

    request_lines = []
    for st in SEARCH_TARGETS:
        request_lines.extend(
            [
                "M-SEARCH * HTTP/1.1",
                f"HOST: {SSDP_ADDRESS[0]}:{SSDP_ADDRESS[1]}",
                f'ST: "{st}"' if st == "ssdp:all" else f"ST: {st}",
                'MAN: "ssdp:discover"',
                f"MX: {max(1, int(timeout))}",
                "",
                "",
            ]
        )
    payload = "\r\n".join(request_lines).encode("ascii")

    try:
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: _SsdpProtocol(results, done),
            remote_addr=SSDP_ADDRESS,
            reuse_port=True,
        )
    except (OSError, NotImplementedError, ValueError):
        # SO_REUSE_PORT is unavailable on e.g. Windows.
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: _SsdpProtocol(results, done),
            remote_addr=SSDP_ADDRESS,
        )
    transport.sendto(payload)

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(done.wait(), timeout)
    transport.close()
    return list(results)


async def async_discover_tvs(timeout: float = 4.0) -> list[DiscoveredTV]:
    """Run a full discovery cycle and return parsed Hisense TVs."""
    locations = await async_scan(timeout)
    _LOGGER.debug("SSDP scan found %d unique locations", len(locations))
    descriptions = await asyncio.gather(*(fetch_description(loc) for loc in locations))
    tvs = [tv for tv in descriptions if tv is not None]
    _LOGGER.debug(
        "Discovery: %d/%d descriptions are Hisense remote TVs (%s)",
        len(tvs),
        len(descriptions),
        ", ".join(f"{tv.host or '?'}/{tv.model_name}" for tv in tvs) or "none",
    )
    return tvs


def build_magic_packet(mac: str) -> bytes:
    """Build a Wake-on-LAN magic packet (6x FF + 16x MAC)."""
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(clean) != 12:
        raise ValueError(f"invalid MAC address: {mac!r}")
    mac_bytes = bytes.fromhex(clean)
    return b"\xff" * 6 + mac_bytes * 16


async def async_send_wol(mac: str, port: int = 33129, repeat: int = 5, interval: float = 0.1) -> None:
    """Send a WOL magic packet the way the APK does (repeat x interval).

    Uses broadcast 255.255.255.255 like NetReceiver does.
    """
    packet = build_magic_packet(mac)
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    transport, _protocol = await loop.create_datagram_endpoint(lambda: asyncio.Protocol(), sock=sock)
    try:
        for _ in range(max(1, repeat)):
            transport.sendto(packet, ("255.255.255.255", port))
            if interval > 0:
                await asyncio.sleep(interval)
    finally:
        transport.close()
