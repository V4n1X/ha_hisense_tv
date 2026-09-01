<div align="center">
  <img src="https://raw.githubusercontent.com/home-assistant/brands/master/custom_integrations/hisense_tv/logo.png" alt="Hisense" width="220"/>
  <h1>Hisense TV for Home Assistant</h1>
  <p><a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS"/></a>
  <a href="https://github.com/V4n1X/ha_hisensetv/releases/latest"><img src="https://img.shields.io/github/v/release/V4n1X/ha_hisensetv?include_prereleases" alt="Release"/></a>
  <a href="https://github.com/V4n1X/ha_hisensetv/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/V4n1X/ha_hisensetv/ci.yml?branch=main" alt="CI"/></a></p>
</div>

Custom integration that controls Hisense Vidaa TVs via the **MQTT broker embedded in the TV** — using the reverse-engineered protocol of the official **Hisense RemoteNOW** app (`com.universal.remote.ms` 5.01.011).

> **Migration:** This integration is a standalone replacement for `sehaas/ha_hisense_tv` and uses the same domain `hisense_tv`. Uninstall any existing `hisense_tv` integration before installing.

## Features

- **media_player** — On/Off, volume set/mute, Play/Pause/Stop, Next/Previous track, source selection (HDMI/TV/…)
- **remote** — all 60+ remote keys via `remote.send_command`
- **Sensors** — volume (%), active source, TV state (`sourceswitch`, `app`, `livetv`, … incl. fake sleep/screen state) + diagnostic attributes (firmware, chip platform, capabilities)
- **Auto-discovery** — SSDP-based (like the app), plus a manual network scan during setup and IP repair via DHCP/MAC
- **First pairing like the app** — when the TV shows a 4-digit pairing code, the setup flow asks for it; on newer firmware generations with encrypted MQTT the bundled RemoteNOW client certificate is used automatically
- **Device registry** — model, manufacturer, firmware, MAC and name are registered from UPnP/discovery/capability data
- **"Pairing lost" repair flow** — after a TV reset or firmware update a repair notification appears that leads straight into PIN re-pairing
- Reconfigure (change IP), Reconfirm (IP changed by DHCP), Reauth (pairing expired), Options flow (polling, WOL, command pacing, button selection)

## Supported devices

Tested against the protocol generation of RemoteNOW 5.x (Vidaa-U/VIDAA TVs, standard MQTT port 36669). TVs requiring a client certificate (e.g. A71 series) are covered by the bundled certificate. Older firmware without push feedback works without the pairing step.

## Installation

### Prerequisites

- Home Assistant ≥ **2024.3** with **HACS** installed
- TV and Home Assistant on the **same network**, TV powered **on during setup**
- Recommendation: enable *Network Standby / Quick Start* on the TV (so automations can power it on later)

### Step by step via HACS

**1. Download the integration**

1. Open **HACS** in the sidebar.
2. Click the **three dots (⋮)** in the bottom right → **Add custom repository**.
3. Enter and confirm:
   - *Repository:* `https://github.com/V4n1X/ha_hisensetv`
   - *Category:* `Integration`
4. The repository appears in the HACS list → open it → click **Download**.

**2. Restart Home Assistant**

5. *Settings → System → Restart* (custom integrations require a full restart).

**3. Set up the integration**

6. *Settings → Devices & Services* → **Add Integration** in the bottom right.
7. Search for and select **"Hisense TV"**.
8. In the dialog:
   - Leave the *Host/IP* field **empty** → the network is scanned automatically via SSDP → select a discovered TV,
   - or enter the TV's IP directly (leave the port unchanged: **36669**).
9. The connection is validated — on newer firmware generations including automatic TLS encryption with the bundled client certificate.

**4. PIN pairing on the TV (if requested)**

10. If the TV shows a **4-digit pairing code on screen**, the *"Pair with your TV"* window appears in Home Assistant.
11. Enter the four digits there. If the code expires on the TV, simply wait a moment until a new one is shown and try again.
    - No PIN window? Older firmware doesn't require authorization — the setup then closes directly.

**5. Done**

12. The device is registered with manufacturer, model, firmware version and MAC address. Entities (`media_player`, `remote`, sensors) are available immediately.

> 📖 Detailed guide with troubleshooting, TV settings and quick tests: [`docs/INSTALLATION.md`](docs/INSTALLATION.md)

### Pairing & connection problems during setup

| Problem | Solution |
|---|---|
| **"Failed to connect"** | Power on the TV (not deep eco standby); test reachability: `telnet <TV-IP> 36669`; rule out VLAN/AP client isolation |
| **TV not found during scan** | SSDP/multicast is often blocked by mesh Wi-Fi → just enter the IP manually |
| **Pairing code rejected** (`invalid_pin`) | The code expires on the TV after ~30 seconds → wait until the TV shows a new one, then enter it fresh |
| **No PIN window** | Older firmware doesn't require authorization — the setup closes automatically, all good |
| **No code appears on the TV** | The official RemoteNOW/VIDAA app occupies the remote session → close the app completely and retry (details: [INSTALLATION.md](docs/INSTALLATION.md)) |
| **Pairing fails despite correct code** | TV may have been powered off in the meantime? Cancel setup, power on the TV, add the integration again |

> After a TV reset or firmware update the pairing can expire: the integration notifies you and walks you through the PIN entry via Reauth.

### Manual

```bash
git clone https://github.com/V4n1X/ha_hisensetv /tmp/ha_hisensetv
mkdir -p <config>/custom_components
cp -r /tmp/ha_hisensetv/custom_components/hisense_tv <config>/custom_components/
rm -rf /tmp/ha_hisensetv
```

Then restart HA and continue with step 6 of the HACS instructions.

