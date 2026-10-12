# Release Notes — v1.5.0

Changing the TV's IP works again, already configured TVs are no longer offered as new, and power/mute commands only do what they are asked to. All fixes are covered by new tests that run the setup flows against a real Home Assistant 2026.10.

## 🐛 Fixed

- **Reconfigure (change IP) always failed.** Home Assistant rejects creating a new entry from a reconfigure flow, so saving a new address raised an error. Reconfigure and Reauth now update the existing entry in place and reload it.
- **Already configured TVs were offered again.**
  - A DHCP lease renewal of a configured TV opened a new "discovered" setup card (and crashed when SSDP found nothing), and an IP change was never applied. The integration now recognizes the TV by its MAC and moves the existing entry to the new IP silently.
  - TVs added by IP had no unique ID, so they could be added twice and SSDP kept offering them. Setup now recognizes an existing TV by MAC or host — before you are asked for a PIN.
- **`turn_on` switched a running TV off** (`KEY_POWER` is a toggle). The power key is now only sent to a TV in fake sleep; an unreachable TV is woken via Wake-on-LAN. `turn_off` on a TV that is already off does nothing instead of raising an error, and `remote.turn_off` — previously missing — works.
- **`media_player.volume_mute` ignored the requested state:** `mute: true` on a muted TV unmuted it. The toggle is now only sent when the TV reports the other state.
- **`remote.send_command` ignored `num_repeats`.**
- **Pairing could time out with the correct PIN** when the TV pushed more than 64 messages while the PIN dialog was open.
- **Closing the PIN dialog left a connection to the TV open** (with its reconnect loop) until Home Assistant restarted.
- **The state lagged up to one poll interval** after the TV went offline or came back; entities now update immediately.
- **Duplicate device** when a TV added by IP later revealed its MAC address — the existing device is now moved to the new identity.
- Smaller fixes: the firmware version shows up on the device card as soon as the TV reports it; a failed unload no longer cuts the connection; an invalid stored MAC no longer blocks Wake-on-LAN on the other MAC; commands to an offline TV report the translated "TV not connected" error, and an unknown source name raises a clear validation error.

## 🔄 Changed

- **"Pairing lost" now uses Home Assistant's built-in reauth notification.** After a TV reset or firmware update you still get a repair notice under *Settings → System → Repairs* that leads into PIN re-pairing — it is now Home Assistant's own. The previous custom notice was shared by all TVs (re-pairing one TV dismissed another TV's notice) and its button could open a second pairing dialog.
- The TV's hardware `device_id` is redacted in diagnostics downloads.

## 🛠️ Under the hood

- **Tests against a real Home Assistant core:** config flows run through Home Assistant's own flow manager, plus entity behaviour and entry setup. Test coverage with Home Assistant installed rose from 45 % to 72 %.
- Validation schemas use `probatio`, Home Assistant's validation library since 2026.9 (`voluptuous` is only an alias there).

## 📋 All changes

See the [commit history](https://github.com/V4n1X/ha_hisense_tv/compare/v1.4.0...v1.5.0) for the complete list.
