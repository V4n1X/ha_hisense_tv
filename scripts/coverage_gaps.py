"""Map coverage.py missing lines to the integration's functions.

Usage:
    python scripts/coverage_gaps.py [--threshold N]

Reads the latest ``.coverage`` data file and prints, for every file that has
uncovered lines, which named functions/properties contain them. This turns
"line 449-498" noise into "the config flow's SSDP/DHCP discovery steps are
never exercised".

The output is a development aid only -- it is not a pass/fail gate. The
pass/fail gate is ``--cov-fail-under`` on the pytest run (see ci.yml).
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import sys

import coverage

REPO = Path(__file__).resolve().parents[1]
INTEGRATION = REPO / "custom_components" / "hisense_tv"


@dataclass(slots=True)
class _Scope:
    """One named function scope inside a module."""

    name: str
    lineno: int
    end_lineno: int
    kind: str  # "function", "method", "property", "class"


def _collect_scopes(module_path: Path) -> list[_Scope]:
    """Return all named scopes of a module, outermost first."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    def walk(node: ast.AST, prefix: str) -> list[_Scope]:
        scopes: list[_Scope] = []
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                deco = ""
                for dec in child.decorator_list:
                    if isinstance(dec, ast.Attribute) and dec.attr == "setter":
                        deco = "setter/"
                    elif isinstance(dec, ast.Name) and dec.id == "property":
                        deco = "property/"
                    elif isinstance(dec, ast.Attribute) and dec.attr in {
                        "getter",
                        "callback",
                    }:
                        deco = f"{dec.attr}/"
                kind = "property" if deco else "method"
                scopes.append(
                    _Scope(
                        name=f"{prefix}{deco}{child.name}",
                        lineno=child.lineno,
                        end_lineno=child.end_lineno or child.lineno,
                        kind=kind,
                    )
                )
                scopes.extend(walk(child, f"{prefix}{deco}{child.name}."))
            elif isinstance(child, ast.ClassDef):
                kind = "class"
                scopes.append(
                    _Scope(
                        name=f"{prefix}{child.name}",
                        lineno=child.lineno,
                        end_lineno=child.end_lineno or child.lineno,
                        kind=kind,
                    )
                )
                scopes.extend(walk(child, f"{prefix}{child.name}."))
        return scopes

    return walk(tree, "")


def _bucket_missing(
    missing: set[int], scopes: list[_Scope]
) -> tuple[list[tuple[int, int, str]], set[int]]:
    """Assign missing lines to scopes; return (scope hits, leftovers)."""
    hits: list[tuple[int, int, str]] = []
    leftovers: set[int] = set(missing)
    for scope in scopes:
        inside = {ln for ln in leftovers if scope.lineno <= ln <= scope.end_lineno}
        if inside:
            hits.append((min(inside), max(inside), scope.name))
            leftovers -= inside
    return hits, leftovers


def main() -> int:
    """Print the per-function gap report; exit 0 always (dev aid)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    cov = coverage.Coverage(data_file=REPO / ".coverage")
    cov.load()
    data = cov.get_data()
    files = data.measured_files()
    if not files:
        print(
            "No coverage data found. Run:  python -m pytest tests --cov",
            file=sys.stderr,
        )
        # Informational only: an earlier failing step must not be reported twice.
        return 0

    total_missing = 0
    for measured in sorted(files):
        path = Path(measured)
        if (
            INTEGRATION.name not in path.parts
            or INTEGRATION.parent.name not in path.parts
        ):
            continue
        rel = path.relative_to(REPO)
        # analysis2 -> (filename, statements, excluded, missing, formatted)
        _fname, _stmts, _excluded, missing, _formatted = cov.analysis2(measured)
        print(f"\n=== {rel} ===")
        total_missing += len(missing)

        scopes = _collect_scopes(INTEGRATION / path.name)
        hits, leftovers = _bucket_missing(missing, scopes)
        for _start, end, name in sorted(hits, key=lambda h: h[0]):
            print(f"    lines {end:>4}+  {name}")
        if leftovers:
            print(f"    (lines outside functions: {sorted(leftovers)})")

    print(
        f"\n{total_missing} uncovered lines overall. "
        "This report is informational; the CI gate is --cov-fail-under."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
