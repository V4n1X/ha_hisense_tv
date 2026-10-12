"""Documentation drift gate.

The README and ``docs/INSTALLATION.md`` spell out the selectable buttons and
their count by hand, right next to the constants that define them, and the
release version lives in two files at once. These tests fail when either copy
drifts from the code, so a button that is added, renamed or removed cannot
silently leave the docs behind.

Complements ``scripts/check_encoding.py``, which guards the encoding of the
very same files.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from hisense_tv.button import BUTTON_DESCRIPTIONS
from hisense_tv.const import DEFAULT_BUTTONS

ROOT = Path(__file__).resolve().parents[1]

# Labels as the options-flow multi-select shows them.
LABELS = {desc.label for desc in BUTTON_DESCRIPTIONS}
LABEL_BY_KEY = {desc.key: desc.label for desc in BUTTON_DESCRIPTIONS}


def _read(*parts: str) -> str:
    """Return a repo file as text."""
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _table_labels(text: str, header_cell: str) -> set[str]:
    """Return the italicised labels in the data rows of a markdown table.

    ``header_cell`` picks the table by its first header cell, for documents
    that contain several.
    """
    lines = text.splitlines()
    starts = [
        i for i, line in enumerate(lines) if line.startswith(f"| {header_cell} |")
    ]
    assert len(starts) == 1, f"expected exactly one '{header_cell}' table"
    labels: set[str] = set()
    # Skip the header row and its "---" separator.
    for line in lines[starts[0] + 2 :]:
        if not line.startswith("|"):
            break
        for cell in line.strip("|").split("|"):
            labels.update(re.findall(r"\*([^*]+)\*", cell))
    return labels


def test_readme_lists_exactly_the_selectable_buttons() -> None:
    """The README button table mirrors BUTTON_DESCRIPTIONS label for label."""
    documented = _table_labels(_read("README.md"), "Group")
    assert documented == LABELS, (
        "README.md button table is out of sync with button.py "
        f"(only in docs: {sorted(documented - LABELS)}; "
        f"missing from docs: {sorted(LABELS - documented)})"
    )


def test_readme_names_the_real_default_buttons() -> None:
    """The default set named in the README matches DEFAULT_BUTTONS, in order."""
    sentence = re.search(
        r"By default \*\*(\d+) buttons\*\* are created: ([^.]*)\.", _read("README.md")
    )
    assert sentence, "README.md no longer names the default button set"
    count, listed = sentence.groups()
    assert int(count) == len(DEFAULT_BUTTONS)
    assert re.findall(r"\*([^*]+)\*", listed) == [
        LABEL_BY_KEY[key] for key in DEFAULT_BUTTONS
    ]


def test_documented_button_count_matches_the_code() -> None:
    """Both documents quote the real number of selectable buttons."""
    total = len(BUTTON_DESCRIPTIONS)
    documents = (
        (_read("README.md"), r"from \*\*(\d+) available ones\*\*", "README.md"),
        (
            _read("docs", "INSTALLATION.md"),
            r"from (\d+) available quick-action buttons",
            "docs/INSTALLATION.md",
        ),
    )
    for text, pattern, name in documents:
        found = re.search(pattern, text)
        assert found, f"{name}: sentence with the button count is missing"
        assert int(found.group(1)) == total, (
            f"{name} says {found.group(1)} selectable buttons, "
            f"button.py defines {total}"
        )


def test_manifest_version_matches_release_notes() -> None:
    """manifest.json and RELEASE_NOTES.md announce the same version."""
    manifest = json.loads(_read("custom_components", "hisense_tv", "manifest.json"))
    heading = re.search(
        r"^#\s+Release Notes\b.*?\bv(\d+\.\d+\.\d+)\b",
        _read("RELEASE_NOTES.md"),
        re.MULTILINE,
    )
    assert heading, "RELEASE_NOTES.md has no '# Release Notes - vX.Y.Z' heading"
    assert manifest["version"] == heading.group(1), (
        f"manifest.json is {manifest['version']}, "
        f"RELEASE_NOTES.md documents {heading.group(1)}"
    )
