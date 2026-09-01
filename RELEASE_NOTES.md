# Release Notes — v1.3.4

New feature: the TV's installed apps are now available in the media player's source selector.

## ✨ New

- **Launch installed apps from the source selector:** the media player's `source_list` now combines the HDMI/TV inputs **and the apps installed on the TV** (Netflix, YouTube, Prime Video, …). Selecting an app in the "Source" picker — or via `media_player.select_source` in automations — launches it on the TV using the protocol's `launchapp` action.

### How it works

- The app list is **actively requested** from the TV on every (re)connect, using the same request the official RemoteNOW app performs in its connect burst — so it reflects the actually installed apps, not a static guess.
- Same robust mechanics as the source list (v1.3.3): throttled retries until the list arrives, case-insensitive dedupe, and defensive parsing of firmware-specific JSON variants (several key spellings, wrapped payloads, plain strings). If a TV does not report an app list, inputs keep working unchanged.
- Selecting an HDMI input still switches the input; app names launch apps — both live side by side in the same selector.

## 📋 All changes

See the [commit history](https://github.com/V4n1X/ha_hisensetv/compare/v1.3.3...v1.3.4) for the complete list.
