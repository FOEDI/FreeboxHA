"""Descriptions and conversions with explicit source units."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .const import FAMILIES
from .privacy import PRIVATE_KEY, SECRET_KEY


@dataclass(slots=True)
class Device:
    key: str
    name: str
    manufacturer: str = "Freebox SAS"
    model: str | None = None
    firmware: str | None = None
    hardware: str | None = None
    parent: str | None = "box"


@dataclass(slots=True)
class Metric:
    key: str
    device: str
    name: str
    value: Any
    endpoint: str
    family: str
    platform: str = "sensor"
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    diagnostic: bool = False
    enabled: bool = True
    cached: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except TypeError, ValueError, OverflowError:
        return None
    return result if math.isfinite(result) else None


def timestamp(value: Any) -> datetime | None:
    if (parsed := number(value)) is None or parsed <= 0:
        return None
    try:
        return datetime.fromtimestamp(parsed, UTC)
    except ValueError, OverflowError, OSError:
        return None


# (unit, device_class, state_class, multiplier). Direction is always Freebox perspective.
KNOWN: dict[str, tuple[str | None, str | None, str | None, float]] = {
    "rate_down": ("Mbit/s", "data_rate", "measurement", 8 / 1_000_000),
    "rate_up": ("Mbit/s", "data_rate", "measurement", 8 / 1_000_000),
    "bandwidth_down": ("Mbit/s", "data_rate", "measurement", 1 / 1_000_000),
    "bandwidth_up": ("Mbit/s", "data_rate", "measurement", 1 / 1_000_000),
    "bytes_down": ("B", "data_size", "total_increasing", 1),
    "bytes_up": ("B", "data_size", "total_increasing", 1),
    "rx_rate": ("Mbit/s", "data_rate", "measurement", 8 / 1_000_000),
    "tx_rate": ("Mbit/s", "data_rate", "measurement", 8 / 1_000_000),
    "rx_bytes_rate": ("Mbit/s", "data_rate", "measurement", 8 / 1_000_000),
    "tx_bytes_rate": ("Mbit/s", "data_rate", "measurement", 8 / 1_000_000),
    "rx_packets_rate": ("packets/s", None, "measurement", 1),
    "tx_packets_rate": ("packets/s", None, "measurement", 1),
    "rx_bytes": ("B", "data_size", "total_increasing", 1),
    "rx_good_bytes": ("B", "data_size", "total_increasing", 1),
    "rx_bad_bytes": ("B", "data_size", "total_increasing", 1),
    "tx_bytes": ("B", "data_size", "total_increasing", 1),
    "total_bytes": ("B", "data_size", "measurement", 1),
    "free_bytes": ("B", "data_size", "measurement", 1),
    "used_bytes": ("B", "data_size", "measurement", 1),
    "uptime_val": ("s", "duration", "measurement", 1),
    "conn_duration": ("s", "duration", "measurement", 1),
    "inactive": ("s", "duration", "measurement", 1),
    "idle_duration": ("s", "duration", "measurement", 1),
    "active_duration": ("s", "duration", "measurement", 1),
    "time_before_spindown": ("s", "duration", "measurement", 1),
    "signal": ("dB", None, "measurement", 1),
    "noise_level": ("dB", None, "measurement", 1),
    "rx_busy_percent": ("%", None, "measurement", 1),
}
STRING_FIELDS = {
    "state",
    "status",
    "type",
    "media",
    "mode",
    "duplex",
    "band",
    "link_type",
    "model",
    "board_name",
    "firmware_version",
    "box_flavor",
    "disk_status",
    "fstype",
    "fsck_result",
    "table_type",
    "connector",
    "primary_channel",
    "secondary_channel",
    "channel",
    "width",
    "channel_width",
    "mcs",
    "vht_mcs",
    "he_mcs",
    "eht_mcs",
    "nss",
    "spatial_streams",
    "standard",
    "sfp_model",
    "sfp_vendor",
    "version",
    "ipv4",
    "ipv6",
    "ipv6ll",
    "prefix",
    "next_hop",
    "ip",
    "netmask",
    "netmask_v4",
    "ip_range_start",
    "ip_range_end",
    "dns",
    "dns1",
    "dns2",
    "domain",
    "hostname",
    "ssid",
    "bssid",
}
COUNTERS = {
    "rx_good_packets",
    "rx_err_packets",
    "rx_fcs_packets",
    "rx_fragments_packets",
    "rx_jabber_packets",
    "rx_oversize_packets",
    "rx_undersize_packets",
    "rx_broadcast_packets",
    "rx_multicast_packets",
    "rx_unicast_packets",
    "tx_packets",
    "tx_broadcast_packets",
    "tx_multicast_packets",
    "tx_unicast_packets",
    "tx_collisions",
    "tx_deferred",
    "tx_excessive",
    "tx_fcs",
    "tx_late",
    "tx_multiple",
    "tx_pause",
    "tx_single",
    "rx_pause",
}


def flatten(value: dict[str, Any], prefix: str = "", depth: int = 0) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if depth > 5:
        return result
    for key, item in list(value.items())[:128]:
        path = f"{prefix}.{key}".lstrip(".")
        if SECRET_KEY.search(key):
            continue
        if isinstance(item, dict):
            result.update(flatten(item, path, depth + 1))
        elif isinstance(item, (str, int, float, bool)):
            result[path] = item
    return result


def describe(device: str, path: str, value: Any, endpoint: str, family: str, options: dict[str, Any]) -> Metric | None:
    leaf = path.split(".")[-1]
    if SECRET_KEY.search(leaf) or (not options["expose_identity"] and PRIVATE_KEY.search(leaf)):
        return None
    metric = Metric(f"{device}:{path}", device, path.replace(".", " ").replace("_", " "), value, endpoint, family)
    if isinstance(value, bool):
        metric.platform = "binary_sensor"
        return metric
    known = KNOWN.get(leaf)
    if leaf in COUNTERS:
        known = ("packets" if "packets" in leaf else "events", None, "total_increasing", 1)
    if family == "system" and leaf.startswith("temp_") or family == "storage" and leaf == "temp":
        known = ("°C", "temperature", "measurement", 1)
    if family == "system" and "fan" in leaf and "rpm" in leaf:
        known = ("rpm", None, "measurement", 1)
    if leaf in {
        "primary_channel",
        "secondary_channel",
        "channel",
        "mcs",
        "vht_mcs",
        "he_mcs",
        "eht_mcs",
        "nss",
        "spatial_streams",
    }:
        known = (None, None, None, 1)
    if leaf in {"channel_width", "width"}:
        known = ("MHz", None, "measurement", 1)
    if family == "ethernet" and leaf == "speed":
        known = ("Mbit/s", "data_rate", "measurement", 1)
    if path.endswith(("last_rx.bitrate", "last_tx.bitrate")):
        known = ("Mbit/s", "data_rate", "measurement", 0.1)
        metric.name += " PHY"
    if family == "fibre" and leaf in {"sfp_pwr_rx", "sfp_pwr_tx"}:
        known = (
            "dBm",
            "signal_strength",
            "measurement",
            0.01 if options["fibre_power_unit"] == "hundredths_dbm" else 1,
        )
    if known:
        parsed = number(value)
        if parsed is None or (
            parsed < 0 and leaf in {"bitrate", "mcs", "vht_mcs", "he_mcs", "eht_mcs", "nss", "speed"}
        ):
            return None
        metric.unit, metric.device_class, metric.state_class, multiplier = known
        metric.value = round(parsed * multiplier, 6)
        return metric
    if isinstance(value, str) and leaf in STRING_FIELDS and len(value) <= 255:
        metric.diagnostic = family in {"network", "routing", "services", "dhcp"}
        return metric
    if options["unknown_metrics"] and isinstance(value, (int, float)) and number(value) is not None:
        metric.enabled = False
        metric.diagnostic = True
        metric.attributes = {"source_field": path, "unit_verified": False}
        return metric
    return None


def essential_metric(metric: Metric) -> bool:
    """Keep one client tracker and a small set of operational box metrics."""
    if metric.device.startswith(("mac:", "host:")):
        return metric.platform == "device_tracker"
    definition = FAMILIES.get(metric.family)
    if definition and not definition.enabled:
        return True
    if metric.key in {
        "wan:connected",
        "wan:rate_down",
        "wan:rate_up",
        "fibre:link",
        "fibre:sfp_pwr_rx",
        "box:uptime_val",
        "box:diagnostic:failed_endpoints",
    }:
        return True
    if metric.family == "system" and metric.device_class == "temperature":
        return True
    if metric.device.startswith("port:"):
        return metric.key.rsplit(":", 1)[-1] in {"link", "speed", "stats.rx_bytes_rate", "stats.tx_bytes_rate"}
    if metric.device.startswith("ap:"):
        return metric.key.rsplit(":", 1)[-1] in {"active", "clients"}
    return False
