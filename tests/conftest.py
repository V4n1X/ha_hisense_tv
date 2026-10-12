"""Test bootstrap.

Makes ``hisense_tv`` importable. When the real Home Assistant package is
installed (CI), it is used as-is so a full-import smoke test can run against
genuine HA APIs. Without it (local dev), minimal stand-ins for the few names
used at import time keep protocol-level unit tests runnable.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components"))


def _register(name: str, **attrs: object) -> types.ModuleType:
    """Create or patch a stub module (and its parent chain) in sys.modules."""
    parts = name.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        mod = sys.modules.get(parent)
        if mod is None:
            mod = types.ModuleType(parent)
            sys.modules[parent] = mod
        # Mark every level as a (namespace) package so submodule imports work.
        mod.__path__ = getattr(mod, "__path__", [])  # type: ignore[attr-defined]

    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
        if len(parts) > 1:
            parent_mod = sys.modules[".".join(parts[:-1])]
            setattr(parent_mod, parts[-1], module)
    module.__path__ = getattr(module, "__path__", [])  # type: ignore[attr-defined]
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _install_stubs() -> None:
    """Minimal homeassistant stand-ins (local dev without the HA package)."""
    if importlib.util.find_spec("probatio") is None:
        vol_mod = _register("probatio")

        class _Schema:
            def __init__(self, schema: object = None, **kwargs: object) -> None:
                self.schema = schema

            def __call__(self, val: object) -> object:
                return val

        vol_mod.Schema = _Schema
        vol_mod.Required = lambda k, **kw: k
        vol_mod.Optional = lambda k, **kw: k
        vol_mod.In = lambda container: container
        vol_mod.All = lambda *validators: validators[0] if validators else None
        vol_mod.Coerce = lambda t: t
        vol_mod.Range = lambda **kw: None

    ha_stub = _register("homeassistant")
    ha_stub.__hisense_test_stub__ = True  # type: ignore[attr-defined]

    class _Platform:
        MEDIA_PLAYER = "media_player"
        REMOTE = "remote"
        SENSOR = "sensor"
        BUTTON = "button"

    class _ButtonEntity:
        pass

    @dataclass(frozen=True, kw_only=True)
    class _ButtonEntityDescription:
        key: str
        translation_key: str | None = None
        icon: str | None = None

    _register(
        "homeassistant.components.button",
        ButtonEntity=_ButtonEntity,
        ButtonEntityDescription=_ButtonEntityDescription,
        ButtonDeviceClass=type("ButtonDeviceClass", (), {}),
    )

    _register(
        "homeassistant.const",
        Platform=_Platform,
        CONF_HOST="host",
        CONF_PORT="port",
        CONF_NAME="name",
    )

    class _DeviceInfo(dict):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)

    class _DeviceRegistry:
        def async_get_or_create(self, **kwargs: object) -> object:
            return object()

        def async_get_device_by_identifier(
            self, _identifier: object, _entry_id: object
        ) -> None:
            return None

        def async_update_device(self, *_args: object, **_kwargs: object) -> None:
            return None

    dr = _register(
        "homeassistant.helpers.device_registry",
        DeviceInfo=_DeviceInfo,
        CONNECTION_NETWORK_MAC="mac",
    )
    dr.async_get = lambda _hass: _DeviceRegistry()  # type: ignore[attr-defined]
    dr.async_entries_for_config_entry = lambda _registry, _entry_id: []  # type: ignore[attr-defined]

    def _callback(fn):
        return fn

    _register(
        "homeassistant.core",
        HomeAssistant=type("HomeAssistant", (), {}),
        callback=_callback,
    )

    _register(
        "homeassistant.exceptions",
        ConfigEntryNotReady=type("ConfigEntryNotReady", (Exception,), {}),
        HomeAssistantError=type(
            "HomeAssistantError",
            (Exception,),
            {
                "__init__": lambda self, *args, **kwargs: super().__init__(*args),
            },
        ),
    )

    class _DataUpdateCoordinator:  # pragma: no cover - runtime shim
        hass = None
        last_update_success = True

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.hass = args[0] if args else None

        def __class_getitem__(cls, _item: object) -> type:  # Generic[T] support
            return cls

        def async_add_listener(self, *_a: object, **_k: object):
            return lambda: None

        async def async_request_refresh(self) -> None:
            return None

    class _CoordinatorEntity:
        def __init__(self, coordinator: type) -> None:
            self.coordinator = coordinator

        available = True

        def async_write_ha_state(self) -> None:
            return None

    _register(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_DataUpdateCoordinator,
        CoordinatorEntity=_CoordinatorEntity,
    )

    class _SelectSelectorConfig:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class _SelectSelector:
        def __init__(self, config: object) -> None:
            self.config = config

    _register(
        "homeassistant.helpers.selector",
        SelectOptionDict=lambda **kw: kw,
        SelectSelectorConfig=_SelectSelectorConfig,
        SelectSelector=_SelectSelector,
        SelectSelectorMode=type("SelectSelectorMode", (), {"DROPDOWN": "dropdown"}),
    )

    class _ConfigFlow:
        def __init_subclass__(cls, **kwargs: object) -> None:
            super().__init_subclass__()

        def async_show_form(self, **kwargs: object) -> dict:
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs: object) -> dict:
            return {"type": "create_entry", **kwargs}

        def async_abort(self, **kwargs: object) -> dict:
            return {"type": "abort", **kwargs}

    class _OptionsFlowWithReload:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class _ConfigEntryState:
        LOADED = "loaded"
        SETUP_RETRY = "setup_retry"

    _register(
        "homeassistant.config_entries",
        ConfigEntry=type("ConfigEntry", (), {"entry_id": "test-entry"}),
        ConfigEntryState=_ConfigEntryState,
        ConfigFlowResult=dict,
        ConfigFlow=_ConfigFlow,
        OptionsFlowWithReload=_OptionsFlowWithReload,
        SOURCE_REAUTH="reauth",
        SOURCE_RECONFIGURE="reconfigure",
        SOURCE_USER="user",
    )

    _register(
        "homeassistant.data_entry_flow",
        AbortFlow=type("AbortFlow", (Exception,), {}),
    )


# CI parity switch: force the stub mode even when the real Home Assistant
# package is installed locally, so "Run unit tests (no Home Assistant required)"
# can be reproduced byte-for-byte before pushing:
#   HISENSE_TEST_FORCE_STUBS=1 python -m pytest tests --ignore=tests/test_ha_smoke.py
HAS_REAL_HA = (
    importlib.util.find_spec("homeassistant") is not None
    and os.environ.get("HISENSE_TEST_FORCE_STUBS") != "1"
)

if not HAS_REAL_HA:
    _install_stubs()


# ---------------------------------------------------------------------------
# Real Home Assistant harness
# ---------------------------------------------------------------------------
#
# pytest-homeassistant-custom-component cannot be used: it imports
# homeassistant.runner, which needs the POSIX-only ``fcntl`` module, so it
# breaks every test run on Windows. This boots the same minimal core the
# deprecation canary uses (config entries, loader, registries) - enough to
# drive real config flows and entities, without HTTP/auth.

if HAS_REAL_HA:
    import pytest
    import pytest_asyncio

    # HA's loader imports the integration as ``custom_components.hisense_tv``.
    # That is a different module object than the ``hisense_tv`` the unit tests
    # import, so real-HA tests must patch names in the ``custom_components``
    # copy (see the ``ha_integration`` fixture).
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    @pytest_asyncio.fixture
    async def hass(tmp_path):
        """A minimal, real Home Assistant instance for flow/entity tests."""
        from homeassistant import config_entries, core, loader
        from homeassistant.helpers import (
            device_registry as dr,
            entity_registry as er,
            frame,
            issue_registry as ir,
            translation,
        )

        instance = core.HomeAssistant(str(tmp_path))
        instance.config.skip_pip = True
        instance.config_entries = config_entries.ConfigEntries(instance, {})
        loader.async_setup(instance)
        frame.async_setup(instance)
        translation.async_setup(instance)
        dr.async_setup(instance)
        await dr.async_load(instance)
        await er.async_load(instance)
        await ir.async_load(instance)
        await instance.async_start()
        yield instance
        await instance.async_stop(force=True)

    @pytest.fixture
    def ha_integration():
        """The integration package exactly as Home Assistant loads it."""
        import importlib

        return importlib.import_module("custom_components.hisense_tv")
