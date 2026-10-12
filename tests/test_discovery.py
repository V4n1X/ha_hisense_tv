"""Tests for SSDP/UPnP parsing and Wake-on-LAN helpers."""

import asyncio

from hisense_tv.discovery import (
    DiscoveredTV,
    build_magic_packet,
    format_mac,
    host_from_location,
    is_hisense_remote_tv,
    parse_device_description,
    parse_model_description,
)

HISENSE_XML = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>Wohnzimmer TV</friendlyName>
    <manufacturer>Hisense</manufacturer>
    <manufacturerURL>http://www.hisense.com</manufacturerURL>
    <modelDescription>transport_protocol=2100
platform=1
region=6
country=DEU
model_name=65A71FS
tv_version=V0000.01.00a.N0821
language=deu
macWifi=AABBCCDDEEFF
macEthernet=001122334455
voice=1
mqttport=36669</modelDescription>
    <modelName>65A71FS</modelName>
    <UDN>uuid:12345678-90ab-cdef-1234-567890abcdef</UDN>
  </device>
</root>"""

OTHER_XML = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>Samsung TV</friendlyName>
    <manufacturer>Samsung Electronics</manufacturer>
    <modelName>UE55NU7400</modelName>
    <UDN>uuid:aaaa-bbbb</UDN>
  </device>
</root>"""


