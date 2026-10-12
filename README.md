<div align="center">
  <img src="https://raw.githubusercontent.com/home-assistant/brands/master/custom_integrations/hisense_tv/logo.png" alt="Hisense" width="220"/>
  <h1>Hisense TV for Home Assistant</h1>
  <p><b>Local control for Hisense VIDAA TVs — no cloud, no extra hardware.</b></p>
  <p><a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS"/></a>
  <a href="https://github.com/V4n1X/ha_hisense_tv/releases/latest"><img src="https://img.shields.io/github/v/release/V4n1X/ha_hisense_tv?include_prereleases" alt="Release"/></a>
  <a href="https://github.com/V4n1X/ha_hisense_tv/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/V4n1X/ha_hisense_tv/ci.yml?branch=main" alt="CI"/></a></p>
</div>

Custom integration that controls Hisense VIDAA TVs via the **MQTT broker embedded in the TV**, using the reverse-engineered protocol of the official **Hisense RemoteNOW** app (`com.universal.remote.ms` 5.01.011).

> [!IMPORTANT]
> **Migrating?** This integration is a standalone replacement for `sehaas/ha_hisense_tv` and uses the same domain `hisense_tv`. Uninstall any existing `hisense_tv` integration before installing.

## ✨ Features

| | Platform | What you get |
|---|---|---|
| 📺 | `media_player` | On/off, volume set/mute, play/pause/stop, next/previous track, source selection (HDMI/TV/…) **plus installed apps** — picking an app in the source selector launches it on the TV |
| 🎮 | `remote` | All 60+ remote keys via `remote.send_command` |
| 📊 | `sensor` | Volume (%), active source, TV state (`sourceswitch`, `app`, `livetv`, … incl. fake sleep/screen state) and diagnostic attributes (firmware, chip platform, capabilities) |
| 🔘 | `button` | Quick-action buttons for the most common keys, selectable in the options |

**Under the hood**

- 🔍 **Auto-discovery** — SSDP like the app, plus a manual network scan during setup and IP repair via DHCP/MAC
- 🔐 **PIN pairing like the app** — when the TV shows a 4-digit code, the setup asks for it; on newer firmware with encrypted MQTT the bundled RemoteNOW client certificate is used automatically
- 🏷️ **Device registry** — model, manufacturer, firmware, MAC and name are filled in automatically
- ♻️ **Self-healing** — Reconfigure (change IP), automatic IP update via DHCP/MAC, and Reauth with a repair notification when the pairing is lost after a TV reset or firmware update

## 📺 Supported devices

Tested against the protocol generation of RemoteNOW 5.x (VIDAA / Vidaa-U TVs, standard MQTT port 36669).

- 🔒 TVs requiring a client certificate (e.g. A71 series) are covered by the bundled certificate.
- 📼 Older firmware without push feedback works without the pairing step.

## 📦 Installation

**Requirements**

- Home Assistant ≥ **2026.9** with [HACS](https://hacs.xyz) installed
- TV and Home Assistant on the **same network**, TV powered **on during setup**

> [!TIP]
> Enable *Network Standby / Quick Start* on the TV so automations can power it on later.

### 1️⃣ Download via HACS

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=V4n1X&repository=ha_hisense_tv&category=integration)

Click the button, confirm that HACS adds the repository, then click **Download**. Restart Home Assistant afterwards (*Settings → System → Restart*).

<details>
<summary>Without the button</summary>

1. Open **HACS** → **⋮** (top right) → **Custom repositories**.
2. Enter `https://github.com/V4n1X/ha_hisense_tv` with category **Integration** and confirm.
3. Open **Hisense TV** in HACS and click **Download**, then restart Home Assistant.

</details>

### 2️⃣ Add the integration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=hisense_tv)

Click the button or go to *Settings → Devices & Services → Add Integration* and search for **Hisense TV**. Then either

- leave *Host/IP* **empty** to scan the network via SSDP and pick a discovered TV, or
- enter the TV's IP directly (keep the port at **36669**).

### 3️⃣ Pair with the TV (if requested)

If the TV shows a **4-digit pairing code**, the *"Pair with your TV"* dialog opens in Home Assistant — enter the code there. The code is only valid for about 30 seconds; if it expires, wait for the TV to show a new one and try again. If no PIN dialog appears, the firmware needs no pairing and the setup simply finishes.

> [!WARNING]
> **Close the official RemoteNOW/VIDAA app first.** The TV allows only one active remote session — while the phone app is connected, the TV shows no pairing code.

🎉 Done — the device is registered with manufacturer, model, firmware and MAC, and all entities are available immediately.

> 📖 Full guide with TV settings, quick tests and more troubleshooting: [`docs/INSTALLATION.md`](docs/INSTALLATION.md)

<details>
<summary>Manual installation (without HACS)</summary>

```bash
git clone https://github.com/V4n1X/ha_hisense_tv /tmp/ha_hisense_tv
mkdir -p <config>/custom_components
cp -r /tmp/ha_hisense_tv/custom_components/hisense_tv <config>/custom_components/
rm -rf /tmp/ha_hisense_tv
```

