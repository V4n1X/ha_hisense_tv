# Release Notes — v1.3.1

Hotfix release addressing two runtime crashes and one event-loop blocking warning reported after the 1.3.0 update.

## 🛠 Fixed

- **Setup crash (`NameError: CONF_MAC_WIFI`)**: entries without stored MAC addresses crashed during setup when the background metadata enrichment kicked in — two constants were accidentally dropped from the imports during the 1.3.0 refactor. *(Only affected entries created manually by IP or where SSDP discovery stored no MAC.)*
- **App-version feedback dropped**: a missing constant import made `_handle_message` raise on every `/appversion` push, so the TV's firmware/app version never populated the device registry.
- **"Detected blocking call to load_cert_chain"**: the bundled TLS client certificate is now loaded in an executor thread instead of blocking the event loop during setup.

## 🔧 Added / improved

- **Static pyflakes gate** in CI (`undefined name` / unused-import detection) — it catches exactly the class of error behind both crashes above
- Repo-wide encoding sanity test (control characters, stored U+FFFD, invalid UTF-8 fail the build)
- CI actions updated (checkout v7, setup-python v7 — clears the Node 20 deprecation warnings)
- README header with the Hisense logo (served from the home-assistant/brands repo) and HACS/Release/CI badges
- Documentation fully in English, hassfest + HACS validation green

## 📋 All changes

See the [commit history](https://github.com/V4n1X/ha_hisensetv/compare/v1.3.0...v1.3.1) for the complete list.
