"""Tests for the DLNA RenderingControl mute reader (no TV required)."""

from __future__ import annotations

from typing import Self

import pytest

from hisense_tv.dlna import (
    RenderingControl,
    parse_get_mute_response,
    parse_rendering_control_url,
)

HOST = "10.0.3.73"
DEFAULT_URL = f"http://{HOST}:38400/MediaServer/rendererdevicedesc.xml"
CONTROL_URL = f"http://{HOST}:38400/upnp/control/mingusrcr"

# Service list as the 65A6101EE describes itself (shortened).
DESCRIPTION = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><device>
<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
<serviceList>
<service><serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
<controlURL>/upnp/control/mingusavtr</controlURL></service>
<service><serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
<controlURL>/upnp/control/mingusrcr</controlURL></service>
</serviceList></device></root>"""


def _mute_answer(value: str) -> bytes:
    """A GetMute response exactly as the TV sends it."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        '<u:GetMuteResponse xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
        f"<CurrentMute>{value}</CurrentMute></u:GetMuteResponse></s:Body></s:Envelope>"
    ).encode()


class FakeResponse:
    """Minimal aiohttp response context manager."""

    def __init__(self, status: int, body: bytes) -> None:
        """Store the canned answer."""
        self.status = status
        self._body = body

    async def __aenter__(self) -> Self:
        """Enter the response context."""
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Leave the response context."""

    async def read(self) -> bytes:
        """Return the canned body."""
        return self._body


class FakeSession:
    """Answers by URL; records every request."""

    def __init__(self, answers: dict[str, tuple[int, bytes]]) -> None:
        """Map URL to (status, body); unknown URLs raise like a dead host."""
        self.answers = answers
        self.requests: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **_kwargs: object) -> FakeResponse:
        """Record the request and return the canned answer."""
        self.requests.append((method, url))
        if url not in self.answers:
            raise OSError("host unreachable")
        return FakeResponse(*self.answers[url])


def test_control_url_is_resolved_against_the_description():
    """The relative controlURL becomes absolute on the description's host."""
    assert parse_rendering_control_url(DESCRIPTION, DEFAULT_URL) == CONTROL_URL


def test_description_without_rendering_control_yields_none():
    """A MediaServer description has no RenderingControl service."""
    assert parse_rendering_control_url(b"<root><device/></root>", DEFAULT_URL) is None
    assert parse_rendering_control_url(b"not xml", DEFAULT_URL) is None


@pytest.mark.parametrize(
    ("value", "expected"), [("1", True), ("0", False), ("true", True), ("x", None)]
)
def test_get_mute_response_parsing(value, expected):
    """CurrentMute is read as the TV sends it (verified live: 1 and 0)."""
    assert parse_get_mute_response(_mute_answer(value)) is expected


@pytest.mark.asyncio
async def test_mute_is_read_via_the_default_hisense_location():
    """Without an SSDP announcement the fixed Hisense location is used."""
    session = FakeSession(
        {DEFAULT_URL: (200, DESCRIPTION), CONTROL_URL: (200, _mute_answer("1"))}
    )
    renderer = RenderingControl(session, HOST)

    assert await renderer.async_get_mute() is True
    assert await renderer.async_get_mute() is True
    # The description is fetched once; later reads only ask GetMute.
    assert session.requests == [
        ("GET", DEFAULT_URL),
        ("POST", CONTROL_URL),
        ("POST", CONTROL_URL),
    ]


@pytest.mark.asyncio
async def test_announced_location_is_preferred():
    """The location SSDP announced wins over the fixed one."""
    announced = f"http://{HOST}:40000/desc.xml"
    session = FakeSession(
        {
            announced: (200, DESCRIPTION.replace(b"38400", b"40000")),
            f"http://{HOST}:40000/upnp/control/mingusrcr": (200, _mute_answer("0")),
        }
    )

    async def locate() -> str:
        return announced

    renderer = RenderingControl(session, HOST, locate)

    assert await renderer.async_get_mute() is False
    assert session.requests[0] == ("GET", announced)


@pytest.mark.asyncio
async def test_unreachable_renderer_reads_none_and_retries_later():
    """A dead renderer never raises; the next read looks the service up again."""
    session = FakeSession({DEFAULT_URL: (200, DESCRIPTION)})
    renderer = RenderingControl(session, HOST)

    assert await renderer.async_get_mute() is None
    assert await renderer.async_get_mute() is None
    assert session.requests.count(("GET", DEFAULT_URL)) == 2
