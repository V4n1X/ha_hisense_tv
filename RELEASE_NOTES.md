# Release Notes — v1.6.2

Documentation-only patch: the README now renders cleanly on the HACS repository
page. There are no functional changes to the integration itself — updating is
optional.

## 📝 Documentation

- **No more raw HTML on the HACS repository page.** That page renders the README
  with the Home Assistant markdown renderer, which passes only a small set of
  HTML through — everything else appeared as literal text. The `<div>`,
  `<details>`/`<summary>`, `<b>` tags and the `align`/`width` attributes are
  gone: the logo and the three badges are ordinary markdown images and links,
  the collapsible *Without the button* and *Manual installation* sections are
  headings, and the GitHub alert markers (`[!IMPORTANT]`, `[!TIP]`,
  `[!WARNING]`) are now bold labels that every renderer displays.
- **New test** (`tests/test_docs.py::test_readme_uses_only_renderer_safe_html`)
  fails when the README reintroduces a tag or attribute the renderer cannot
  show. Angle brackets that sit inside inline code or code blocks — such as
  `<config>` in the install snippet — are literal text and stay allowed.

## 🔖 All changes

See the [commit history](https://github.com/V4n1X/ha_hisense_tv/compare/v1.6.1...v1.6.2) for the complete list.
