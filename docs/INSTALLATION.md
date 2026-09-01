# Installation & Setup — Step by Step

This guide covers installing the Hisense TV integration via HACS and the
first pairing on the TV (including PIN entry). The flow is a 1:1 replica of
the official RemoteNOW app's first-time connection.

---

## Part 1 — Check prerequisites

| # | Prerequisite | How to check |
|---|---|---|
| 1 | Home Assistant ≥ 2024.3 running | *Settings → About* |
| 2 | **HACS** is installed | *HACS* appears in the sidebar. If not: [hacs.xyz](https://hacs.xyz/docs/setup/download) |
| 3 | TV and HA are on the **same network/subnet** | TV menu → network status (note the IP!) |
| 4 | TV is **powered on** (not eco standby) | Picture visible |
| 5 | The RemoteNOW phone app can control the TV | Confirms the TV's MQTT service is active |

> 💡 Note down the TV's IP (e.g. `192.168.1.50`) — it lets you skip the
> network scan in the setup in case SSDP is blocked in your network
> (VLAN/AP isolation).

---

## Part 2 — Install via HACS

1. In Home Assistant, open **HACS** in the sidebar.
2. Click the **three dots (⋮)** in the bottom right → **Add custom repository**.
3. Enter the following:
   - **Repository:** `https://github.com/V4n1X/ha_hisense_tv`
   - **Category:** `Integration`
4. Confirm with **Add**. The repository then appears in HACS.
5. Search HACS for **"Hisense TV"** (or open the new repository) and click **Download**.
6. Confirm the "restart required" message: **Settings → System → Restart**.

<details>
<summary>Alternative: Manual installation</summary>

```bash
cd <config-directory>
git clone https://github.com/V4n1X/ha_hisense_tv /tmp/ha_hisense_tv
mkdir -p custom_components
cp -r /tmp/ha_hisense_tv/custom_components/hisense_tv custom_components/
rm -rf /tmp/ha_hisense_tv
```
Then restart Home Assistant. (Do not use in parallel with the HACS variant.)
</details>

> ⚠️ **Removed a previous hisense_tv integration?** This integration uses the
> same name (`hisense_tv`) as e.g. `sehaas/ha_hisense_tv`. If another version
> is already installed, uninstall it first (HACS → remove and delete the
> `custom_components/hisense_tv` folder), otherwise there will be conflicts.

---

## Part 3 — Prepare the TV

So that powering on via automations works later and the broker is reachable,
these TV settings are recommended (menu paths vary by model):

| # | Setting | Where |
|---|---|---|
| 1 | Enable **Network Standby / Quick Start** | *Settings → System → Power* |
| 2 | Firmly connect WLAN **or** LAN (both work; the MAC is captured per interface) | *Settings → Network* |
| 3 | Allow remote control by apps (if your TV offers such an option) | *Settings → System → …* |

The TV's MQTT service listens on port **36669** by default.

---

## Part 4 — Set up the integration

1. **Settings → Devices & Services**
2. **Add Integration** in the bottom right
3. Search for and select **"Hisense TV"**
4. In the dialog that appears:
   - **Variant A (recommended):** leave the *Host/IP* field **empty** → the integration scans the network via SSDP → in the next step select the discovered TV from the list
   - **Variant B:** enter the IP directly (*Host*) and leave the port unchanged (**36669**)
5. The connection is now validated:
   - Establishing the MQTT connection to the TV (on newer firmware generations automatically with encrypted TLS incl. the bundled client certificate)
   - Test query of the TV state

### If the TV requests authorization → **PIN pairing**

On more recent firmware versions the TV shows a **4-digit code on screen**
when it sees an unknown client for the first time (exactly like the first
setup of the phone app):

1. 📺 The TV shows: *pairing code* (four digits)
2. 🖥️ The **"Pair with your TV"** window appears automatically in Home Assistant
3. ⌨️ Enter the four digits **while they are still valid** (the code expires
   on the TV after a short time — if it fails, simply wait until the TV shows
   a new one, or cancel and start again)
4. ✅ On success the window closes and the setup is complete

> ⚠️ **Important for smooth pairing** (verified live on the device):
>
> * **Close the official RemoteNOW/VIDAA app first** — the TV only allows
>   *one* active client. If the phone app is still connected, the TV shows a
>   pairing window in HA but **no code**; it only reports that the connected
>   device slot is busy.
> * The code is **only valid for about 30 seconds**, after which the TV closes
>   the dialog itself. The integration automatically requests a new code on
>   the next attempt.
> * System overlays (e.g. the shutdown countdown in eco mode) can **obscure**
>   the code — dismiss them briefly with the remote.

**Error messages in the pairing window:**

| Message | Meaning | Solution |
|---|---|---|
| *The entered pairing code was rejected by the TV* | Code wrong or expired | Wait for a new code and enter it fresh |
| *No response from the TV* | Timeout during validation | Try again; don't power off the TV in the meantime |
| No PIN window, setup closes directly | Older firmware without pairing requirement | All good — no pairing needed |
| No code appears on the TV at all | Remote slot busy (phone app running) or an overlay hides it | Close the app / dismiss the overlay and restart the setup |

5. Afterwards the integration creates the device in the **device registry**:
   manufacturer *Hisense*, model, firmware version and MAC address are
   filled in automatically.

---

## Part 5 — Verify it works

After setup the following entities exist (example name "Living Room TV"):

| Entity | Purpose |
|---|---|
| `media_player.living_room_tv` | On/Off, volume, mute, source, play/pause |
| `remote.living_room_tv_remote` | All remote keys |
| `sensor.living_room_tv_volume` | Volume in % |
| `sensor.living_room_tv_source` | Active input source |
| `sensor.living_room_tv_status` | Raw TV state (diagnostic) |
| `button.living_room_tv_*` | Quick-action keys (default: Home, Back, Source, Settings, Info — configurable in the options) |

> ℹ️ **Availability = TV is running.** The MQTT broker lives inside the TV
> itself — when the device is off there is technically nothing to query.
> That's why all entities of this integration go to **`unavailable`** as soon
> as the TV is off, instead of reporting a fake state ("off"). Powering on is
> done exclusively via **Wake-on-LAN** (see below) — and thanks to the
> offline-capable setup this also works right after an HA restart.

**Quick test in Developer Tools → Actions:**

```yaml
action: remote.send_command
target:
  entity_id: remote.living_room_tv_remote
data:
  command: volume_up
```

The volume should change on the TV. For a full volume test:

```yaml
action: media_player.volume_set
target:
  entity_id: media_player.living_room_tv
data:
  volume_level: 0.3
```

---

## Part 6 — Adjust options (optional)

*Settings → Devices & Services → Hisense TV → ⚙️ Options* (via the three dots):

| Option | Default | Purpose |
|---|---|---|
| Poll interval | 30 s | State refresh; use a smaller value (10–15 s) if values arrive late |
| Wake-on-LAN | on | Power on via magic packet instead of the power key (powering on is **only** possible via WOL) |
| Command delay | 30 ms | Pacing for command chains (`command: "back, ok"`) |
| Button selection | 5 buttons | Multi-select from 22 available quick-action buttons |

**Powering on via WOL — alternative with built-in tools:** The integration
sends the magic packet itself (`media_player.turn_on` or `remote.turn_on`,
the MAC is captured automatically during SSDP discovery). You can equally use
Home Assistant's **native `wake_on_lan` integration**: *Settings → Devices &
Services → Add Integration → Wake-on-LAN*, then create a switch with the TV's
MAC (the MAC is in the state sensor's entity attributes and in the
diagnostics download). Both work for `turn_on` actions in automations.

**IP address changed?** No need to set up again: the integration recognizes
the TV by its MAC (Reconfirm) — or you change the address manually via
*Configure* (Reconfigure).

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| "Failed to connect" during setup | TV in deep standby, VLAN separation, firewall | Power on the TV; test port 36669/TCP from the HA host (`telnet <tv-ip> 36669`); disable AP client isolation |
| TV not found during scan | SSDP/multicast blocked (common with mesh/WLAN bridges) | Use variant B with a manual IP |
| Entities permanently `unavailable` | TV in deep standby → broker off | This is the OFF state; ignore "availability" in automations or enable network standby |
| No volume/state values | Some models only push after a poll | Lower the poll interval to 10–15 s |
| PIN window never appears | Old firmware without pairing requirement | Normal — the setup closes automatically |

Questions about the protocol behind it? → [`PROTOCOL.md`](PROTOCOL.md)
