"""Config flow for the Hisense TV integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .button import BUTTON_DESCRIPTIONS
from .const import (
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
    AUTH_WAIT_EVENTS,
    PROBE_WAIT_EVENTS,
    PROBE_TIMEOUT,
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
    host_from_location,
    parse_upnp_dict,
)

_LOGGER = logging.getLogger(__name__)

PIN_FIELD = "pin"


class PairingRequired(Exception):
    """The TV pushed an /authentication request while probing."""


def _host_schema(host: str | None) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_HOST, description={"suggested_value": host or ""}): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Optional(CONF_NAME, description={"suggested_value": ""}): str,
        }
    )


def _pin_schema(errors: dict[str, str] | None = None) -> vol.Schema:
    return vol.Schema({vol.Required(PIN_FIELD): str})


class HisenseTvConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Hisense TV config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered: DiscoveredTV | None = None
        self._host: str = ""
        self._port: int = DEFAULT_PORT
        self._use_tls: bool | None = None
        self._client_id: str = ""
        self._friendly_name: str = ""
        self._probe_client: HisenseTvClient | None = None
        self._scan_results: list[DiscoveredTV] = []
        self._is_reconfiguring: bool = False
        self._reauth_target_entry_id: str | None = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @property
    def _probe(self) -> HisenseTvClient:
        assert self._probe_client is not None
        return self._probe_client

    async def _validate(self) -> str:
        """Connect + probe. Raises CannotConnect / PairingRequired."""
        # Enrich via SSDP first: knowing transport_protocol up front lets us
        # open the right transport immediately instead of wasting a plain
        # TCP attempt against a TLS-only broker.
        if self._use_tls is None and self._discovered is None:
            try:
                tv = await asyncio.wait_for(self._lookup_metadata(), timeout=6)
            except asyncio.TimeoutError:
                tv = None
            if tv is not None:
                _LOGGER.debug("SSDP enrichment before probe: %s (tls=%s)", tv.model_name, tv.use_tls)
                self._discovered = tv
                self._use_tls = tv.use_tls

        if not self._client_id:
            self._client_id = new_client_id()

        client = HisenseTvClient(
            host=self._host,
            port=self._port,
            client_id=self._client_id,
            use_tls=self._use_tls,
            client_cert_path=default_client_cert_path(),
        )
        await client.start()  # CannotConnect bubbles up

        marker = len(client.recent_events())
        await client.get_tv_state()
        _LOGGER.debug("Probe %s:%s sent gettvstate (tls=%s)", self._host, self._port, client.active_tls)
        try:
            # Only /authentication proves "pairing needed". Spontaneous
            # broadcast state updates (e.g. voicestate) must not be mistaken
            # for a successful auth probe; timeout means no pairing gate.
            event_name, _payload = await wait_for_event(
                client,
                PROBE_WAIT_EVENTS,
                PROBE_TIMEOUT,
                start_index=marker,
            )
        except asyncio.TimeoutError:
            # Older firmware: no push feedback, no pairing gate -> accept.
            _LOGGER.debug("Probe finished without pairing gate")
            self._probe_client = client
            if self._use_tls is None:
                self._use_tls = client.active_tls
            return "ok"

        if self._use_tls is None:
            self._use_tls = client.active_tls
        _LOGGER.debug("Probe: TV requests pairing (%s)", _payload)
        self._probe_client = client
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
        if self._probe_client is not None:
            await self._probe_client.stop()
            self._probe_client = None

        friendly = self._friendly_name or (tv.name if tv else "") or DEFAULT_NAME
        data: dict[str, Any] = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_NAME: friendly,
            CONF_USE_TLS: bool(self._use_tls),
            CONF_UUID: self._client_id,
            "client_id": self._client_id,
        }
        if tv is not None:
            data.update(
                {
                    CONF_MODEL_NAME: tv.model_name,
                    CONF_TV_VERSION: tv.tv_version,
                    CONF_UDN: tv.udn,
                    CONF_REGION: tv.region,
                    CONF_COUNTRY: tv.country,
                    CONF_LANGUAGE: tv.language,
                    CONF_PLATFORM_VERSION: tv.extras.get("platform", ""),
                    CONF_TRANSPORT_PROTOCOL: tv.transport_protocol,
                }
            )
            if tv.mac_wifi:
                data[CONF_MAC_WIFI] = tv.mac_wifi
            if tv.mac_ethernet:
                data[CONF_MAC_ETHERNET] = tv.mac_ethernet

        if self._reauth_target_entry_id is not None:
            # Reauth path: the TV forgot us. Keep the entry (and its title /
            # name), swap in the fresh client identity and connection data.
            entry = self.hass.config_entries.async_get_entry(self._reauth_target_entry_id)
            if entry is None:
                return self.async_abort(reason="reauth_successful")
            merged = {**entry.data, **data}
            if not self._friendly_name and entry.data.get(CONF_NAME):
                merged[CONF_NAME] = entry.data.get(CONF_NAME)
            self.hass.config_entries.async_update_entry(entry, data=merged)
            from .repairs import async_delete_pairing_lost_issue  # noqa: PLC0415

            async_delete_pairing_lost_issue(self.hass, entry.entry_id)
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        if self._is_reconfiguring:
            # Reconfigure path (possibly reached through the pairing step):
            # update the existing entry instead of creating a new one.
            entry = self._get_reconfigure_entry()
            merged = {**entry.data, **data}
            if not tv:
                # Keep previous metadata when nothing better was found.
                for key in (
                    CONF_MODEL_NAME,
                    CONF_TV_VERSION,
                    CONF_UDN,
                    CONF_REGION,
                    CONF_COUNTRY,
                    CONF_LANGUAGE,
                    CONF_PLATFORM_VERSION,
                    CONF_TRANSPORT_PROTOCOL,
                ):
                    merged[key] = entry.data.get(key, merged.get(key, ""))
            return self.async_create_entry(title=entry.title, data=merged)

        return self.async_create_entry(title=friendly, data=data)

    # ------------------------------------------------------------------
    # user initiated setup
    # ------------------------------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
                try:
                    result = await self._validate()
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except PairingRequired:
                    return self.async_show_form(step_id="pairing", data_schema=_pin_schema(), errors={})
                else:
                    if result == "ok":
                        return await self._finish()

        return self.async_show_form(step_id="user", data_schema=_host_schema(None), errors=errors)

    async def async_step_discover(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        results = self._scan_results
        options = {
            tv.unique_id: f"{tv.name or tv.host} ({tv.model_name or 'Hisense'})" for tv in results
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
                await self.async_set_unique_id(tv.unique_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: tv.host, CONF_PORT: tv.mqtt_port})
                try:
                    result = await self._validate()
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except PairingRequired:
                    return self.async_show_form(step_id="pairing", data_schema=_pin_schema(), errors={})
                else:
                    if result == "ok":
                        return await self._finish()

        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema({vol.Required("device"): vol.In(options)}),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # pairing (mirrors SecurityActivity of the RemoteNOW app)
    # ------------------------------------------------------------------
    async def _show_pin_error(self, error: str) -> ConfigFlowResult:
        return self.async_show_form(step_id="pairing", data_schema=_pin_schema(), errors={"base": error})

    async def async_step_pairing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert user_input is not None
        pin = str(user_input[PIN_FIELD]).strip()
        client = self._probe
        marker = len(client.recent_events())
        _LOGGER.debug("Submitting pairing code to %s", client.host)
        await client.submit_pairing_code(pin)
        try:
            _name, auth_result = await wait_for_event(
                client, AUTH_WAIT_EVENTS, PAIRING_TIMEOUT / 2, start_index=marker
            )
        except asyncio.TimeoutError:
            _LOGGER.debug("Pairing: no authenticationcode feedback (timeout)")
            return await self._show_pin_error("pairing_timeout")
        if not auth_result.ok:
            _LOGGER.debug("Pairing rejected: result=%s info=%s", auth_result.result, auth_result.info)
            await client.cancel_pairing()
            return await self._show_pin_error("invalid_pin")
        _LOGGER.debug("Pairing accepted by TV")
        return await self._finish()

    # ------------------------------------------------------------------
    # reauth (pairing expired: TV was reset or firmware updated)
    # ------------------------------------------------------------------
    async def async_step_reauth(self, entry_data) -> ConfigFlowResult:  # noqa: ANN001
        entry_id = self.context.get("entry_id")
        self._reauth_target_entry_id = str(entry_id) if entry_id else None
        self._host = str(entry_data.get(CONF_HOST) or "")
        self._port = int(entry_data.get(CONF_PORT) or DEFAULT_PORT)
        self._use_tls = entry_data.get(CONF_USE_TLS)
        self._client_id = ""  # fresh identity - the TV forgot the old one
        self._friendly_name = ""
        self._discovered = None
        name = str(entry_data.get(CONF_NAME) or self._host)
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                result = await self._validate()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except PairingRequired:
                return self.async_show_form(step_id="pairing", data_schema=_pin_schema(), errors={})
            else:
                if result == "ok":
                    # The TV still knows this client - pairing was not lost.
                    _LOGGER.debug("Reauth probe succeeded without pairing")
                    return await self._finish()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "name": str(self.context.get("title_placeholders", {}).get("name", "")),
            },
        )

    # ------------------------------------------------------------------
    # discovery driven steps (manifest ssdp/dhcp matchers)
    # ------------------------------------------------------------------
    async def async_step_ssdp(self, discovery_info: Any) -> ConfigFlowResult:
        location = getattr(discovery_info, "ssdp_location", None)
        headers = getattr(discovery_info, "ssdp_headers", {}) or {}
        if not location and isinstance(headers, dict):
            location = headers.get("location") or headers.get("LOCATION")
        if not location and hasattr(discovery_info, "upnp") and isinstance(discovery_info.upnp, dict):
            location = discovery_info.upnp.get("location")

        host = ""
        if location:
            host = host_from_location(location) or ""
        if not host:
            ip = getattr(discovery_info, "ip_address", None) or getattr(discovery_info, "host", None)
            host = str(ip) if ip else ""

        tv: DiscoveredTV | None = None
        if location:
            try:
                tv = await fetch_description(location)
            except Exception as ex:  # noqa: BLE001
                _LOGGER.debug("SSDP fetch_description error: %s", ex)
        if tv is None and hasattr(discovery_info, "upnp") and isinstance(discovery_info.upnp, dict):
            tv = parse_upnp_dict(discovery_info.upnp, host=host)

        if tv is None:
            return self.async_abort(reason="not_hisense")

        if host and not tv.host:
            tv.host = host

        await self.async_set_unique_id(tv.unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: tv.host, CONF_PORT: tv.mqtt_port})
        self._discovered = tv
        self._host = tv.host
        self._port = tv.mqtt_port
        self._use_tls = tv.use_tls
        self._friendly_name = tv.name
        self.context["title_placeholders"] = {"name": tv.name or tv.host}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        tv = self._discovered
        assert tv is not None
        if user_input is not None:
            try:
                result = await self._validate()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except PairingRequired:
                return self.async_show_form(step_id="pairing", data_schema=_pin_schema(), errors={})
            else:
                if result == "ok":
                    return await self._finish()

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "name": tv.name or tv.host,
                "model": tv.model_name or "Hisense",
                "host": tv.host,
                "port": str(tv.mqtt_port),
            },
        )

    async def async_step_dhcp(self, discovery_info: Any) -> ConfigFlowResult:
        """DHCP discovery: cheap metadata lookup only, no MQTT probe.

        Discovery steps should return fast; the full connection probe (and any
        pairing) happens on the confirm step when the user accepts.
        """
        host = getattr(discovery_info, "ip", None)
        if not host:
            return self.async_abort(reason="not_hisense")
        self._host = str(host)
        self._port = DEFAULT_PORT
        # Best-effort SSDP metadata enrichment (bounded, non-fatal).
        tv = await self._lookup_metadata()
        if tv is not None:
            self._discovered = tv
            self._port = tv.mqtt_port or self._port
            self._use_tls = tv.use_tls
            self._friendly_name = tv.name
        else:
            self._friendly_name = f"Hisense TV ({self._host})"
        self.context["title_placeholders"] = {"name": self._friendly_name}
        return await self.async_step_confirm()

    async def async_step_reconfirm(self, discovery_info: Any) -> ConfigFlowResult:
        """A registered TV reappeared under a different IP address."""
        host = getattr(discovery_info, "ip", None)
        mac = getattr(discovery_info, "macaddress", None)
        if not host or not mac:
            return self.async_abort(reason="not_hisense")

        normalized = str(mac).upper().replace(":", "").replace("-", "")
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            stored_macs = {
                str(entry.data.get(key, "")).replace(":", "").replace("-", "").upper()
                for key in (CONF_MAC_WIFI, CONF_MAC_ETHERNET)
            }
            if normalized in stored_macs and normalized:
                if entry.data.get(CONF_HOST) != host:
                    self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_HOST: str(host)})
                    return self.async_abort(reason="reconfirm_success")
                return self.async_abort(reason="already_configured")
        return self.async_abort(reason="not_hisense")

    # ------------------------------------------------------------------
    # reconfigure (manual host/port change with full revalidation)
    # ------------------------------------------------------------------
    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        self._is_reconfiguring = True
        errors: dict[str, str] = {}
        if user_input is not None:
            old_host = str(entry.data.get(CONF_HOST))
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])
            if host != old_host:
                # New address: forget per-host metadata so SSDP can re-enrich.
                self._discovered = None
            self._host = host
            self._port = port
            self._use_tls = None  # re-detect on the new address
            self._client_id = str(entry.data.get(CONF_UUID) or new_client_id())
            try:
                result = await self._validate()
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except PairingRequired:
                return self.async_show_form(step_id="pairing", data_schema=_pin_schema(), errors={})
            else:
                if result == "ok":
                    tv = self._discovered or await self._lookup_metadata()
                    new_data = {**entry.data, CONF_HOST: host, CONF_PORT: port, CONF_USE_TLS: bool(self._use_tls)}
                    if tv is not None:
                        new_data.update(
                            {
                                CONF_MODEL_NAME: tv.model_name or entry.data.get(CONF_MODEL_NAME, ""),
                                CONF_TV_VERSION: tv.tv_version or entry.data.get(CONF_TV_VERSION, ""),
                                CONF_MAC_WIFI: tv.mac_wifi or entry.data.get(CONF_MAC_WIFI, ""),
                                CONF_MAC_ETHERNET: tv.mac_ethernet or entry.data.get(CONF_MAC_ETHERNET, ""),
                            }
                        )
                    if self._probe_client is not None:
                        await self._probe_client.stop()
                        self._probe_client = None
                    return self.async_create_entry(title=entry.title, data=new_data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=str(entry.data.get(CONF_HOST, ""))): str,
                    vol.Required(CONF_PORT, default=int(entry.data.get(CONF_PORT, DEFAULT_PORT))): int,
                }
            ),
            errors=errors,
        )


    # ------------------------------------------------------------------
    # options
    # ------------------------------------------------------------------
    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> HisenseTvOptionsFlowHandler:  # noqa: ANN001
        return HisenseTvOptionsFlowHandler()


class HisenseTvOptionsFlowHandler(OptionsFlowWithReload):
    """Behavioral options; reloads the entry automatically on save."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        button_options = [
            SelectOptionDict(value=description.key, label=description.label)
            for description in BUTTON_DESCRIPTIONS
        ]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=600)),
                vol.Required(
                    CONF_ENABLE_WOL,
                    default=options.get(CONF_ENABLE_WOL, DEFAULT_ENABLE_WOL),
                ): bool,
                vol.Required(
                    CONF_COMMAND_DELAY,
                    default=options.get(CONF_COMMAND_DELAY, DEFAULT_COMMAND_DELAY),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
                vol.Required(
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
