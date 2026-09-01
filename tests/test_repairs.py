"""Tests for the pairing-lost repair flow (issue created, resolved, deleted)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hisense_tv.const import DOMAIN
from hisense_tv.repairs import (
    ISSUE_PAIRING_LOST,
    PairingLostRepairFlow,
    async_create_fix_flow,
    async_create_pairing_lost_issue,
    async_delete_pairing_lost_issue,
)


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeEntry:
    """Minimal config-entry stand-in for the repair tests."""

    entry_id: str = "entry-1"
    title: str = "Wohnzimmer TV"
    domain: str = DOMAIN
    data: dict = None

    def __post_init__(self) -> None:
        if self.data is None:
            self.data = {"host": "1.2.3.4", "port": 36669}


class FakeIssueRegistry:
    """In-memory stand-in for the issue registry."""

    def __init__(self) -> None:
        self.issues: dict[tuple[str, str], dict] = {}

    def async_create_issue(
        self,
        hass,
        domain: str,
        issue_id: str,
        *,
        is_fixable: bool,
        severity,
        translation_key: str | None = None,
        translation_placeholders=None,
        data=None,
        **_kwargs,
    ) -> None:
        self.issues[(domain, issue_id)] = {
            "domain": domain,
            "issue_id": issue_id,
            "is_fixable": is_fixable,
            "severity": severity,
            "translation_key": translation_key,
            "translation_placeholders": translation_placeholders,
            "data": data,
        }

    def async_get_issue(self, domain: str, issue_id: str):
        item = self.issues.get((domain, issue_id))
        if item is None:
            return None
        from types import SimpleNamespace

        return SimpleNamespace(
            translation_placeholders=item["translation_placeholders"],
            translation_key=item["translation_key"],
            is_fixable=item["is_fixable"],
            data=item["data"],
        )

    # Real HA issue registry delegates these names internally.
    def async_get_or_create(
        self,
        domain: str,
        issue_id: str,
        *,
        is_fixable: bool,
        severity,
        translation_key: str | None = None,
        translation_placeholders=None,
        data=None,
        **_kwargs,
    ) -> None:
        self.issues[(domain, issue_id)] = {
            "domain": domain,
            "issue_id": issue_id,
            "is_fixable": is_fixable,
            "severity": severity,
            "translation_key": translation_key,
            "translation_placeholders": translation_placeholders,
            "data": data,
        }

    def async_delete(self, domain: str, issue_id: str) -> None:
        self.issues.pop((domain, issue_id), None)


class FakeConfigEntries:
    """Stand-in for hass.config_entries with a tiny in-memory store."""

    def __init__(self) -> None:
        self.entries: dict[str, object] = {}
        self.init_calls: list[tuple] = []

    def async_get_entry(self, entry_id: str):
        return self.entries.get(entry_id)

    @property
    def flow(self):
        return self

    async def async_init(self, domain, *, context=None, data=None, **_kw):
        return await self.async_init_flow(domain, context=context, data=data)

    async def async_init_flow(self, domain, *, context=None, data=None, **_kw):
        self.init_calls.append((domain, context, data))
        return {"type": "form", "flow_id": "reauth-flow", "context": context}


class FakeHass:
    """Minimal hass stand-in exposing the registries the repairs flow touches."""

    def __init__(self) -> None:
        self.issue_registry = FakeIssueRegistry()
        self.config_entries = FakeConfigEntries()
        self.created_tasks: list[object] = []

    def async_create_task(self, coro):
        self.created_tasks.append(coro)
        return coro


@pytest.fixture
def fake_hass(monkeypatch):
    """Wire a FakeHass into the issue registry helpers used by repairs."""
    from homeassistant.helpers import issue_registry as ir

    hass = FakeHass()
    monkeypatch.setattr(ir, "async_get", lambda _hass: hass.issue_registry)
    return hass


@pytest.fixture
def fake_entry():
    return FakeEntry()


# ---------------------------------------------------------------------------
# issue lifecycle: created -> resolved -> deleted
# ---------------------------------------------------------------------------


def test_create_pairing_lost_issue(fake_hass, fake_entry):
    async_create_pairing_lost_issue(fake_hass, fake_entry)

    key = (DOMAIN, ISSUE_PAIRING_LOST)
    assert key in fake_hass.issue_registry.issues
    issue = fake_hass.issue_registry.issues[key]
    assert issue["is_fixable"] is True
    assert issue["translation_key"] == ISSUE_PAIRING_LOST
    assert issue["translation_placeholders"] == {"name": "Wohnzimmer TV"}
    assert issue["data"] == {"entry_id": "entry-1"}


def test_create_issue_is_idempotent(fake_hass, fake_entry):
    async_create_pairing_lost_issue(fake_hass, fake_entry)
    async_create_pairing_lost_issue(fake_hass, fake_entry)

    key = (DOMAIN, ISSUE_PAIRING_LOST)
    assert key in fake_hass.issue_registry.issues
    # same single issue, not duplicated
    assert len(fake_hass.issue_registry.issues) == 1


def test_delete_pairing_lost_issue(fake_hass):
    fake_hass.issue_registry.issues[(DOMAIN, ISSUE_PAIRING_LOST)] = {
        "data": {"entry_id": "entry-1"}
    }

    async_delete_pairing_lost_issue(fake_hass, "entry-1")

    assert (DOMAIN, ISSUE_PAIRING_LOST) not in fake_hass.issue_registry.issues


def test_delete_issue_when_absent_is_noop(fake_hass):
    # must not raise even if the issue was never created
    async_delete_pairing_lost_issue(fake_hass, "entry-unknown")
    assert fake_hass.issue_registry.issues == {}


# ---------------------------------------------------------------------------
# fix flow creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_fix_flow_returns_pairing_flow():
    flow = await async_create_fix_flow(None, ISSUE_PAIRING_LOST, {"entry_id": "e1"})

    assert isinstance(flow, PairingLostRepairFlow)
    assert flow.data == {"entry_id": "e1"}


@pytest.mark.asyncio
async def test_create_fix_flow_unknown_issue_returns_none():
    flow = await async_create_fix_flow(None, "some_other_issue", {"entry_id": "e1"})
    assert flow is None


# ---------------------------------------------------------------------------
# fix flow behaviour: confirm -> dismiss issue + start reauth
# ---------------------------------------------------------------------------


def _make_flow(fake_hass, fake_entry):
    flow = PairingLostRepairFlow()
    flow.handler = DOMAIN
    flow.issue_id = ISSUE_PAIRING_LOST
    flow.data = {"entry_id": fake_entry.entry_id}
    flow.hass = fake_hass
    fake_hass.config_entries.entries[fake_entry.entry_id] = fake_entry
    return flow


@pytest.mark.asyncio
async def test_repair_init_shows_confirm_form(fake_hass, fake_entry):
    flow = _make_flow(fake_hass, fake_entry)
    fake_hass.issue_registry.async_get_or_create(
        DOMAIN,
        ISSUE_PAIRING_LOST,
        is_fixable=True,
        severity=None,
        translation_key=ISSUE_PAIRING_LOST,
        translation_placeholders={"name": "Wohnzimmer TV"},
    )

    result = await flow.async_step_init(None)

    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert result["description_placeholders"] == {"name": "Wohnzimmer TV"}


@pytest.mark.asyncio
async def test_repair_confirm_starts_reauth_and_resolves_issue(fake_hass, fake_entry):
    flow = _make_flow(fake_hass, fake_entry)

    result = await flow.async_step_init({})

    # confirm -> create_entry (repairs manager then deletes the issue)
    assert result["type"] == "create_entry"
    # a reauth flow was scheduled for the right entry
    assert len(fake_hass.created_tasks) == 1
    # The scheduled task wraps the flow-init coroutine; await it to record the call.
    await fake_hass.created_tasks[0]
    domain, context, data = fake_hass.config_entries.init_calls[0]
    assert domain == DOMAIN
    assert context["source"] == "reauth"
    assert context["entry_id"] == fake_entry.entry_id
    assert data is fake_entry.data


@pytest.mark.asyncio
async def test_repair_confirm_with_missing_entry_still_dismisses(fake_hass):
    flow = PairingLostRepairFlow()
    flow.handler = DOMAIN
    flow.issue_id = ISSUE_PAIRING_LOST
    flow.data = {"entry_id": "gone"}
    flow.hass = fake_hass

    result = await flow.async_step_init({})

    # no entry -> nothing scheduled, but the issue is still dismissed
    assert result["type"] == "create_entry"
    assert fake_hass.created_tasks == []


@pytest.mark.asyncio
async def test_issue_lifecycle_created_then_deleted(fake_hass, fake_entry):
    """End-to-end lifecycle: created on pairing-lost, deleted after resolution."""
    async_create_pairing_lost_issue(fake_hass, fake_entry)
    key = (DOMAIN, ISSUE_PAIRING_LOST)
    assert key in fake_hass.issue_registry.issues

    flow = _make_flow(fake_hass, fake_entry)
    result = await flow.async_step_init({})

    assert result["type"] == "create_entry"
    # simulating the repairs manager's finish hook
    fake_hass.issue_registry.async_delete(DOMAIN, flow.issue_id)
    assert fake_hass.issue_registry.issues == {}
