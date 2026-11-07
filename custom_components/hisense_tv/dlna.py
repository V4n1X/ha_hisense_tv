"""UPnP RenderingControl access for the state MQTT does not carry.

The TV never reports its mute state over MQTT, but its DLNA renderer's
RenderingControl service does (``GetMute``), for a mute from the TV's own
remote as well (verified live on a 65A6101EE). The service sends no GENA
events for it, so the state is polled.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Any
from urllib.parse import urljoin
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as DefusedElementTree

_LOGGER = logging.getLogger(__name__)

RENDERING_CONTROL = "urn:schemas-upnp-org:service:RenderingControl:1"
# Fixed location of the renderer description in Hisense's DLNA stack; used
# until SSDP has announced the real one.
DEFAULT_DESCRIPTION_URL = "http://{host}:38400/MediaServer/rendererdevicedesc.xml"
REQUEST_TIMEOUT = 3.0

_GET_MUTE_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
    f'<u:GetMute xmlns:u="{RENDERING_CONTROL}">'
    "<InstanceID>0</InstanceID><Channel>Master</Channel>"
    "</u:GetMute></s:Body></s:Envelope>"
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_rendering_control_url(xml_bytes: bytes, description_url: str) -> str | None:
    """Absolute control URL of the RenderingControl service, if described."""
    try:
        root = DefusedElementTree.fromstring(xml_bytes)
    except (ParseError, ValueError):
        return None
    for service in root.iter():
        if _local(service.tag) != "service":
            continue
        fields = {_local(child.tag): (child.text or "").strip() for child in service}
        if fields.get("serviceType") == RENDERING_CONTROL and fields.get("controlURL"):
            return urljoin(description_url, fields["controlURL"])
    return None


def parse_get_mute_response(xml_bytes: bytes) -> bool | None:
    """CurrentMute of a GetMute response; None when it carries none."""
    try:
        root = DefusedElementTree.fromstring(xml_bytes)
    except (ParseError, ValueError):
        return None
    for element in root.iter():
        if _local(element.tag) == "CurrentMute":
            value = (element.text or "").strip().lower()
            if value in ("1", "true"):
                return True
            if value in ("0", "false"):
                return False
    return None


class RenderingControl:
    """Reads the mute state from the TV's DLNA renderer; never raises."""

    def __init__(
        self,
        session: Any,
        host: str,
        locate: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        """Remember how to find the renderer's description.

        ``locate`` returns the description URL SSDP announced, if any; the
        fixed Hisense location is the fallback.
        """
        self._session = session
        self._locate = locate
        self._default_url = DEFAULT_DESCRIPTION_URL.format(host=host)
        self._control_url: str | None = None

    def forget_control_url(self) -> None:
        """Look the service up again (the TV rebooted or moved)."""
        self._control_url = None

    async def _request(self, method: str, url: str, **kwargs: Any) -> bytes | None:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(method, url, **kwargs) as response:
                    if response.status != 200:
                        _LOGGER.debug("%s %s answered %s", method, url, response.status)
                        return None
                    return await response.read()
        except (TimeoutError, OSError, ValueError) as err:
            _LOGGER.debug("%s %s failed: %s", method, url, err)
        except Exception as err:  # noqa: BLE001 - aiohttp error hierarchy
            _LOGGER.debug("%s %s failed: %s", method, url, err)
        return None

    async def _resolve_control_url(self) -> str | None:
        if self._control_url is not None:
            return self._control_url
        candidates = [self._default_url]
        if self._locate is not None and (announced := await self._locate()):
            candidates.insert(0, announced)
        for description_url in dict.fromkeys(candidates):
            description = await self._request("GET", description_url)
            if description is not None and (
                control_url := parse_rendering_control_url(description, description_url)
            ):
                self._control_url = control_url
                break
        return self._control_url

    async def async_get_mute(self) -> bool | None:
        """Current mute state, or None when the renderer cannot be asked."""
        control_url = await self._resolve_control_url()
        if control_url is None:
            return None
        answer = await self._request(
            "POST",
            control_url,
            data=_GET_MUTE_BODY.encode(),
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPACTION": f'"{RENDERING_CONTROL}#GetMute"',
            },
        )
        if answer is None:
            # Maybe a stale control URL; resolve it again next time.
            self.forget_control_url()
            return None
        return parse_get_mute_response(answer)
