"""Repo-wide encoding sanity gate.

Runs the same checks as ``scripts/check_encoding.py`` inside the normal
pytest run, so corrupted encodings (stored U+FFFD, control characters such
as the stray 0x1A once shipped in docs/PROTOCOL.md, invalid UTF-8) fail
every CI build and local test run.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_encoding import check_files


def test_no_encoding_corruption() -> None:
    """Fail when any tracked file carries encoding corruption."""
    findings = check_files()
    assert not findings, "encoding problems found:\n" + "\n".join(
        f"  - {f}" for f in findings
    )
