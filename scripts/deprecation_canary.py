#!/usr/bin/env python
"""Runtime deprecation canary for the Hisense TV custom integration.

Boots a *real* Home Assistant (minimal bootstrap, no HTTP/supervisor) in a
temporary config directory, registers ``custom_components`` so HA's loader
discovers the integration, adds a config entry and lets the full setup run
(component setup, entry setup, device registry, all entity platforms).

While everything runs, it counts every deprecation report Home Assistant
itself raises *for this integration*, i.e. every message coming from
``homeassistant.helpers.frame.report_usage`` ("Detected that custom
integration 'hisense_tv' ...") or the blocking-call detector in
``homeassistant.util.loop`` ("Detected blocking call ... integration
'hisense_tv' ..."). These reports are how HA announces deprecated API usage
and unsafe blocking calls from custom integrations before they break in a
future release.

Exit codes:
    0  clean (or SKIP when aiomqtt is unavailable)
    1  HA raised one or more deprecation / blocking-call reports
    2  component setup failed
    3  config entry did not reach LOADED state (a blocking-call RuntimeError
       inside async_setup_entry also lands here, with the offender in the log)
    4  self-test failed: an injected deprecation report was NOT detected -
       the message patterns in this script have drifted from HA's formats
    5  the injected capability push feedback (which patches the registry
       device) raised, e.g. because a device registry API no longer exists

Run directly (needs the ``homeassistant`` package installed):

    python scripts/deprecation_canary.py

Or through the pytest wrapper in tests/test_ha_smoke.py, which CI runs in the
job that installs real Home Assistant.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import logging
from pathlib import Path
import re
import shutil
import sys
import threading

REPO_ROOT = Path(__file__).resolve().parents[1]

# --- in-process report counter (attached before HA boots) -------------------

DEPRECATION_PATTERNS = (
    # homeassistant.helpers.frame.report_usage, both attribution paths:
    #   "Detected that custom integration 'hisense_tv' calls a deprecated ..."
    #   "Detected that integration 'hisense_tv' calls a deprecated ..."
    re.compile(r"Detected that (?:custom )?integration 'hisense_tv'"),
    # homeassistant.util.loop.raise_for_blocking_call:
    #   "Detected blocking call ... inside the event loop by
    #    custom integration 'hisense_tv' ..."
    re.compile(r"Detected blocking call[\s\S]*?integration 'hisense_tv'"),
)


class _ReportCounter(logging.Handler):
    """Count log records matching any deprecation report pattern."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.hits: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if any(pattern.search(message) for pattern in DEPRECATION_PATTERNS):
            self.hits.append(message)


