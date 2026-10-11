"""Persistent identities and bounded network observations."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any

MAC_RE = re.compile(r"^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")


def normalize_mac(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.lower().replace("-", ":")
    return value if MAC_RE.fullmatch(value) else None


def host_mac(host: dict[str, Any]) -> str | None:
    direct = normalize_mac(host.get("mac"))
    if direct:
        return direct
    identifiers = host.get("l2ident", [])
    if isinstance(identifiers, dict):
        identifiers = [identifiers]
    if isinstance(identifiers, list):
        for identifier in identifiers:
            if isinstance(identifier, dict) and (mac := normalize_mac(identifier.get("id"))):
                return mac
    return normalize_mac(str(host.get("id", "")).removeprefix("ether-"))


def identity(host: dict[str, Any], interface: str) -> str | None:
    if mac := host_mac(host):
        return f"mac:{mac}"
    if isinstance(host.get("id"), (str, int)):
        return f"host:{interface}:{host['id']}"
    return None


def addresses(host: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ipv4: set[str] = set()
    ipv6: set[str] = set()
    for item in host.get("l3connectivities", []) if isinstance(host.get("l3connectivities"), list) else []:
        if not isinstance(item, dict):
            continue
        try:
            parsed = ipaddress.ip_address(item.get("addr", ""))
        except ValueError, TypeError:
            continue
        (ipv4 if parsed.version == 4 else ipv6).add(str(parsed))
    return tuple(sorted(ipv4)), tuple(sorted(ipv6))


@dataclass(slots=True)
class NetworkDevice:
    key: str
    mac: str | None = None
    name: str = "Network device"
    vendor: str | None = None
    host_type: str | None = None
    freebox_id: str | None = None
    interfaces: tuple[str, ...] = ()
    ipv4: tuple[str, ...] = ()
    ipv6: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    dhcp_name: str | None = None
    reserved: bool | None = None
    lease: dict[str, Any] = field(default_factory=dict)
    online: bool | None = None
    connection: str | None = None
    switch_port: str | None = None
    ap_id: str | None = None
    band: str | None = None
    first_seen: float = 0
    last_seen: float | None = None
    last_activity: float | None = None
    last_connected: float | None = None
    last_disconnected: float | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    source_paths: tuple[str, ...] = ()
    wifi: dict[str, Any] = field(default_factory=dict)
    member_keys: tuple[str, ...] = ()

    @property
    def private_mac(self) -> bool | None:
        return bool(int(self.mac[:2], 16) & 2) if self.mac else None

    def export(self) -> dict[str, Any]:
        # Never store full station data or session data; inventory is local HA storage.
        return {
            key: getattr(self, key)
            for key in (
                "key",
                "mac",
                "name",
                "vendor",
                "host_type",
                "freebox_id",
                "interfaces",
                "ipv4",
                "ipv6",
                "names",
                "dhcp_name",
                "reserved",
                "first_seen",
                "last_seen",
                "last_activity",
                "last_connected",
                "last_disconnected",
                "history",
                "member_keys",
            )
        }


class Inventory:
    def __init__(self, group_by_name: bool = False) -> None:
        self.devices: dict[str, NetworkDevice] = {}
        self.initialized = False
        self.group_by_name = group_by_name
        self.aliases: dict[str, str] = {}
        self._names: dict[str, str] = {}

    @staticmethod
    def name_key(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        value = " ".join(value.split()).casefold()
        return value if value and value != "network device" else None

    def resolve(self, key: str) -> str:
        return self.aliases.get(key, key) if self.group_by_name else key

    def resolve_host(self, host: dict[str, Any], interface: str) -> str | None:
        key = identity(host, interface)
        if key is None:
            return None
        if self.group_by_name:
            if key in self.aliases:
                return self.aliases[key]
            name = self.name_key(host.get("primary_name") or host.get("hostname"))
            if name and name in self._names:
                return self._names[name]
        return key

    def configure(self, group_by_name: bool) -> None:
        if self.group_by_name == group_by_name:
            return
        saved = self.export()
        self.group_by_name = group_by_name
        self.devices.clear()
        self.aliases.clear()
        self._names.clear()
        self.restore(saved)

    def restore(self, payload: dict[str, Any]) -> None:
        items = payload.get("devices", [])
        if not isinstance(items, list):
            return
        items = [item for item in items if isinstance(item, dict) and isinstance(item.get("key"), str)]
        # Keep the oldest persisted identity so regrouping preserves an existing tracker ID.
        for item in sorted(items, key=lambda value: (value.get("first_seen") or 0, value["key"])):
            allowed = {key: value for key, value in item.items() if key in NetworkDevice.__dataclass_fields__}
            for attribute in ("interfaces", "ipv4", "ipv6", "names", "member_keys"):
                allowed[attribute] = tuple(allowed.get(attribute, ()))
            allowed["online"] = None
            allowed["history"] = allowed.get("history", [])[-100:]
            members = tuple(sorted(set(allowed["member_keys"]) | {item["key"]}))
            name = self.name_key(item.get("name"))
            key = self._names.get(name, item["key"]) if self.group_by_name and name else item["key"]
            keys = [key] if self.group_by_name else list(members)
            for key in keys:
                if key in self.devices:
                    device = self.devices[key]
                    for attribute in ("interfaces", "ipv4", "ipv6", "names", "member_keys"):
                        setattr(
                            device, attribute, tuple(sorted(set(getattr(device, attribute)) | set(allowed[attribute])))
                        )
                    device.member_keys = tuple(sorted(set(device.member_keys) | set(members)))
                    for attribute in ("last_seen", "last_activity", "last_connected", "last_disconnected"):
                        timestamps = [
                            value
                            for value in (getattr(device, attribute), item.get(attribute))
                            if isinstance(value, (int, float))
                        ]
                        setattr(device, attribute, max(timestamps) if timestamps else None)
                    device.history = sorted(
                        device.history + allowed["history"], key=lambda event: event.get("timestamp", "")
                    )[-100:]
                else:
                    values = {**allowed, "key": key, "member_keys": members if self.group_by_name else (key,)}
                    if not self.group_by_name and key.startswith("mac:"):
                        values["mac"] = normalize_mac(key[4:])
                    self.devices[key] = NetworkDevice(**values)
                if self.group_by_name:
                    self.aliases.update({member: key for member in members})
                    if name:
                        self._names[name] = key

    def upsert(self, host: dict[str, Any], interface: str, path: str, now: float) -> NetworkDevice | None:
        key = self.resolve_host(host, interface)
        if key is None:
            return None
        device = self.devices.setdefault(key, NetworkDevice(key=key, first_seen=now))
        raw_key = identity(host, interface)
        assert raw_key is not None
        device.member_keys = tuple(sorted(set(device.member_keys) | {raw_key}))
        if self.group_by_name:
            self.aliases[raw_key] = key
        device.mac = device.mac or host_mac(host)
        device.freebox_id = str(host["id"]) if "id" in host else device.freebox_id
        device.name = str(host.get("primary_name") or host.get("hostname") or device.name)[:128]
        if self.group_by_name and (name := self.name_key(device.name)):
            self._names[name] = key
        device.vendor = host.get("vendor_name") or device.vendor
        device.host_type = host.get("host_type") or device.host_type
        device.interfaces = tuple(sorted(set(device.interfaces) | {interface}))
        device.source_paths = tuple(sorted(set(device.source_paths) | {path}))
        if "l3connectivities" in host:
            device.ipv4, device.ipv6 = addresses(host)
        if isinstance(host.get("names"), list):
            device.names = tuple(
                sorted({str(item["name"])[:128] for item in host["names"] if isinstance(item, dict) and "name" in item})
            )
            for item in host["names"]:
                if isinstance(item, dict) and item.get("source") == "dhcp":
                    device.dhcp_name = str(item.get("name", ""))[:128]
        if isinstance(host.get("last_activity"), (int, float)) and host["last_activity"] > 0:
            device.last_activity = host["last_activity"]
        if isinstance(host.get("active"), bool) or isinstance(host.get("reachable"), bool):
            device.online = bool(host.get("active") or host.get("reachable"))
        if device.online:
            device.last_seen = now
        return device

    def history(self, key: str, event: dict[str, Any], limit: int) -> None:
        if key in self.devices:
            self.devices[key].history.append(event)
            self.devices[key].history = self.devices[key].history[-limit:] if limit else []

    def export(self) -> dict[str, Any]:
        return {"devices": [device.export() for device in self.devices.values()]}