def test_format_mac_variants():
    """Raw, dashed and lowercase MACs normalize to colon-separated upper case."""
    assert format_mac("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"
    assert format_mac("AA-BB-CC-DD-EE-FF") == "AA:BB:CC:DD:EE:FF"
    assert format_mac("aa:bb:cc:dd:ee:ff") == "AA:BB:CC:DD:EE:FF"


def test_parse_model_description_block():
    """The modelDescription key=value block parses case-insensitively."""
    desc = parse_model_description("mqttport=36669\nmacWifi=AABBCCDDEEFF\nvoice=1\n")
    assert desc == {"mqttport": "36669", "macwifi": "AABBCCDDEEFF", "voice": "1"}


def test_parse_hisense_device_description():
    """A full device description yields every field the integration needs."""
    tv = parse_device_description(HISENSE_XML)
    assert tv is not None
    assert tv.name == "Wohnzimmer TV"
    assert tv.model_name == "65A71FS"
    assert tv.tv_version == "V0000.01.00a.N0821"
    assert tv.mqtt_port == 36669
    assert tv.mac_wifi == "AA:BB:CC:DD:EE:FF"
    assert tv.mac_ethernet == "00:11:22:33:44:55"
    # transport_protocol=2100 >= 1000 -> encrypted MQTT like newer models
    assert tv.transport_protocol == 2100
    assert tv.use_tls is True
    assert tv.unique_id == "AA:BB:CC:DD:EE:FF"
    assert tv.wake_mac in ("AA:BB:CC:DD:EE:FF", "00:11:22:33:44:55")


def test_non_hisense_xml_rejected():
    """Foreign TVs are filtered out."""
    assert parse_device_description(OTHER_XML) is None


def test_broken_xml_returns_none():
    """Malformed XML is rejected without raising."""
    assert parse_device_description(b"<not xml") is None


def test_filter_rule():
    """mqttport/transport_protocol mark a remote TV; bare brand match counts."""
    assert is_hisense_remote_tv("Hisense", {"mqttport": "36669"}) is True
    assert is_hisense_remote_tv("ACME", {"transport_protocol": "2100"}) is True
    assert is_hisense_remote_tv("Hisense", {"foo": "bar"}) is True
    assert is_hisense_remote_tv("Samsung", {}) is False
    assert is_hisense_remote_tv("Samsung", {"friendly": "x"}) is False


def test_unique_id_fallback_chain():
    """Without MACs the UDN becomes the unique id."""
    tv = DiscoveredTV(host="1.2.3.4")
    tv.udn = "uuid:x"
    assert tv.unique_id == "uuid:x"


def test_wol_magic_packet():
    """The magic packet has the 6x-FF header and repeats the MAC 16 times."""
    packet = build_magic_packet("00:11:22:33:44:55")
    assert len(packet) == 102  # 6 x FF + 16 x MAC
    assert packet[:6] == b"\xff" * 6
    assert packet[6:12] == bytes.fromhex("001122334455")
    assert packet[96:] == bytes.fromhex("001122334455")


def test_wol_rejects_invalid_mac():
    """MACs that are not 12 hex digits raise ValueError."""
    try:
        build_magic_packet("nope")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_null_manufacturer_upnp_payload():
    """Regression test for real-world Hisense TV UPnP with manufacturer=null and #CAP# prefix."""
    from hisense_tv.discovery import parse_upnp_dict

    upnp_data = {
        "deviceType": "urn:schemas-upnp-org:device:MediaRenderer:1",
        "friendlyName": "Fernseher Schlafzimmer",
        "manufacturer": None,
        "manufacturerURL": "http://www.hisense.com",
        "modelDescription": "#CAP#\nmac=18300c123245\nmacWifi=6023a4b9b449\nmacEthernet=18300c123245\nip=10.0.3.73\nregion=4\ncountry=CZE\nmodel_name=65A6101EE_0001\ntv_version=V0000.01.00a.P0219\nlanguage=eng\ntransport_protocol=1001\nemanual=0\nnetwork_wakeup=1\nvoice=1\ncap=0\nmqttport=36669",
        "modelName": "Renderer",
        "modelNumber": "1.0",
        "UDN": "uuid:88598779-f5d6-11ea-8fbb-29f1759a22ba",
    }
    tv = parse_upnp_dict(upnp_data, host="10.0.3.73")
    assert tv is not None
    assert tv.host == "10.0.3.73"
    assert tv.name == "Fernseher Schlafzimmer"
    assert tv.model_name == "65A6101EE_0001"
    assert tv.tv_version == "V0000.01.00a.P0219"
    assert tv.mac_wifi == "6023a4b9b449"
    assert tv.mac_ethernet == "18300c123245"
    assert tv.mqtt_port == 36669
    assert tv.transport_protocol == 1001
    assert tv.use_tls is True
    assert host_from_location("::bad uri::") is None


def test_async_scan_sends_and_closes():
    """Smoke test the scan helper against loopback (no responses expected)."""
    # Smoke test the scan helper against loopback (no responses expected).
    locations = asyncio.run(asyncio.wait_for(_scan(), timeout=8))
    assert locations == []


async def _scan():
    """Run a short SSDP scan."""
    from hisense_tv.discovery import async_scan

    return await async_scan(timeout=0.3)


SSDP_REPLY = (
    b"HTTP/1.1 200 OK\r\n"
    b"CACHE-CONTROL: max-age=1800\r\n"
    b"LOCATION: http://192.0.2.10:38400/description.xml\r\n"
    b"ST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n"
    b"\r\n"
)


def test_async_scan_receives_unicast_replies(monkeypatch):
    """Replies arrive from the device's own address, never from the multicast group.

    Regression test: with remote_addr= the UDP socket was connect()ed to the
    multicast group and the kernel dropped every such reply, so no scan found
    a TV (no MAC enrichment, hence no Wake-on-LAN).
    """
    from hisense_tv import discovery

    searches: list[bytes] = []

    async def scenario() -> list[str]:
        loop = asyncio.get_running_loop()
        # The "device" answers from its own socket, i.e. from a different
        # source address than the one the M-SEARCH was sent to.
        device, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
        )

        class _Group(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                searches.append(data)
                device.sendto(SSDP_REPLY, addr)

        group, _ = await loop.create_datagram_endpoint(
            _Group, local_addr=("127.0.0.1", 0)
        )
        monkeypatch.setattr(discovery, "SSDP_ADDRESS", group.get_extra_info("sockname"))
        try:
            return await discovery.async_scan(timeout=0.5)
        finally:
            group.close()
            device.close()

    locations = asyncio.run(asyncio.wait_for(scenario(), timeout=8))

    assert locations == ["http://192.0.2.10:38400/description.xml"]
    # One datagram per search target, each carrying exactly one M-SEARCH.
    assert len(searches) == len(discovery.SEARCH_TARGETS)
    assert all(packet.count(b"M-SEARCH") == 1 for packet in searches)