## Changing settings after setup

| Action | Where |
|---|---|
| Change IP/port | *Integration → Configure* (Reconfigure, with revalidation) |
| Polling/WOL/pacing/button selection | *Integration → Options* |
| IP changed by DHCP | happens automatically (Reconfirm via device-bound MAC) |
| TV was reset / pairing lost | the integration notifies you; Reauth asks for the PIN again |

## Remote commands & buttons

Besides the `remote` entity the integration also provides quick-action buttons. By default **5 buttons** are created (*Home*, *Back*, *Source*, *Settings*, *Info*) — Power and Wake-on-LAN are deliberately not buttons, as they are already covered by `media_player.turn_on/turn_off`.

Via *Integration → Options* you can select exactly the buttons you want from **22 available ones** via multi-select — including navigation (*OK*, *Up/Down/Left/Right*), volume/channels (*Volume ±*, *Mute*, *Channel ±*) and app shortcuts (*Netflix*, *YouTube*, *Prime Video*, *Disney+*, *Plex*).

### Sending keys via service (`remote.send_command`)

```yaml
service: remote.send_command
target:
  entity_id: remote.hisense_tv_remote
data:
  command: home
```

Multiple keys: `command: ["1", "2"]` or `"back, ok"` · pacing via the `command_delay` option or `delay_secs`.

> 📋 **All 60+ keys & apps**: full overview of all keys, direct apps, color keys and digits in [`docs/REMOTE_KEYS.md`](docs/REMOTE_KEYS.md).

## Technical details

The complete reverse-engineered protocol (topics, payloads, credential derivation, pairing sequence, discovery, WOL, discrepancies with community sources) is documented in [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

Short version:

- MQTT on `tcp://<TV>:36669`, user `hisenseservice`, password `multimqttservice` (static in every RemoteNOW installation)
- Commands: `/remoteapp/tv/<service>/<clientId>/actions/<action>` · feedback: `/remoteapp/mobile/broadcast/#` + `/remoteapp/mobile/<clientId>/#`
- `changevolume` accepts plain numbers (0–100); mute is `KEY_MUTE`
- Power on via Wake-on-LAN: magic packet 5× every 100 ms to UDP port **33129**

## Troubleshooting (runtime)

Setup and pairing issues are covered above under Installation. Common runtime topics:

| Symptom | Cause/Solution |
|---|---|
| Entities `unavailable` although the TV shows a picture | Broker only reachable in "fast" standby; check eco standby |
| No volume/state values | Some models only push after the first `getvolume` poll (option: reduce interval) |
| Powering on via automation fails | Enable "Network Standby/Quick Start" on the TV, otherwise WOL is impossible |
| Suddenly unresponsive after a TV update | A firmware update can reset the pairing → wait for the Reauth flow and re-enter the PIN |

## Acknowledgements

The reverse-engineering community this project builds upon:

- [Krazy998/mqtt-hisensetv](https://github.com/Krazy998/mqtt-hisensetv) – first public protocol documentation
- [sehaas/ha_hisense_tv](https://github.com/sehaas/ha_hisense_tv) – Mosquitto bridge approach, PIN flow, client certificate experience
- [newAM/hisensetv_hass](https://github.com/newAM/hisensetv_hass)
- [d3nd3/Hisense-mqtt-keyfiles](https://github.com/d3nd3/Hisense-mqtt-keyfiles)

## Changelog

### 1.3.1

**Fixed**

- **Setup crash (`NameError: CONF_MAC_WIFI`)** after a config-entry reload when the entry had no stored MAC addresses — the background metadata-enrichment path referenced constants that were accidentally removed during the 1.3.0 refactor
- **App-version feedback ignored**: a missing constant import made the integration drop every `/appversion` push from the TV
- **Blocking call warning**: the TLS client certificate is now loaded in an executor thread instead of blocking the event loop at setup

**Added**

- Static `pyflakes` gate in CI (would have caught both crashes above) plus a repo-wide encoding sanity test
- CI actions updated (checkout v7, setup-python v7), README header with Hisense logo and badges

### 1.3.0

**New**

- **Button selection via options flow:** Only 5 buttons by default (*Home*, *Back*, *Source*, *Settings*, *Info*); via the integration options you can multi-select exactly the ones you want from 22 available keys (navigation, volume/channels, app shortcuts)
- **"Pairing lost" repair flow:** After a TV reset or firmware update a repair notification appears in *Settings → System → Repairs* that leads straight into PIN re-pairing
- **TV may be powered off at HA start:** The "Setup error, will retry" failure when the TV is off is gone — setup completes, the reconnect loop retries in the background, and **Wake-on-LAN works even after an HA restart with the TV powered off**

**Fixed**

- **Stable device identity:** The `unique_id` is now based on the MAC (instead of the client UUID that changes on re-pairing) — no more duplicate device after Reauth
- **Proper error messages:** "TV not connected" is reported as a translated error instead of a raw `NotConnected` exception (affects off/volume/playback control and `remote.send_command`)

**Improved**

- Shared entity base (`entity.py`) removes duplicated code across all platform files (device info, WOL logic)
- Background task via `entry.async_create_background_task` (HA-managed reference tracking, therefore minimum version HA 2024.3)
- Backwards-compatible translations (de/en) incl. `exceptions` schema, hassfest validation passes cleanly
- `aiomqtt` requirement capped (`>=2.0.0,<3.0.0`)
- Tested against Home Assistant 2026.8 (all modules import without deprecation warnings)

### 1.2.4

Last release before this changelog — see [v1.2.4](https://github.com/V4n1X/ha_hisensetv/releases/tag/v1.2.4).

## License

MIT — see [LICENSE](LICENSE).
