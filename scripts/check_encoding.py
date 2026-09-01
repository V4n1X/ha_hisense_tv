#!/usr/bin/env python
"""Encoding sanity check for all tracked text files.

Detects the kinds of corruption that surface as ``\ufffd`` in editors and
renderers:

- stored Unicode replacement characters (U+FFFD bytes)
- C0/C1 control characters (except tab, LF, CR) such as the stray 0x1A
  that once shipped inside docs/PROTOCOL.md
- DEL (0x7F)
- invalid UTF-8 (file is not decodable and not detected as binary)
- UTF-8 byte-order marks

Usage:
    python scripts/check_encoding.py            # check, exit 1 on findings
    python scripts/check_encoding.py --quiet    # findings only
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

REPLACEMENT_BYTES = b"\xef\xbf\xbd"
BOM = b"\xef\xbb\xbf"


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    names = out.stdout.split(b"\0")
    return [REPO_ROOT / n.decode("utf-8") for n in names if n]


def _is_binary(raw: bytes) -> bool:
    """Heuristic: a NUL byte means binary (certs, images, ...)."""
    return b"\x00" in raw


def check_files() -> list[str]:
    """Return one human-readable finding per detected problem."""
    findings: list[str] = []
    for path in _tracked_files():
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        raw = path.read_bytes()

        if REPLACEMENT_BYTES in raw:
            findings.append(f"{rel}: stored Unicode replacement character (U+FFFD bytes)")
        if raw.startswith(BOM):
            findings.append(f"{rel}: UTF-8 byte-order mark (BOM)")
        if _is_binary(raw):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as err:
            findings.append(f"{rel}: invalid UTF-8 ({err})")
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            bad = [ch for ch in line if (ord(ch) < 32 and ch not in "\t") or ord(ch) == 0x7F]
            if bad:
                shown = ", ".join(f"U+{ord(ch):04X}" for ch in bad[:3])
                findings.append(f"{rel}:{lineno}: control character(s) {shown}")
    return findings


def main() -> int:
    findings = check_files()
    if not findings:
        if "--quiet" not in sys.argv:
            print("encoding check: OK (no control characters, U+FFFD, BOMs or invalid UTF-8)")
        return 0
    print("encoding check: FAILED\n", file=sys.stderr)
    for finding in findings:
        print(f"  - {finding}", file=sys.stderr)
    print(f"\n{len(findings)} finding(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
