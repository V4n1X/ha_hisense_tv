# Release Notes — v1.3.3

Fix release for the media player's source select staying empty.

## 🛠 Fixed

- **Source select showed no sources:** the media player requested the TV's source list exactly once (a permanent one-shot flag). If that single request silently failed — most commonly while the TV was still waking up after the offline-setup change in 1.3.x, or during a brief connection flap — the flag was set anyway and the source list stayed empty **forever**.

  The request now retries on every coordinator refresh with a 60 second throttle, and the integration additionally requests the source list on **every reconnect** (same mechanism as the 1.3.2 capability fix). Sources now reliably appear once the TV is on and connected, without needing a restart.

## 📋 All changes

See the [commit history](https://github.com/V4n1X/ha_hisensetv/compare/v1.3.2...v1.3.3) for the complete list.
