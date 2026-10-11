"""Graphical pairing, reauthentication and per-family options."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .api import FreeboxClient, FreeboxError, normalize_host, tls_context
from .const import DEFAULT_HOST, DEFAULT_OPTIONS, DEFAULT_PORT, DOMAIN, FAMILIES, NAME, VERSION

_LOGGER = logging.getLogger(__name__)
CONNECTION_ERRORS = {
    "tls_certificate_error",
    "tls_handshake_error",
    "connection_timeout",
    "connection_refused",
    "https_unavailable",
    "invalid_api_version",
    "apps_denied",
    "wrong_freebox",
    "invalid_request",
    "new_apps_denied",
    "denied_from_external_ip",
    "ratelimited",
    "internal_error",
}


class FreeboxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._host = DEFAULT_HOST
        self._port = DEFAULT_PORT
        self._api: FreeboxClient | None = None
        self._app_id = ""
        self._app_token = ""
        self._track_id = 0
        self._pair_task: asyncio.Task[str] | None = None
        self._mode = "user"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return FreeboxOptionsFlow()

    async def async_step_zeroconf(self, discovery_info):
        self._host = discovery_info.host
        properties = discovery_info.properties
        if uid := properties.get("uid"):
            await self.async_set_unique_id(str(uid))
            self._abort_if_unique_id_configured(updates={"host": self._host})
        self.context["title_placeholders"] = {"name": NAME}
        return await self.async_step_user()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors = {}
        if user_input:
            stage = "discovery"
            try:
                self._host = normalize_host(user_input["host"])
                self._port = int(user_input["port"])
                context = await self.hass.async_add_executor_job(tls_context)
                self._api = FreeboxClient(async_get_clientsession(self.hass), context, self._host, self._port)
                version = await self._api.discover()
                await self.async_set_unique_id(version.uid)
                if self._mode == "user":
                    self._abort_if_unique_id_configured()
                else:
                    existing = self._get_reauth_entry() if self._mode == "reauth" else self._get_reconfigure_entry()
                    if version.uid != existing.unique_id:
                        return self.async_abort(reason="wrong_freebox")
                # Keep the application identity below 32 characters for Freebox compatibility.
                self._app_id = f"fr.freeboxha.{uuid.uuid4().hex[:16]}"
                stage = "authorization"
                self._app_token, self._track_id = await self._api.authorize(self._app_id)
                self._pair_task = self.hass.async_create_task(self._track(), "Freebox LCD pairing")
                return await self.async_step_pair()
            except FreeboxError as err:
                errors["base"] = err.code if err.code in CONNECTION_ERRORS else "cannot_connect"
                _LOGGER.warning("Freebox pairing failed: stage=%s code=%s", stage, err.code)
            except ValueError:
                errors["base"] = "cannot_connect"
                _LOGGER.warning("Freebox pairing failed: invalid address or port")
        return self.async_show_form(
            step_id="user",
            description_placeholders={"version": VERSION},
            data_schema=vol.Schema(
                {
                    vol.Required("host", default=self._host): str,
                    vol.Required("port", default=self._port): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                }
            ),
            errors=errors,
        )

    async def _track(self) -> str:
        try:
            async with asyncio.timeout(120):
                while self._api:
                    status = await self._api.authorization_status(self._track_id)
                    if status != "pending":
                        if status == "granted":
                            await self._api.login()
                        return status
                    await asyncio.sleep(2)
        except FreeboxError, TimeoutError:
            return "timeout"
        return "unknown"

    async def async_step_pair(self, user_input=None):
        if self._pair_task is None:
            return self.async_abort(reason="pairing_failed")
        if not self._pair_task.done():
            return self.async_show_progress(step_id="pair", progress_action="pairing", progress_task=self._pair_task)
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_finish(self, user_input=None):
        if not self._pair_task or self._pair_task.result() != "granted":
            reason = "denied" if self._pair_task and self._pair_task.result() == "denied" else "pairing_failed"
            return self.async_abort(reason=reason)
        data = {"host": self._host, "port": self._port, "app_id": self._app_id, "app_token": self._app_token}
        if self._api:
            await self._api.close()
        if self._mode == "reauth":
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        if self._mode == "reconfigure":
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=data, reason="reconfigure_successful"
            )
        return self.async_create_entry(title=NAME, data=data)

    async def async_step_reauth(self, entry_data):
        self._mode = "reauth"
        self._host = entry_data["host"]
        self._port = entry_data.get("port", DEFAULT_PORT)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is not None:
            return await self.async_step_user({"host": self._host, "port": self._port})
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({}))

    async def async_step_reconfigure(self, user_input=None):
        self._mode = "reconfigure"
        existing = self._get_reconfigure_entry()
        self._host = existing.data["host"]
        self._port = existing.data.get("port", DEFAULT_PORT)
        return await self.async_step_user(user_input)

    @callback
    def async_remove(self) -> None:
        if self._pair_task and not self._pair_task.done():
            self._pair_task.cancel()
        if self._api:
            self.hass.async_create_task(self._api.close(), "Freebox pairing cleanup")
        super().async_remove()


class FreeboxOptionsFlow(config_entries.OptionsFlow):
    @property
    def values(self) -> dict[str, Any]:
        return {**DEFAULT_OPTIONS, **self.config_entry.options}

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init", menu_options=["essential", "categories", "intervals", "alerts", "privacy", "capabilities"]
        )

    def _save(self, user_input):
        profile_changed = any(
            key in user_input and user_input[key] != self.values[key]
            for key in ("advanced_metrics", "detailed_devices")
        )
        data = {**self.values, **user_input}
        if profile_changed:
            data["apply_entity_defaults"] = True
        return self.async_create_entry(title="", data=data)

    async def async_step_essential(self, user_input=None):
        if user_input is not None:
            return self._save(
                {
                    "families": list(DEFAULT_OPTIONS["families"]),
                    "advanced_metrics": False,
                    "detailed_devices": False,
                    "group_by_name": True,
                    "apply_entity_defaults": True,
                }
            )
        return self.async_show_form(step_id="essential", data_schema=vol.Schema({}))

    async def async_step_categories(self, user_input=None):
        if user_input is not None:
            return self._save(user_input)
        return self.async_show_form(
            step_id="categories",
            data_schema=vol.Schema(
                {
                    vol.Required("families", default=self.values["families"]): SelectSelector(
                        SelectSelectorConfig(options=list(FAMILIES), multiple=True, translation_key="families")
                    ),
                    vol.Required("detailed_devices", default=self.values["detailed_devices"]): bool,
                    vol.Required("advanced_metrics", default=self.values["advanced_metrics"]): bool,
                    vol.Required("group_by_name", default=self.values["group_by_name"]): bool,
                    vol.Required("websocket", default=self.values["websocket"]): bool,
                }
            ),
        )

    async def async_step_intervals(self, user_input=None):
        if user_input is not None:
            return self._save(user_input)
        schema = {
            vol.Required(f"interval_{name}", default=self.values[f"interval_{name}"]): vol.All(
                vol.Coerce(int), vol.Range(min=5, max=3600)
            )
            for name in FAMILIES
        }
        return self.async_show_form(step_id="intervals", data_schema=vol.Schema(schema))

    async def async_step_alerts(self, user_input=None):
        if user_input is not None:
            return self._save(user_input)
        schema: dict[Any, Any] = {}
        for key in (
            "disconnect_delay",
            "wifi_disconnect_delay",
            "event_delay",
            "alert_delay",
            "wifi_signal_hysteresis",
            "temperature_hysteresis",
            "fibre_rx_hysteresis",
        ):
            schema[vol.Required(key, default=self.values[key])] = vol.All(vol.Coerce(int), vol.Range(min=0, max=3600))
        for key in ("wifi_signal_threshold", "temperature_threshold", "fibre_rx_threshold"):
            schema[vol.Required(key, default=self.values[key])] = vol.All(
                vol.Coerce(float), vol.Range(min=-200, max=200)
            )
        schema[vol.Required("events_enabled", default=self.values["events_enabled"])] = bool
        schema[vol.Required("fibre_power_unit", default=self.values["fibre_power_unit"])] = SelectSelector(
            SelectSelectorConfig(options=["hundredths_dbm", "dbm"], translation_key="fibre_power_unit")
        )
        return self.async_show_form(step_id="alerts", data_schema=vol.Schema(schema))

    async def async_step_privacy(self, user_input=None):
        if user_input is not None:
            minutes = user_input.pop("debug_minutes", 0)
            user_input["debug_until"] = time.time() + int(minutes) * 60 if minutes else 0
            return self._save(user_input)
        schema: dict[Any, Any] = {
            vol.Required(key, default=self.values[key]): bool
            for key in ("expose_identity", "event_identity", "track_new_devices", "unknown_metrics")
        }
        schema[vol.Required("history_size", default=self.values["history_size"])] = vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        )
        schema[vol.Required("debug_minutes", default=0)] = vol.All(vol.Coerce(int), vol.Range(min=0, max=60))
        return self.async_show_form(step_id="privacy", data_schema=vol.Schema(schema))

    async def async_step_capabilities(self, user_input=None):
        if user_input is not None:
            return await self.async_step_init()
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator:
            counts = {
                status: sum(c.status == status for c in coordinator.collectors.capabilities.values())
                for status in ("supported", "unsupported", "forbidden", "error")
            }
            summary = "; ".join(f"{key}: {value}" for key, value in counts.items())
            version = coordinator.api.version.version if coordinator.api.version else "unknown"
        else:
            summary, version = "Integration not loaded", "unknown"
        return self.async_show_form(
            step_id="capabilities",
            data_schema=vol.Schema({}),
            description_placeholders={"summary": summary, "api_version": version},
        )
