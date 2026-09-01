# Release Notes — v1.3.2

Fix release for device metadata that went missing after the 1.3.x offline-setup change.

## 🛠 Fixed

- **Hardware info missing on the device card** (`hw_version`): since 1.3.0 setup completes even when the TV is powered off — but the capability request that fills `chip_platform` / `hw_version` only ran during setup while the TV was connected. Starting Home Assistant with the TV off meant the metadata was never requested and the hardware line stayed empty. The integration now re-requests **capability and app version on every reconnect** (throttled to once per minute), so hardware/firmware metadata populates regardless of the TV's state at HA start.
- **SSDP enrichment backfills more metadata**: chip `platform` and `transport_protocol` are now written into the config entry when missing, so `hw_version` ("platform …") can be shown even without a capability push.

## 📋 All changes

See the [commit history](https://github.com/V4n1X/ha_hisensetv/compare/v1.3.1...v1.3.2) for the complete list.
