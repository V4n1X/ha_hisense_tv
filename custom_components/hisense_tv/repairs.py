"""Repairs platform for the Hisense TV integration.

Raises a repair issue when the TV no longer knows this Home Assistant
connection (pairing lost after a TV reset or firmware update).

The fix flow is a confirm dialog: confirming it dismisses the issue and
starts the entry's reauth flow, which walks the user through PIN pairing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.data_entry_flow import FlowResult

    from .__init__ import HisenseConfigEntry

ISSUE_PAIRING_LOST = "pairing_lost"


def async_create_pairing_lost_issue(
    hass: "HomeAssistant",
    entry: "HisenseConfigEntry",
) -> None:
    """Create (or refresh) the pairing-lost repair issue for an entry."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_PAIRING_LOST,
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_PAIRING_LOST,
        translation_placeholders={"name": entry.title or "Hisense TV"},
        data={"entry_id": entry.entry_id},
    )


def async_delete_pairing_lost_issue(
    hass: "HomeAssistant",
    entry_id: str,
) -> None:
    """Delete the pairing-lost repair issue (called after successful re-pair)."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_PAIRING_LOST)


class PairingLostRepairFlow(RepairsFlow):
    """Confirm dialog that dismisses the issue and starts re-pairing."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> "FlowResult":
        """Show the confirm step; on confirm, dismiss the issue and reauth."""
        if user_input is not None:
            entry_id = (self.data or {}).get("entry_id")
            entry = (
                self.hass.config_entries.async_get_entry(entry_id)
                if entry_id
                else None
            )
            if entry is not None:
                # Start the PIN re-pairing flow. It runs in the config entries
                # flow manager; the user continues it from the UI prompt.
                self.hass.async_create_task(
                    self.hass.config_entries.flow.async_init(
                        entry.domain,
                        context={"source": "reauth", "entry_id": entry.entry_id},
                        data=entry.data,
                    )
                )
            # create_entry deletes the issue (repairs manager does it for us).
            return self.async_create_entry(data={})

        issue_registry = ir.async_get(self.hass)
        description_placeholders = None
        if issue := issue_registry.async_get_issue(self.handler, self.issue_id):
            description_placeholders = issue.translation_placeholders

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
            description_placeholders=description_placeholders,
        )


async def async_create_fix_flow(
    hass: "HomeAssistant",
    issue_id: str,
    issue_data: dict[str, str | int | float | None] | None,
) -> PairingLostRepairFlow | None:
    """Create the repair flow for the pairing-lost issue."""
    if issue_id == ISSUE_PAIRING_LOST:
        flow = PairingLostRepairFlow()
        flow.data = issue_data or {}
        return flow
    return None
