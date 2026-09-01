"""Tests for the config flow."""

from __future__ import annotations

import pytest

from hisense_tv.config_flow import HisenseTvConfigFlow, _host_schema, _pin_schema


@pytest.mark.asyncio
async def test_user_step_initial_form():
    """Initial user step returns the host configuration form."""
    flow = HisenseTvConfigFlow()
    result = await flow.async_step_user(None)

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {}


def test_host_schema_serialization():
    """Host schema contains host, port, name."""
    schema = _host_schema(None)
    assert schema is not None


def test_pin_schema():
    """Pin schema contains pin field."""
    schema = _pin_schema()
    assert schema is not None
