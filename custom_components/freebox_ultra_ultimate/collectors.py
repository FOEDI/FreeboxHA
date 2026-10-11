"""Family-isolated read-only collection and dependent endpoint discovery."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from .api import AuthenticationError, EndpointUnavailable, FreeboxClient, FreeboxError, PermissionDenied
from .capabilities import Capability
from .const import FAMILIES, is_network_list
from .privacy import strip_secrets


@dataclass(slots=True)
class Snapshot:
    value: dict[str, Any] | list[Any]
    updated: float
    family: str


class Collectors:
    """Cache successful endpoints; publish failures separately from data."""

    def __init__(self, api: FreeboxClient) -> None:
        self.api = api
        self.snapshots: dict[str, Snapshot] = {}
        self.capabilities: dict[str, Capability] = {}
        self.fresh: set[str] = set()
        self.changed: set[str] = set()
        self.due: dict[str, float] = {}
        self.auth_error: AuthenticationError | None = None

    async def fetch(self, path: str, shape: str, family: str) -> Any:
        cap = self.capabilities.setdefault(path, Capability())
        if cap.next_retry > time.monotonic():
            return None
        started = time.monotonic()
        now = time.time()
        cap.last_attempt = now
        try:
            result = await self.api.get(path)
            cap.response_type = type(result).__name__
            # Freebox firmware may encode an empty host/station collection as {}
            # or null. Restrict compatibility to successful network-list reads.
            if shape == "list" and is_network_list(path) and (result is None or result == {}):
                result = []
            if not isinstance(result, dict if shape == "object" else list):
                raise FreeboxError("invalid_shape")
            # Do not silently truncate inventory: incomplete lists must never imply absence.
            if isinstance(result, list) and len(result) > 2048:
                raise FreeboxError("collection_limit")
            cleaned = strip_secrets(result)
            cap.success(cleaned, time.monotonic() - started, now)
            self.snapshots[path] = Snapshot(cleaned, now, family)
            self.changed.add(path)
            return cleaned
        except AuthenticationError as err:
            self.auth_error = err
            cap.fail("authentication", err.code, now)
        except PermissionDenied as err:
            cap.fail("forbidden", err.code, now)
        except EndpointUnavailable as err:
            cap.fail("unsupported", err.code, now)
        except FreeboxError as err:
            cap.fail("error", err.code, now)
        return None

    async def family(self, name: str) -> None:
        definition = FAMILIES[name]
        values = await asyncio.gather(*(self.fetch(path, shape, name) for path, shape in definition.endpoints))
        if any(value is not None for value in values):
            self.fresh.add(name)
        root = values[0]
        tasks = []
        child_paths: set[str] = set()

        def queue(path: str, shape: str) -> None:
            child_paths.add(path)
            tasks.append(self.fetch(path, shape, name))

        if name == "presence" and isinstance(root, list):
            for interface in root:
                if isinstance(interface, dict) and isinstance(interface.get("name"), str):
                    path = f"lan/browser/{quote(interface['name'], safe='')}/"
                    queue(path, "list")
        if name in {"wifi_clients", "wifi_environment", "wifi_radios"} and isinstance(root, list):
            for ap in root:
                if not isinstance(ap, dict) or not isinstance(ap.get("id"), (str, int)):
                    continue
                ap_id = quote(str(ap["id"]), safe="")
                suffixes = (
                    ("stations/",)
                    if name == "wifi_clients"
                    else ("channel_usage/", "neighbors/")
                    if name == "wifi_environment"
                    else ("",)
                )
                for suffix in suffixes:
                    queue(f"wifi/ap/{ap_id}/{suffix}", "object" if not suffix else "list")
        if name == "ethernet" and isinstance(root, list):
            for port in root:
                if isinstance(port, dict) and isinstance(port.get("id"), (str, int)):
                    port_id = quote(str(port["id"]), safe="")
                    queue(f"switch/port/{port_id}/stats", "object")
                    queue(f"switch/port/{port_id}", "object")
        if tasks:
            await asyncio.gather(*tasks)
        if name in {"presence", "wifi_clients", "wifi_environment", "wifi_radios", "ethernet"}:
            roots = {path for path, _ in definition.endpoints}
            for path, snapshot in self.snapshots.items():
                if snapshot.family == name and path not in roots and path not in child_paths:
                    # Failed discovery or removed child: retain history, revoke cached freshness.
                    self.capabilities[path].status = "stale"
                    self.capabilities[path].error = "discovery_unavailable" if root is None else "discovery_removed"

    async def update(self, options: dict[str, Any], forced: set[str] | None = None) -> set[str]:
        self.fresh.clear()
        self.changed.clear()
        self.auth_error = None
        now = time.monotonic()
        names = [
            name
            for name in options["families"]
            if name in FAMILIES and (self.due.get(name, 0) <= now or name in (forced or set()))
        ]
        # Families sharing AP discovery execute sequentially, with a per-cycle cache.
        original_fetch = self.fetch
        cycle: dict[str, asyncio.Task[Any]] = {}

        async def cached(path: str, shape: str, family: str) -> Any:
            if path not in cycle:
                cycle[path] = asyncio.create_task(original_fetch(path, shape, family))
            return await cycle[path]

        self.fetch = cached  # type: ignore[method-assign]
        try:
            await asyncio.gather(*(self.family(name) for name in names))
        finally:
            self.fetch = original_fetch  # type: ignore[method-assign]
        for name in names:
            self.due[name] = now + max(5, int(options[f"interval_{name}"]))
        return set(names)

    def healthy(self, path: str) -> bool:
        return path in self.snapshots and self.capabilities[path].status == "supported"

    def invalidate(self) -> None:
        """Reprobe firmware capabilities after an observed reboot."""
        for cap in self.capabilities.values():
            cap.next_retry = 0
        self.due.clear()
