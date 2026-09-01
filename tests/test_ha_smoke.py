"""Full-import smoke test against a real Home Assistant installation.

Skipped locally (no homeassistant package); runs in CI where the workflow
installs Home Assistant. Catches broken HA API usage at import time in every
integration module, which the stub-based unit tests cannot.
"""

from __future__ import annotations

import importlib
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
    for module_name in MODULES:
        assert importlib.import_module(module_name) is not None, module_name


def test_platforms_declared_in_init() -> None:
    init = importlib.import_module("hisense_tv")
    platforms = [str(p) for p in init.PLATFORMS]
    assert "media_player" in platforms
    assert "remote" in platforms
    assert "sensor" in platforms
    assert "button" in platforms


def test_bundled_client_certificate_is_shipped() -> None:
    init = importlib.import_module("hisense_tv")
    cert = init.bundled_client_cert()
    assert cert is not None and cert.is_file()
