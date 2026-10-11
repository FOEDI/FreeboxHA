"""Independent deadlines, persistence and optional Freebox WebSocket hints."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AuthenticationError, FreeboxClient, FreeboxError
from .collectors import Collectors
from .const import DEFAULT_OPTIONS, DOMAIN
from .events import EventEngine
from .inventory import Inventory
from .metrics import Metric
from .models import Model

_LOGGER = logging.getLogger(__name__)
WS_EVENTS = ("lan_host_l3addr_reachable", "lan_host_l3addr_unreachable")


class FreeboxCoordinator(DataUpdateCoordinator[Model]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: FreeboxClient) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(seconds=5), always_update=True
        )
        self.api = api
        self.options = {**DEFAULT_OPTIONS, **entry.options}
        self.collectors = Collectors(api)
        self.inventory = Inventory(group_by_name=self.options["group_by_name"])
        self.model = Model(self.inventory)
        self.engine = EventEngine(self.inventory, self.options, entry.entry_id)
        self.store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.inventory")
        self._last_uptime: float | None = None
        self._forced: set[str] = set()
        self._ws_task: asyncio.Task[None] | None = None
        self._event_listeners: list[Any] = []
        self.latest_events: list[dict[str, Any]] = []
        self.websocket_status = "disabled"
        self.entity_count = 0
        self._entity_keys: set[str] = set()
        self.cleaned_aliases: set[str] = set()
        self.last_event_times: dict[str, float] = {}
        self.reboot_count = 0
        self._last_inventory_save: float | None = None

    async def restore(self) -> None:
        if (saved := await self.store.async_load()) is not None:
            self.inventory.restore(saved)
            self.engine.known.update(self.inventory.devices)

    @callback
    def subscribe_events(self, listener: Any) -> Any:
        self._event_listeners.append(listener)
        return lambda: self._event_listeners.remove(listener)

    def registered(self, unique_id: str) -> None:
        self._entity_keys.add(unique_id)
        self.entity_count = len(self._entity_keys)

    async def _async_update_data(self) -> Model:
        try:
            await self.collectors.update(self.options, self._forced)
            self._forced.clear()
            if self.collectors.auth_error:
                raise ConfigEntryAuthFailed(self.collectors.auth_error.code)
            healthy = {path for path in self.collectors.snapshots if self.collectors.healthy(path)}
            self.model.build(self.collectors, self.options)
            self.inventory.initialized = True
            uptime = self.model.uptime
            if "system/" in self.collectors.changed and uptime is not None:
                if self._last_uptime is not None and uptime < self._last_uptime:
                    self.reboot_count += 1
                    self.engine.invalidate()
                    self.collectors.invalidate()
                    # Cached pre-reboot categories are untrusted until a fresh observation.
                    for path, cap in self.collectors.capabilities.items():
                        if path not in self.collectors.changed:
                            cap.status = "stale"
                    healthy = {path for path in healthy if path in self.collectors.changed}
                    self._forced.update(self.options["families"])
                self._last_uptime = uptime
            if not healthy and self.options["families"]:
                self.engine.invalidate()
                raise UpdateFailed("No readable API endpoints")
            now = time.time()
            self.latest_events = self.engine.update(self.model, healthy, self.collectors.changed, now)
            # Presence entities use the same confirmed state as connection events.
            for key, device in self.inventory.devices.items():
                stable = self.engine.baseline.get(f"{key}:online", device.online)
                for suffix in ("connected", "tracker"):
                    if device.online is not None and (metric := self.model.metrics.get(f"{key}:{suffix}")) is not None:
                        metric.value = stable
                        metric.attributes.update(
                            connected_observed=device.online, presence_pending=stable != device.online
                        )
            for event in self.latest_events:
                event["entry_id"] = self.config_entry.entry_id if self.config_entry else ""
                self.last_event_times[event["event_type"]] = now
                self.hass.bus.async_fire(
                    event["event_type"], {key: value for key, value in event.items() if key != "event_type"}
                )
                for listener in list(self._event_listeners):
                    listener(event)
            checkpoint = time.monotonic()
            if self._last_inventory_save is None or checkpoint - self._last_inventory_save >= 60:
                # Bounded checkpoints: delaying every five-second tick would postpone forever.
                await self.store.async_save(self.inventory.export())
                self._last_inventory_save = checkpoint
            self._diagnostic_metrics()
            if self.options.get("debug_until", 0) > now:
                counts = {
                    state: sum(c.status == state for c in self.collectors.capabilities.values())
                    for state in ("supported", "unsupported", "forbidden", "error")
                }
                _LOGGER.info(
                    "Temporary safe diagnostics: endpoint counts=%s; devices=%s; metrics=%s",
                    counts,
                    len(self.inventory.devices),
                    len(self.model.metrics),
                )
            _LOGGER.debug(
                "Collected %s families, %s devices, %s metrics; websocket=%s",
                len(self.collectors.fresh),
                len(self.inventory.devices),
                len(self.model.metrics),
                self.websocket_status,
            )
            return self.model
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(err.code) from err
        except FreeboxError as err:
            raise UpdateFailed(err.code) from err

    def _diagnostic_metrics(self) -> None:
        values = {
            "tracked_devices": len(self.inventory.devices),
            "created_entities": self.entity_count,
            "supported_endpoints": sum(cap.status == "supported" for cap in self.collectors.capabilities.values()),
            "failed_endpoints": sum(
                cap.status in {"error", "forbidden", "authentication"} for cap in self.collectors.capabilities.values()
            ),
            "unsupported_endpoints": sum(cap.status == "unsupported" for cap in self.collectors.capabilities.values()),
            "websocket_status": self.websocket_status,
            "observed_reboots": self.reboot_count,
            "api_version": self.api.version.version if self.api.version else "unknown",
        }
        for key, value in values.items():
            self.model.add(
                Metric(f"box:diagnostic:{key}", "box", key.replace("_", " "), value, "", "diagnostic", diagnostic=True)
            )
        for family in self.options["families"]:
            paths = [path for path, snap in self.collectors.snapshots.items() if snap.family == family]
            available = any(self.collectors.healthy(path) for path in paths)
            self.model.add(
                Metric(
                    f"box:health:{family}",
                    "box",
                    f"{family} API available",
                    available,
                    "",
                    "diagnostic",
                    "binary_sensor",
                    diagnostic=True,
                )
            )

    def start_websocket(self) -> None:
        if self.options["websocket"] and "presence" in self.options["families"]:
            self._ws_task = self.hass.async_create_background_task(self._websocket_loop(), f"{DOMAIN} websocket")

    async def _websocket_loop(self) -> None:
        backoff = 5
        while True:
            try:
                async with await self.api.open_websocket() as websocket:
                    await websocket.send_json({"action": "register", "request_id": 1, "events": list(WS_EVENTS)})
                    accepted = False
                    # A successful TCP handshake is not proof of supported subscriptions.
                    async with asyncio.timeout(10):
                        response = await websocket.receive()
                    if response.type != aiohttp.WSMsgType.TEXT:
                        raise FreeboxError("websocket_registration_failed")
                    message = json.loads(response.data)
                    if (
                        isinstance(message, dict)
                        and message.get("action") == "register"
                        and message.get("success") is True
                    ):
                        accepted = True
                    if not accepted:
                        self.websocket_status = "subscription_refused"
                        raise FreeboxError("websocket_registration_failed")
                    self.websocket_status = "subscribed"
                    backoff = 5
                    last_hint = 0.0
                    async for response in websocket:
                        if response.type != aiohttp.WSMsgType.TEXT:
                            continue
                        message = json.loads(response.data)
                        if (
                            not isinstance(message, dict)
                            or message.get("action") != "notification"
                            or message.get("success") is not True
                        ):
                            continue
                        # Hints refresh authoritative LAN data; notification content never sets presence.
                        if message.get("event") in WS_EVENTS and time.monotonic() - last_hint >= 2:
                            self._forced.add("presence")
                            if "wifi_clients" in self.options["families"]:
                                self._forced.add("wifi_clients")
                            last_hint = time.monotonic()
                            await self.async_request_refresh()
            except asyncio.CancelledError:
                raise
            except aiohttp.ClientError, FreeboxError, TimeoutError, ValueError, OSError:
                if self.websocket_status != "subscription_refused":
                    self.websocket_status = "unavailable_polling"
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)

    async def stop(self) -> None:
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None
        await self.async_shutdown()
        await self.store.async_save(self.inventory.export())
        await self.api.close()
