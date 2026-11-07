# Release Notes — v1.6.5

The media player now shows the TV's real mute state, including a mute from the
TV's own remote. Updating is recommended.

## ✨ Mute state from the TV

- **The mute state is read from the TV.** MQTT never carries it, but the TV's
  DLNA renderer does: its `RenderingControl` service answers `GetMute` with the
  real state, for a mute from Home Assistant and from the TV's own remote alike
  (verified live on a 65A6101EE). The RemoteNOW app reads it the same way.
- **When it updates:** with every poll (the polling interval in the options),
  and about one second after a mute from Home Assistant. The TV sends no DLNA
  events for mute changes, so a mute from the TV's remote shows up with the
  next poll.
- The renderer's address comes from Home Assistant's SSDP cache, with the fixed
  address of Hisense's DLNA stack as the fallback. If the renderer cannot be
  reached, the integration keeps tracking the mute toggles it sends itself, as
  in v1.6.4.

## 📝 Documentation

- `docs/PROTOCOL.md` documents the DLNA renderer and the missing events.
- The README troubleshooting entry on mute now explains the poll-based update.

## 🔖 All changes

See the [commit history](https://github.com/V4n1X/ha_hisense_tv/compare/v1.6.4...v1.6.5) for the complete list.
