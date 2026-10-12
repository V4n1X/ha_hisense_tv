# Release Notes — v1.6.1

Documentation and test-only patch. Two inaccuracies in the v1.6.0 README are
corrected, and the documentation now has a test that keeps it in sync with the
code. There are no functional changes to the integration itself — updating is
optional.

## 📝 Documentation

- **The button table now uses the labels the options flow really shows.** *Guide*
  became *Guide (EPG)*, and the abbreviated *Volume ±* / *Channel ±* are spelled
  out as *Volume up*, *Volume down*, *Channel up* and *Channel down*, so every
  entry can be found by copy-pasting it into the multi-select.
- **The `sensor` row lists the TV states again** (`sourceswitch`, `app`,
  `livetv`, …) — the concrete examples dropped while the README was restructured
  are back.

## 🛠️ Under the hood

- **New documentation drift gate** (`tests/test_docs.py`). The selectable
  buttons were listed by hand in two documents while the code defines them in
  `button.py`; the release version lived in two files at once. The new tests
  fail CI when the README's button table, the quoted button counts, the default
  button set or the release version drift from their source, the same way the
  repo already guards encoding, formatting and coverage.

## 🔖 All changes

See the [commit history](https://github.com/V4n1X/ha_hisense_tv/compare/v1.6.0...v1.6.1) for the complete list.
