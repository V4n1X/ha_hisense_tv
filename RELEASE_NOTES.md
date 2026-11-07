# Release Notes — v1.6.4

State fixes found by testing against a live TV (65A6101EE): the volume sensor
follows a volume change from Home Assistant at once, mute works reliably, and
the device page shows the real firmware version. Updating is recommended.

## 🐛 Fixes

- **Volume sensor updates at once when the volume is set from Home
  Assistant.** The TV confirms a new level within milliseconds, but the
  integration had already stored the value for the media player and dropped
  the confirmation as "no change", so the sensor waited for the next poll (up
  to the poll interval). All entities now update immediately (measured live:
  190 ms).
- **Mute no longer toggles the wrong way.** The TV never reports its mute
  state, neither on its own nor when asked. With the state unknown,
  *unmute* sent the mute toggle and muted a TV nobody had muted. The
  integration now tracks the state it switched to itself, counts unknown as
  unmuted, and shows it on the media player. Every mute toggle counts,
  whether it comes from the media player, the remote entity or a button.
- **The device shows the real firmware version.** The TV's `appversion`
  answer is a millisecond timestamp (`1794021425030`), which replaced the
  firmware version on the device page. The firmware now comes from the
  capability answer (`softwareVersion`, e.g. `V0001.01.00a.P0219`) and is
  stored with the entry, so it stays correct while the TV is off.
- The capability answer of newer firmware names the brand `vendorBrand`; it is
  read now too.

## 📝 Documentation

- `docs/PROTOCOL.md`: the live findings on volume, mute, `capability` and
  `appversion`.
- README troubleshooting: what to do when the mute state drifts after using
  the TV's own remote. The outdated note that sensors update 1–2 s after a
  command is gone; volume and source changes arrive within about 100–200 ms.

## 🔖 All changes

See the [commit history](https://github.com/V4n1X/ha_hisense_tv/compare/v1.6.3...v1.6.4) for the complete list.