async def main(config_dir: str) -> int:
    """Boot minimal HA, run the integration setup and evaluate the verdict."""
    if importlib.util.find_spec("aiomqtt") is None:
        print("HISENSE_TV_DEPRECATION_CANARY_VERDICT=SKIP (aiomqtt not installed)")
        return 0

    # Make HA's custom-component loader discover us: it imports the
    # ``custom_components`` package from sys.path (loader._get_custom_components).
    parent = str(REPO_ROOT)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    from homeassistant import (  # noqa: PLC0415
        block_async_io,
        config_entries,
        core,
        loader,
    )
    from homeassistant.auth import auth_manager_from_config  # noqa: PLC0415
    from homeassistant.bootstrap import (  # noqa: PLC0415
        _init_blocking_io_modules_in_executor,
    )
    from homeassistant.const import __version__ as ha_version  # noqa: PLC0415
    from homeassistant.helpers import (  # noqa: PLC0415
        device_registry as dr,
        entity_registry as er,
        frame,
        issue_registry as ir,
        translation,
    )
    from homeassistant.setup import async_setup_component  # noqa: PLC0415

    def _prime_blocking_modules() -> None:
        """Run blocking module init off the loop (mirror of bootstrap)."""
        _init_blocking_io_modules_in_executor()
        # Module-level set_default_verify_paths() would otherwise run during
        # the in-loop import of websocket_api -> http -> util.ssl.
        importlib.import_module("homeassistant.util.ssl")

    counter = _ReportCounter()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    logging.getLogger().addHandler(counter)

    print(f"deprecation canary: Home Assistant {ha_version}")

    # Strict blocking-call detection (mirror bootstrap.async_setup_ha). Must
    # run on the event loop thread *before* the hass object exists so the
    # captured loop thread id is correct. No disable() exists on purpose:
    # this script runs as a one-shot subprocess.
    block_async_io.enable()

    hass = core.HomeAssistant(config_dir)
    hass.config.skip_pip = True
    # The flow manager, loader cache and translation/entity caches are wired
    # in bootstrap; the canary wires them manually because it skips the full
    # config/bootstrap pipeline.
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    loader.async_setup(hass)
    frame.async_setup(hass)
    translation.async_setup(hass)

    # Newer Home Assistant releases (verified: 2026.9+; absent in 2026.2) need
    # the device registry set up before it can be loaded, as bootstrap does.
    if hasattr(dr, "async_setup"):
        dr.async_setup(hass)

    await asyncio.gather(
        hass.async_add_executor_job(_prime_blocking_modules),
        dr.async_load(hass),
        er.async_load(hass),
        ir.async_load(hass),
    )

    # media_player depends on websocket_api -> http, which needs the auth
    # manager. Wire it the same way ``hass --script auth`` does. This must
    # happen AFTER the registry loads: auth provider initialization touches
    # the registry singletons, and their async_load asserts the key is not
    # yet present in hass.data.
    hass.auth = await auth_manager_from_config(hass, [{"type": "homeassistant"}], [])
    await hass.auth.auth_providers[0].async_initialize()

    try:
        component_ok = await async_setup_component(hass, "hisense_tv", {})
    except Exception as ex:  # noqa: BLE001
        print(f"deprecation canary: component setup raised: {ex!r}")
        await stop_hass(hass)
        print("HISENSE_TV_DEPRECATION_CANARY_VERDICT=SETUP_FAILED")
        return 2
    if not component_ok:
        print("deprecation canary: async_setup_component returned False")
        await stop_hass(hass)
        print("HISENSE_TV_DEPRECATION_CANARY_VERDICT=SETUP_FAILED")
        return 2

    entry = config_entries.ConfigEntry(
        data={
            "host": "192.0.2.111",  # TEST-NET-1: black hole, no TV answers
            "port": 36669,
            "name": "Deprecation Canary",
            "use_tls": False,
            "uuid": "deprecation-canary-client",
            "client_id": "deprecation-canary-client",
        },
        domain="hisense_tv",
        title="Deprecation Canary",
        source="user",
        unique_id="deprecation-canary",
        version=1,
        minor_version=1,
        options={},
        discovery_keys={},
        subentries_data=[],
    )
    await hass.config_entries.async_add(entry)

    # Push feedback is what patches the registry device - the only place that
    # uses the device registry lookup API. The black-hole canary TV never sends
    # any, so inject one capability message through the client's own callback
    # and let real Home Assistant execute that path under the report counter.
    feedback_error: Exception | None = None
    try:
        from custom_components.hisense_tv.const import (  # noqa: PLC0415
            DISPATCH_CAPABILITY,
        )
        from custom_components.hisense_tv.models import CapabilityInfo  # noqa: PLC0415

        capability = CapabilityInfo()
        capability.chip_platform = "canary"
        entry.runtime_data.client.on_event(DISPATCH_CAPABILITY, capability)
    except Exception as ex:  # noqa: BLE001
        feedback_error = ex

    # Give the setup-time background tasks (offline reconnect loop, SSDP
    # metadata enrichment) a moment to run - they must be deprecation clean
    # as well.
    await asyncio.sleep(3.0)

    loaded = entry.state is config_entries.ConfigEntryState.LOADED

    # Self-test: inject a genuine report through HA's own report_usage with
    # this integration's domain and verify the counter sees it. Guards
    # against silent neutralization when HA changes its message formats.
    # Uses the integration_domain path (not frame attribution), so it works
    # on every platform.
    real_hits = counter.hits[:]
    from homeassistant.helpers import frame as frame_helper  # noqa: PLC0415

    frame_helper.report_usage(
        "canary self-test (injected, not a real problem)",
        integration_domain="hisense_tv",
        breaks_in_ha_version="9999.9",
        custom_integration_behavior=frame_helper.ReportBehavior.LOG,
    )
    await asyncio.sleep(0.2)
    injection_caught = len(counter.hits) > len(real_hits)

    await stop_hass(hass)

    if not loaded:
        print(
            "deprecation canary: entry state is "
            f"{entry.state} (expected LOADED) - see setup errors above"
        )
        print("HISENSE_TV_DEPRECATION_CANARY_VERDICT=SETUP_FAILED")
        return 3

    if feedback_error is not None:
        print(
            "deprecation canary: injected capability feedback raised "
            f"{feedback_error!r} (device registry update path)"
        )
        print("HISENSE_TV_DEPRECATION_CANARY_VERDICT=FEEDBACK_FAILED")
        return 5

    if not injection_caught:
        print(
            "deprecation canary: self-test FAILED - an injected deprecation "
            "report was not detected. The DEPRECATION_PATTERNS in this script "
            "no longer match Home Assistant's report message formats and must "
            "be updated."
        )
        print("HISENSE_TV_DEPRECATION_CANARY_VERDICT=FORMAT_DRIFT")
        return 4

    # NOTE: no temp-dir cleanup in here - TemporaryDirectory.cleanup() does
    # blocking I/O and must run outside the event loop (the blocking-call
    # detector would flag the canary itself). See run() below.
    if real_hits:
        print(f"deprecation canary: {len(real_hits)} report(s) raised by HA:")
        for hit in real_hits:
            print(f"  - {hit}")
        print("HISENSE_TV_DEPRECATION_CANARY_VERDICT=REPORTED")
        return 1

    print("deprecation canary: setup is deprecation clean (self-test passed)")
    print("HISENSE_TV_DEPRECATION_CANARY_VERDICT=CLEAN")
    return 0


def run() -> int:
    """Synchronous wrapper: temp dir is managed OUTSIDE the event loop.

    Two blocking-I/O pitfalls, both of which would make HA's blocking-call
    detector flag the canary itself:

    - The temp dir is created before and removed after the event loop exists,
      never on it.
    - Removal runs on a separate thread: the detector matches by thread id,
      and this thread still matches the captured loop thread id even after
      ``asyncio.run()`` has returned.
    """
    import tempfile  # noqa: PLC0415

    config_dir = tempfile.mkdtemp(prefix="ha_deprecation_canary_")
    (Path(config_dir) / "configuration.yaml").write_text(
        "# deprecation canary: intentionally minimal config\n",
        encoding="utf-8",
    )
    try:
        return asyncio.run(main(config_dir))
    finally:
        threading.Thread(
            target=shutil.rmtree,
            args=(config_dir,),
            kwargs={"ignore_errors": True},
            name="canary-cleanup",
        ).start()


async def stop_hass(hass) -> None:
    """Shut the minimal instance down, tolerating a not-fully-started core."""
    with contextlib.suppress(Exception):
        await hass.async_stop(force=True)


if __name__ == "__main__":
    raise SystemExit(run())
