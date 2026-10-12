"""Config flow for the Hisense TV integration."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import probatio

from .button import BUTTON_DESCRIPTIONS
from .const import (
    AUTH_WAIT_EVENTS,
    CONF_BUTTONS,
    CONF_COMMAND_DELAY,
    CONF_COUNTRY,
    CONF_ENABLE_WOL,
    CONF_LANGUAGE,
    CONF_MAC_ETHERNET,
    CONF_MAC_WIFI,
    CONF_MODEL_NAME,
    CONF_PLATFORM_VERSION,
    CONF_POLL_INTERVAL,
    CONF_REGION,
    CONF_TRANSPORT_PROTOCOL,
    CONF_TV_VERSION,
    CONF_UDN,
    CONF_USE_TLS,
    CONF_UUID,
    DEFAULT_BUTTONS,
    DEFAULT_COMMAND_DELAY,
    DEFAULT_ENABLE_WOL,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    PAIRING_TIMEOUT,
    PROBE_TIMEOUT,
    PROBE_WAIT_EVENTS,
)
from .data import (
    CannotConnect,
    HisenseTvClient,
    default_client_cert_path,
    new_client_id,
    wait_for_event,
)
from .discovery import (
    DiscoveredTV,
    async_discover_tvs,
    fetch_description,
    format_mac,
    host_from_location,
    parse_upnp_dict,
)

if TYPE_CHECKING:
    from homeassistant.components.dhcp import DhcpServiceInfo
    from homeassistant.components.ssdp import SsdpServiceInfo

_LOGGER = logging.getLogger(__name__)

PIN_FIELD = "pin"


class PairingRequired(Exception):
    """The TV pushed an /authentication request while probing."""


def _host_schema(host: str | None) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Optional(
                CONF_HOST, description={"suggested_value": host or ""}
            ): str,
            probatio.Required(CONF_PORT, default=DEFAULT_PORT): int,
            probatio.Optional(CONF_NAME, description={"suggested_value": ""}): str,
        }
    )


def _pin_schema() -> probatio.Schema:
    return probatio.Schema({probatio.Required(PIN_FIELD): str})


def _tv_macs(tv: DiscoveredTV | None) -> list[str]:
    """MACs a discovered TV advertises (wifi first)."""
    if tv is None:
        return []
    return [mac for mac in (tv.mac_wifi, tv.mac_ethernet) if mac]


def _entry_macs(entry: ConfigEntry) -> set[str]:
    """Normalized MACs stored on a config entry."""
    return {
        format_mac(str(entry.data[key]))
        for key in (CONF_MAC_WIFI, CONF_MAC_ETHERNET)
        if entry.data.get(key)
    }


def _tv_unique_id(tv: DiscoveredTV | None) -> str | None:
    """Device identity for the entry: MAC, else UDN - never the IP address."""
    if tv is None or not (tv.mac_wifi or tv.mac_ethernet or tv.udn):
        return None
    return tv.unique_id


def _tv_metadata(tv: DiscoveredTV | None) -> dict[str, Any]:
    """Entry data learned from SSDP; empty values are left out.

    Leaving them out lets a reconfigure/reauth merge keep what the entry
    already knows instead of blanking it with an incomplete description.
    """
    if tv is None:
        return {}
    values: dict[str, Any] = {
        CONF_MODEL_NAME: tv.model_name,
        CONF_TV_VERSION: tv.tv_version,
        CONF_UDN: tv.udn,
        CONF_REGION: tv.region,
        CONF_COUNTRY: tv.country,
        CONF_LANGUAGE: tv.language,
        CONF_PLATFORM_VERSION: tv.extras.get("platform", ""),
        CONF_TRANSPORT_PROTOCOL: tv.transport_protocol,
        CONF_MAC_WIFI: tv.mac_wifi,
        CONF_MAC_ETHERNET: tv.mac_ethernet,
    }
    return {key: value for key, value in values.items() if value not in ("", None)}


class HisenseTvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Hisense TV config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state for a fresh, aborted or retried run."""
        self._discovered: DiscoveredTV | None = None
        self._host: str = ""
        self._port: int = DEFAULT_PORT
        self._use_tls: bool | None = None
        self._client_id: str = ""
        self._friendly_name: str = ""
        self._probe_client: HisenseTvClient | None = None
        self._scan_results: list[DiscoveredTV] = []

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @property
    def _probe(self) -> HisenseTvClient:
        assert self._probe_client is not None
        return self._probe_client

    @callback
    def async_remove(self) -> None:
        """Close a probe connection the user abandoned (e.g. at the PIN step).

        The probe client runs its own reconnect loop; without this it would
        keep an MQTT session to the TV open until Home Assistant restarts.
        """
        if (client := self._probe_client) is not None:
            self._probe_client = None
            self.hass.async_create_task(client.stop(), "hisense_tv probe cleanup")

    async def _stop_probe(self) -> None:
        if (client := self._probe_client) is not None:
            self._probe_client = None
            await client.stop()

    def _find_configured_entry(
        self, host: str | None, macs: Iterable[str]
    ) -> ConfigEntry | None:
        """Existing entry for this TV: matched by MAC, else by host.

        The host only counts when one side has no MAC to compare - a
        different TV may well have inherited the IP of a configured one.
        """
        wanted = {format_mac(mac) for mac in macs if mac}
        entries = self._async_current_entries(include_ignore=False)
        for entry in entries:
            if wanted & _entry_macs(entry):
                return entry
        if host:
            for entry in entries:
                if entry.data.get(CONF_HOST) == host and not (
                    wanted and _entry_macs(entry)
                ):
                    return entry
        return None

    def _abort_if_tv_configured(
        self, host: str | None, macs: Iterable[str], updates: dict[str, Any]
    ) -> None:
        """Abort when the TV already has an entry, moving it to the new address."""
        entry = self._find_configured_entry(host, macs)
        if entry is None:
            return
        if self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, **updates}
        ) and entry.state in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_RETRY):
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
        raise AbortFlow("already_configured")

    async def _validate(self) -> str:
        """Connect + probe. Raises CannotConnect / PairingRequired."""
        # Enrich via SSDP first: knowing transport_protocol up front lets us
        # open the right transport immediately instead of wasting a plain
        # TCP attempt against a TLS-only broker.
        if self._use_tls is None and self._discovered is None:
            try:
                tv = await asyncio.wait_for(self._lookup_metadata(), timeout=6)
            except TimeoutError:
                tv = None
            if tv is not None:
                _LOGGER.debug(
                    "SSDP enrichment before probe: %s (tls=%s)",
                    tv.model_name,
                    tv.use_tls,
                )
                self._discovered = tv
                self._use_tls = tv.use_tls

        if self.source == SOURCE_USER:
            # Before probing: a duplicate must not walk through PIN pairing.
            self._abort_if_tv_configured(
                self._host,
                _tv_macs(self._discovered),
                {CONF_HOST: self._host, CONF_PORT: self._port},
            )

        if not self._client_id:
            self._client_id = new_client_id()

        await self._stop_probe()
        client = HisenseTvClient(
            host=self._host,
            port=self._port,
            client_id=self._client_id,
            use_tls=self._use_tls,
            client_cert_path=default_client_cert_path(),
        )
        await client.start()  # CannotConnect bubbles up
        self._probe_client = client

        marker = client.event_marker()
        await client.get_tv_state()
        _LOGGER.debug(
            "Probe %s:%s sent gettvstate (tls=%s)",
            self._host,
            self._port,
            client.active_tls,
        )
        if self._use_tls is None:
            self._use_tls = client.active_tls
        try:
            # Only /authentication proves "pairing needed". Spontaneous
            # broadcast state updates (e.g. voicestate) must not be mistaken
            # for a successful auth probe; timeout means no pairing gate.
            _event_name, payload = await wait_for_event(
                client,
                PROBE_WAIT_EVENTS,
                PROBE_TIMEOUT,
                start_index=marker,
            )
        except TimeoutError:
            # Older firmware: no push feedback, no pairing gate -> accept.
            _LOGGER.debug("Probe finished without pairing gate")
            return "ok"

        _LOGGER.debug("Probe: TV requests pairing (%s)", payload)
        raise PairingRequired

    async def _lookup_metadata(self) -> DiscoveredTV | None:
        """Best-effort SSDP enrichment for manually entered hosts."""
        if self._discovered is not None:
            return self._discovered
        try:
            tvs = await async_discover_tvs(timeout=3.0)
        except Exception:  # noqa: BLE001
            return None
        return next((tv for tv in tvs if tv.host == self._host), None)

    async def _finish(self) -> ConfigFlowResult:
        """Disconnect the probe connection and store the result."""
        tv = self._discovered or await self._lookup_metadata()
        await self._stop_probe()

        connection: dict[str, Any] = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_USE_TLS: bool(self._use_tls),
            CONF_UUID: self._client_id,
            "client_id": self._client_id,
        }
        metadata = _tv_metadata(tv)

        if self.source in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
            # Reauth (the TV forgot us) and reconfigure (new address) both
            # update the existing entry; its title and name stay untouched.
            entry = (
                self._get_reauth_entry()
                if self.source == SOURCE_REAUTH
                else self._get_reconfigure_entry()
            )
            return self.async_update_reload_and_abort(
                entry, data={**entry.data, **metadata, **connection}
            )

        if unique_id := _tv_unique_id(tv):
            await self.async_set_unique_id(unique_id, raise_on_progress=False)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._host, CONF_PORT: self._port}
            )

        friendly = self._friendly_name or (tv.name if tv else "") or DEFAULT_NAME
        return self.async_create_entry(
            title=friendly, data={**connection, CONF_NAME: friendly, **metadata}
        )

    async def _probe_step(self) -> ConfigFlowResult | dict[str, str]:
        """Run the probe; returns the next result, or form errors to show."""
        try:
            await self._validate()
        except CannotConnect:
            return {"base": "cannot_connect"}
        except PairingRequired:
            return self.async_show_form(
                step_id="pairing", data_schema=_pin_schema(), errors={}
            )
        return await self._finish()

    # ------------------------------------------------------------------
    # user initiated setup
    # ------------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry step: empty host triggers discovery, otherwise probe directly."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = str(user_input.get(CONF_HOST) or "").strip()
            port = int(user_input.get(CONF_PORT) or DEFAULT_PORT)
            friendly = str(user_input.get(CONF_NAME) or "").strip()
            if friendly:
                self._friendly_name = friendly

            if not host:
                try:
                    self._scan_results = await async_discover_tvs(timeout=4.0)
                except Exception:  # noqa: BLE001
                    self._scan_results = []
                if not self._scan_results:
                    errors["base"] = "no_devices_found"
                else:
                    return await self.async_step_discover()
            else:
                self._host = host
                self._port = port
                result = await self._probe_step()
                if "type" in result:
                    return result
                errors = result

        return self.async_show_form(
            step_id="user", data_schema=_host_schema(self._host), errors=errors
        )

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick one of the discovered TVs."""
        errors: dict[str, str] = {}
        results = self._scan_results
        options = {
            tv.unique_id: f"{tv.name or tv.host} ({tv.model_name or 'Hisense'})"
            for tv in results
        }
        if user_input is not None:
            selected = user_input.get("device")
            tv = next((item for item in results if item.unique_id == selected), None)
            if tv is None:
                errors["base"] = "invalid_selection"
            else:
                self._discovered = tv
                self._host = tv.host
                self._port = tv.mqtt_port
                self._use_tls = tv.use_tls
                if tv.name:
                    self._friendly_name = tv.name
                result = await self._probe_step()
                if "type" in result:
                    return result
                errors = result

        return self.async_show_form(
            step_id="discover",
            data_schema=probatio.Schema(
                {probatio.Required("device"): probatio.In(options)}
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # pairing (mirrors SecurityActivity of the RemoteNOW app)
    # ------------------------------------------------------------------
    async def _show_pin_error(self, error: str) -> ConfigFlowResult:
        return self.async_show_form(
            step_id="pairing", data_schema=_pin_schema(), errors={"base": error}
        )

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Submit the PIN shown on the TV and wait for the auth result."""
        assert user_input is not None
        pin = str(user_input[PIN_FIELD]).strip()
        client = self._probe
        marker = client.event_marker()
        _LOGGER.debug("Submitting pairing code to %s", client.host)
        await client.submit_pairing_code(pin)
        try:
            _name, auth_result = await wait_for_event(
                client, AUTH_WAIT_EVENTS, PAIRING_TIMEOUT / 2, start_index=marker
            )
        except TimeoutError:
            _LOGGER.debug("Pairing: no authenticationcode feedback (timeout)")
            return await self._show_pin_error("pairing_timeout")
        if not auth_result.ok:
            _LOGGER.debug(
                "Pairing rejected: result=%s info=%s",
                auth_result.result,
                auth_result.info,
            )
            await client.cancel_pairing()
            return await self._show_pin_error("invalid_pin")
        _LOGGER.debug("Pairing accepted by TV")
        return await self._finish()

    # ------------------------------------------------------------------
    # reauth (pairing expired: TV was reset or firmware updated)
    # ------------------------------------------------------------------
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-pairing with a fresh client identity for this entry."""
        self._host = str(entry_data.get(CONF_HOST) or "")
        self._port = int(entry_data.get(CONF_PORT) or DEFAULT_PORT)
        self._use_tls = entry_data.get(CONF_USE_TLS)
        self._client_id = ""  # fresh identity - the TV forgot the old one
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Probe the TV: pairing gate only appears when the old pairing is gone."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._probe_step()
            if "type" in result:
                return result
            errors = result

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema({}),
            errors=errors,
            description_placeholders={"name": self._get_reauth_entry().title},
        )

    # ------------------------------------------------------------------
    # discovery driven steps (manifest ssdp/dhcp matchers)
    # ------------------------------------------------------------------
    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> ConfigFlowResult:
        """Handle SSDP discovery: parse the description and ask for confirmation."""
        upnp = discovery_info.upnp if isinstance(discovery_info.upnp, Mapping) else {}
        headers = discovery_info.ssdp_headers or {}
        location = (
            discovery_info.ssdp_location
            or headers.get("location")
            or headers.get("LOCATION")
            or upnp.get("location")
        )

        host = (host_from_location(location) or "") if location else ""

        tv: DiscoveredTV | None = None
        if location:
            try:
                tv = await fetch_description(location)
            except Exception as ex:  # noqa: BLE001
                _LOGGER.debug("SSDP fetch_description error: %s", ex)
        if tv is None and upnp:
            tv = parse_upnp_dict(dict(upnp), host=host)

        if tv is None:
            return self.async_abort(reason="not_hisense")

        if host and not tv.host:
            tv.host = host

        # Also catches entries added by IP, which have no unique id to match.
        self._abort_if_tv_configured(
            tv.host, _tv_macs(tv), {CONF_HOST: tv.host, CONF_PORT: tv.mqtt_port}
        )
        await self.async_set_unique_id(tv.unique_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: tv.host, CONF_PORT: tv.mqtt_port}
        )
        self._discovered = tv
        self._host = tv.host
        self._port = tv.mqtt_port
        self._use_tls = tv.use_tls
        self._friendly_name = tv.name
        self.context["title_placeholders"] = {"name": tv.name or tv.host}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirmation step for a TV found by SSDP."""
        errors: dict[str, str] = {}
        tv = self._discovered
        assert tv is not None
        if user_input is not None:
            result = await self._probe_step()
            if "type" in result:
                return result
            errors = result

        return self.async_show_form(
            step_id="confirm",
            data_schema=probatio.Schema({}),
            errors=errors,
            description_placeholders={
                "name": tv.name or tv.host,
                "model": tv.model_name or "Hisense",
                "host": tv.host,
                "port": str(tv.mqtt_port),
            },
        )

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """A registered TV was seen on DHCP (manifest: registered_devices).

        The matcher only fires for MACs already in the device registry, so
        this never sets up a new TV: it follows an IP change of a configured
        one and aborts, without showing a discovery card.
        """
        mac = format_mac(discovery_info.macaddress)
        self._abort_if_tv_configured(None, [mac], {CONF_HOST: discovery_info.ip})
        return self.async_abort(reason="not_hisense")

    # ------------------------------------------------------------------
    # reconfigure (manual host/port change with full revalidation)
    # ------------------------------------------------------------------
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual host/port change with full revalidation before saving."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = str(user_input[CONF_HOST]).strip()
            self._port = int(user_input[CONF_PORT])
            self._use_tls = None  # re-detect on the new address
            self._discovered = None  # SSDP re-enriches for the new address
            self._client_id = str(entry.data.get(CONF_UUID) or new_client_id())
            result = await self._probe_step()
            if "type" in result:
                return result
            errors = result

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_HOST, default=str(entry.data.get(CONF_HOST, ""))
                    ): str,
                    probatio.Required(
                        CONF_PORT, default=int(entry.data.get(CONF_PORT, DEFAULT_PORT))
                    ): int,
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # options
    # ------------------------------------------------------------------
    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> HisenseTvOptionsFlowHandler:
        """Create the options flow handler for an entry."""
        return HisenseTvOptionsFlowHandler()


class HisenseTvOptionsFlowHandler(OptionsFlowWithReload):
    """Behavioral options; reloads the entry automatically on save."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form; a save triggers the automatic reload."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        button_options = [
            SelectOptionDict(value=description.key, label=description.label)
            for description in BUTTON_DESCRIPTIONS
        ]
        schema = probatio.Schema(
            {
                probatio.Required(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): probatio.All(probatio.Coerce(int), probatio.Range(min=5, max=600)),
                probatio.Required(
                    CONF_ENABLE_WOL,
                    default=options.get(CONF_ENABLE_WOL, DEFAULT_ENABLE_WOL),
                ): bool,
                probatio.Required(
                    CONF_COMMAND_DELAY,
                    default=options.get(CONF_COMMAND_DELAY, DEFAULT_COMMAND_DELAY),
                ): probatio.All(probatio.Coerce(int), probatio.Range(min=0, max=500)),
                probatio.Required(
                    CONF_BUTTONS,
                    default=list(options.get(CONF_BUTTONS, DEFAULT_BUTTONS)),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=button_options,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
