# Release Notes — v1.4.0

Wake-on-LAN now works for TVs added by IP address, and the integration moves to the Home Assistant 2026.9 device registry.

## ⚠️ Breaking

- **Home Assistant 2026.9 or newer is required.** The integration now looks up its registry device with the entry-scoped `async_get_device_by_identifier` API introduced in the 2026.9 device registry rework (the old `async_get_device` is deprecated). HACS only offers this update on HA 2026.9+; older installations stay on v1.3.6.

## 🐛 Fixed

- **SSDP discovery never received any reply, so Wake-on-LAN silently did nothing for TVs added by IP** ([#1](https://github.com/V4n1X/ha_hisense_tv/pull/1), thanks [@Anzic23](https://github.com/Anzic23)). The M-SEARCH socket was `connect()`ed to the multicast group, and a connected UDP socket drops the unicast replies the TVs actually send. As a result the background enrichment never learned the TV's MAC addresses, `media_player.turn_on` sent no magic packet, and `turn_off` raised `NotConnected` while the TV was in standby.

  The scan now binds locally, sends to the multicast group explicitly and uses one datagram per search target. After updating, **restart Home Assistant once with the TV switched on**: the entry is enriched with both MAC addresses, model and firmware version, and `media_player.turn_on` wakes the TV from standby (about 25 s on the tested HE88L5V).

## 🔒 Hardened

- UPnP device descriptions from the network are parsed with `defusedxml` (protection against XML entity-expansion attacks). This adds `defusedxml` as a runtime dependency, installed automatically.

## 🛠️ Under the hood

- **CI runs on Python 3.14 against current Home Assistant.** HA 2026.3+ requires Python 3.14.2, so CI on Python 3.13 had silently been testing HA 2026.2.
- **Deprecation canary:** CI boots a real Home Assistant, sets the integration up, injects a capability push message and fails as soon as HA reports deprecated API usage or a blocking call — so the next HA deprecation is caught before users see it.
- **Code style enforced by ruff** with Home Assistant's official rule set (lint and format), plus pre-commit hooks running the same checks locally.
- **Coverage measurement with a ratchet gate**, new tests for the SSDP scan and the device-metadata helpers.

## 📋 All changes

See the [commit history](https://github.com/V4n1X/ha_hisense_tv/compare/v1.3.6...v1.4.0) for the complete list.
