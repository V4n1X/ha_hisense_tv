"""Full-import smoke test against a real Home Assistant installation.

Skipped locally (no homeassistant package); runs in CI where the workflow
installs Home Assistant. Catches broken HA API usage at import time in every
integration module, which the stub-based unit tests cannot.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest

ha_module = sys.modules.get("homeassistant")
if getattr(ha_module, "__hisense_test_stub__", False):
    # conftest installed its minimal stand-ins (no real HA available).
    pytest.skip("real Home Assistant package not installed", allow_module_level=True)

MODULES = [
    "hisense_tv",
    "hisense_tv.const",
    "hisense_tv.models",
    "hisense_tv.discovery",
    "hisense_tv.data",
    "hisense_tv.entity",
    "hisense_tv.coordinator",
    "hisense_tv.config_flow",
    "hisense_tv.repairs",
    "hisense_tv.button",
    "hisense_tv.media_player",
    "hisense_tv.remote",
    "hisense_tv.sensor",
    "hisense_tv.diagnostics",
]


def test_all_modules_import_with_real_homeassistant() -> None:
    """Every integration module must import against the installed HA release."""
    for module_name in MODULES:
        assert importlib.import_module(module_name) is not None, module_name


def test_platforms_declared_in_init() -> None:
    """All shipped platforms must be listed in PLATFORMS."""
    init = importlib.import_module("hisense_tv")
    platforms = [str(p) for p in init.PLATFORMS]
    assert "media_player" in platforms
    assert "remote" in platforms
    assert "sensor" in platforms
    assert "button" in platforms


def test_bundled_client_certificate_is_shipped() -> None:
    """The mTLS client certificate must exist in the package."""
    init = importlib.import_module("hisense_tv")
    cert = init.bundled_client_cert()
    assert cert is not None and cert.is_file()


def test_setup_triggers_no_ha_deprecation_warnings(tmp_path) -> None:
    """Full runtime setup must not raise any HA deprecation reports.

    Runs scripts/deprecation_canary.py as a subprocess: it boots a minimal
    real Home Assistant, sets up the integration from a temporary config dir
    and counts every report HA itself raises for it (deprecated API usage
    via helpers.frame.report_usage and blocking calls in the event loop).

    A subprocess is deliberate: HA's blocking-call detection monkey-patches
    stdlib functions process-wide and cannot be disabled again.
    """
    import os
    import subprocess

    script = Path(__file__).resolve().parents[1] / "scripts" / "deprecation_canary.py"
    env = os.environ.copy()
    # Keep the subprocess out of pytest's own machinery.
    env.pop("PYTEST_CURRENT_TEST", None)

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        check=False,
    )

    verdict = ""
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("HISENSE_TV_DEPRECATION_CANARY_VERDICT="):
            verdict = line.split("=", 1)[1].split()[0]
            break

    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    assert verdict == "CLEAN", (
        f"deprecation canary verdict={verdict or 'NONE'} rc={result.returncode}; "
        "Home Assistant raised deprecation/blocking-call reports for the "
        "integration setup - see the log output above"
    )
