# Release Notes — v1.6.3

Power state fix: a TV switched off with its own remote now shows as off in Home
Assistant immediately instead of after up to 90 seconds. The release also goes
through the Home Assistant 2026.11 developer changes and fixes a blocking call
Home Assistant reported at startup. Updating is recommended.

## 🐛 Fixes

- **The TV is off the moment it is switched off.** The TV broadcasts
  `platform_service/actions/tvsleep` when it powers down, but keeps the MQTT
  connection open for about another minute without answering anything. The
  integration waited for that connection to drop, so the media player stayed
  *on* for 65–90 seconds. It now reacts to the broadcast: media player and
  remote switch to *off* right away (measured live: 1 ms). If the TV answers
  again before the connection drops, it counts as on again.
- **Faster fallback for TVs that do not send `tvsleep`.** The MQTT keepalive is
  10 s instead of the app's 45 s, so a silently vanished TV is detected within
  20 s instead of 90 s.
- **Fake sleep shows as off.** A TV in fake sleep (screen off, broker still
  running) was reported as *on*, although turning it on and off already
  treated it as off. Media player and remote now report *off*.
- **Switching on is picked up sooner.** While the TV is off, the integration
  retries the connection at least every 10 s (was 60 s), and right after a
  Wake-on-LAN packet it retries immediately.
- **No more "Detected blocking call … inside the event loop" warning.** The
  MQTT library was imported on the first connection attempt, inside the event
  loop, where its import reads package metadata from disk. It is now imported
  with the module.
- `turn_on` during the minute after `tvsleep` sends Wake-on-LAN instead of the
  power key, which the TV no longer accepts at that point.

## ✨ Home Assistant 2026.11

- **Integration category** `media_entertainment.tv_streaming` in the manifest,
  so the Marketplace and the integrations page list it under *TV & streaming*.
- **Icons come from `icons.json`** (icon translations) instead of being
  hard-coded. The volume sensor icon now follows the level: muted, low,
  medium, high.
- The source-list request runs as a background task of the config entry, so an
  unload cancels it.

## 🛠️ Under the hood

- `docs/PROTOCOL.md` documents the live-verified `tvsleep` broadcast and the
  shorter keepalive.
- The real-Home-Assistant test harness and the deprecation canary initialize
  the config entries before loading the entity registry, which Home Assistant
  2026.11 waits for.
- New tests for the `tvsleep` handling, fake sleep, the reconnect after
  Wake-on-LAN and the icon translations.

## 🔖 All changes

See the [commit history](https://github.com/V4n1X/ha_hisense_tv/compare/v1.6.2...v1.6.3) for the complete list.
