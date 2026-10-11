"""Export operational health, field names and counts; no raw API responses."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import FAMILIES
from .privacy import anonymous_id


def safe_path(path: str, salt: str) -> str:
    """Keep known endpoint names and replace dynamic identifiers."""
    static = {
        part for definition in FAMILIES.values() for endpoint, _ in definition.endpoints for part in endpoint.split("/")
    }
    static.update({"stations", "channel_usage", "neighbors", "port", "stats"})
    return "/".join(part if not part or part in static else anonymous_id(part, salt) for part in path.split("/"))


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    salt = entry.entry_id
    endpoints = {}
    for path, cap in coordinator.collectors.capabilities.items():
        export = cap.export()
        # API field names can be firmware controlled: allow schema names, never arbitrary strings.
        export["fields"] = [field for field in export["fields"] if re.fullmatch(r"[a-zA-Z0-9_.\[\]-]{1,128}", field)]
        export["unknown_fields"] = [
            field
            for field in coordinator.model.unknown_fields.get(path, [])
            if re.fullmatch(r"[a-zA-Z0-9_.\[\]-]{1,128}", field)
        ]
        endpoints[safe_path(path, salt)] = export
    return {
        "api_version": coordinator.api.version.version if coordinator.api.version else None,
        "box_id": anonymous_id(coordinator.api.version.uid if coordinator.api.version else "unknown", salt),
        "enabled_families": coordinator.options["families"],
        "permissions": {
            key: value
            for key, value in coordinator.api.permissions.items()
            if key in {"settings", "downloader", "parental", "explorer", "pvr", "calls", "contacts"}
        },
        "endpoints": endpoints,
        "tracked_devices": len(coordinator.inventory.devices),
        "group_by_name": coordinator.options["group_by_name"],
        "known_network_identities": sum(
            len(device.member_keys) or 1 for device in coordinator.inventory.devices.values()
        ),
        "created_entities": coordinator.entity_count,
        "generated_metrics": len(coordinator.model.metrics),
        "observed_reboots": coordinator.reboot_count,
        "websocket_status": coordinator.websocket_status,
        "intervals": {name: coordinator.options[f"interval_{name}"] for name in coordinator.options["families"]},
        "limitations": [
            "GET only; no active radio scans or configuration controls",
            "Same-name grouping is enabled only by configuration; remembered MAC aliases retain the canonical identity",
            "Wi-Fi signal is documented as dB attenuation, not a verified dBm RSSI",
            "FTTH power uses documented hundredths of dBm unless explicitly configured otherwise",
            "New/unknown fields require unit verification before statistics are enabled",
            "WebSocket subscriptions are firmware dependent; polling remains active",
            "Cached Wi-Fi radar results are not refreshed by a scan",
        ],
    }