Then restart Home Assistant and continue with step 2.

</details>

## 🔧 Configuration

| Action | Where |
|---|---|
| Change IP/port | *Integration → Configure* (Reconfigure, with revalidation) |
| Polling, WOL, command pacing, button selection | *Integration → Options* |
| IP changed by DHCP | Handled automatically — the TV is recognized by its MAC |
| TV was reset / pairing lost | The integration notifies you; Reauth asks for the PIN again |

## 🎮 Remote commands & buttons

Besides the `remote` entity the integration provides quick-action buttons. By default **5 buttons** are created: *Home*, *Back*, *Source*, *Settings* and *Info*. Power and Wake-on-LAN are deliberately not buttons, as `media_player.turn_on/turn_off` already cover them.

Via *Integration → Options* you can pick exactly the buttons you want from **22 available ones**:

| Group | Buttons |
|---|---|
| 🏠 General | *Home*, *Back*, *Menu*, *Info*, *Guide (EPG)*, *Source*, *Settings* |
| 🧭 Navigation | *OK*, *Up*, *Down*, *Left*, *Right* |
| 🔊 Volume & channels | *Volume up*, *Volume down*, *Mute*, *Channel up*, *Channel down* |
| 🚀 App shortcuts | *Netflix*, *YouTube*, *Prime Video*, *Disney+*, *Plex* |

### Sending keys via `remote.send_command`

```yaml
service: remote.send_command
target:
  entity_id: remote.hisense_tv_remote
data:
  command: home
```

- **Multiple keys:** `command: ["1", "2"]` or `"back, ok"`
- **Pacing:** the `command_delay` option or `delay_secs`
- **Repeat the whole sequence:** `num_repeats`

> 📋 Full overview of all keys, direct apps, color keys and digits: [`docs/REMOTE_KEYS.md`](docs/REMOTE_KEYS.md)

## 🩺 Troubleshooting

### 🔌 Setup & pairing

| Symptom | Cause / solution |
|---|---|
| **"Failed to connect"** | Power on the TV (not deep eco standby); test reachability with `telnet <TV-IP> 36669`; rule out VLAN/AP client isolation |
| **TV not found during scan** | SSDP/multicast is often blocked by mesh Wi-Fi → enter the IP manually |
| **Pairing code rejected** (`invalid_pin`) | The code expires after ~30 seconds → wait for a new one and enter it fresh |
| **No code appears on the TV** | The RemoteNOW/VIDAA app occupies the remote session → close it completely and retry |
| **Pairing fails despite correct code** | The TV may have been powered off in between → cancel, power on the TV, add the integration again |

### 📡 Runtime

| Symptom | Cause / solution |
|---|---|
| Entities `unavailable` although the TV shows a picture | The broker is only reachable in "fast" standby; check eco standby |
| Powering on via automation fails | Enable *Network Standby / Quick Start* on the TV, otherwise Wake-on-LAN is impossible |
| Volume/source sensor updates 1–2 s after a command | Intentional: values are **live TV pushes**, not optimistic guesses (see [`docs/PROTOCOL.md`](docs/PROTOCOL.md)) |
| No volume/state values | Some models only push after the first `getvolume` poll → reduce the polling interval in the options |
| Unresponsive after a TV update | A firmware update can reset the pairing → wait for the Reauth notification and re-enter the PIN |

## 🔬 Technical details

The complete reverse-engineered protocol (topics, payloads, credential derivation, pairing sequence, discovery, WOL, discrepancies with community sources) is documented in [`docs/PROTOCOL.md`](docs/PROTOCOL.md). In short:

- **Transport:** MQTT on `tcp://<TV>:36669`, user `hisenseservice`, password `multimqttservice` (static in every RemoteNOW installation)
- **Topics:** commands go to `/remoteapp/tv/<service>/<clientId>/actions/<action>`, feedback comes from `/remoteapp/mobile/broadcast/#` and `/remoteapp/mobile/<clientId>/#`
- **Volume & mute:** `changevolume` accepts plain numbers (0–100); mute is `KEY_MUTE`
- **Power on:** Wake-on-LAN magic packet, 5× every 100 ms to UDP port **33129**

## 🔖 Changelog

Release notes for every version are published on the [Releases page](https://github.com/V4n1X/ha_hisense_tv/releases).

## 🙏 Acknowledgements

The reverse-engineering community this project builds upon:

- [Krazy998/mqtt-hisensetv](https://github.com/Krazy998/mqtt-hisensetv) – first public protocol documentation
- [sehaas/ha_hisense_tv](https://github.com/sehaas/ha_hisense_tv) – Mosquitto bridge approach, PIN flow, client certificate experience
- [newAM/hisensetv_hass](https://github.com/newAM/hisensetv_hass)
- [d3nd3/Hisense-mqtt-keyfiles](https://github.com/d3nd3/Hisense-mqtt-keyfiles)

## 📄 License

MIT — see [LICENSE](LICENSE).
