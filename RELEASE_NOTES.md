# Release Notes — v1.3.0

This release focuses on a leaner, more configurable button experience, guided recovery when the TV forgets its pairing, and a much more robust setup path when the TV is powered off.

## ✨ New

### Button selection via options flow
- Only **5 buttons** are created by default: *Home*, *Back*, *Source*, *Settings*, *Info* (previously 12)
- Power and Wake-on-LAN buttons were removed — both are already covered by `media_player.turn_on` / `media_player.turn_off`
- 22 buttons are now selectable via a multi-select dropdown in the integration options: navigation (*OK*, *Up/Down/Left/Right*), volume/channels (*Volume ±*, *Mute*, *Channel ±*) and app shortcuts (*Netflix*, *YouTube*, *Prime Video*, *Disney+*, *Plex*)
- ⚠️ **Upgrade note:** the old *Power* and *Wake on LAN* button entities will show as "no longer provided" after updating — delete them from the device. Want them back (plus more)? Pick them in *Integration → Options*.

### "Pairing lost" repair flow
- When the TV no longer knows this Home Assistant connection (factory reset or firmware update), a repair issue now appears under *Settings → System → Repairs*
- Confirming the repair dismisses the issue and starts the PIN re-pairing flow directly

### TV may be powered off at HA start
- The "Setup error, will retry" failure when starting Home Assistant with the TV powered off is gone
- Setup now completes even when the TV is unreachable: the reconnect loop retries in the background and entities report *unavailable* until the TV answers
- **Wake-on-LAN now works even after an HA restart with the TV powered off** — previously this was impossible because the entry was stuck in retry state without entities

## 🛠 Fixed

- **Stable device identity:** the config entry `unique_id` is now based on the TV's MAC address instead of the client UUID, which changes on every re-pairing — this previously caused a **duplicate device** after Reauth
- **Proper error messages:** "TV not connected" is raised as a translated `HomeAssistantError` instead of a raw `NotConnected` exception (affects turn off, volume set, playback controls and `remote.send_command`)

## 🔧 Improved

- New shared entity base (`entity.py`): device info, unique-id helpers and WOL logic live in one place instead of being duplicated across five platform files
- Background metadata enrichment now uses `entry.async_create_background_task` (HA-managed task references)
- Translations (de/en) extended and aligned with the `exceptions` schema — errors now appear in the UI language
- `aiomqtt` requirement capped: `>=2.0.0,<3.0.0`
- Full hassfest validation passes; all modules import cleanly against Home Assistant 2026.8 with zero deprecation warnings
- **Minimum Home Assistant version raised to 2024.3**

## 📋 All changes

See the [commit history](https://github.com/V4n1X/ha_hisensetv/compare/v1.2.4...v1.3.0) for the complete list.
