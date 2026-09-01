# Release Notes — v1.3.5

Polish release: persistent hardware info, proper sensor icons and instant source/volume feedback.

## 🛠 Fixed / improved

### Hardware info now survives HA restarts with the TV off
- The device registry already persisted `hw_version`, but it was only learned at runtime from the TV's capability push — a newly created registry device needed the TV powered on once.
- The chip platform reported via capability is now **stored in the config entry data** the first time it arrives, so `hw_version` ("chip …" / "platform …") is restored from storage on every restart, registry device recreation or entry re-import — no TV required.

### Sensor icons
- Volume, source and TV state sensors carried the generic eye icon; they now use proper icons: `mdi:volume-high`, `mdi:video-input-hdmi`, `mdi:information-outline`.

### Instant source / volume / mute feedback
- **Source select:** choosing an input or app now updates the source sensor immediately (optimistic write); the TV's `sourceswitch` push corrects it if needed — previously the sensor lagged until the next push/poll.
- **Volume up/down:** applies an optimistic single step instead of waiting 1–2 s for the TV's `volumechange` push (the push still corrects the final value).
- **Mute:** reflects the requested mute state instantly instead of waiting for the TV's feedback.

## 📋 All changes

See the [commit history](https://github.com/V4n1X/ha_hisensetv/compare/v1.3.4...v1.3.5) for the complete list.
