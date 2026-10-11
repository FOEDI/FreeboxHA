"""Debounced transitions from fresh observations, never from API outages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .const import EVENT_PREFIX
from .inventory import Inventory
from .metrics import number
from .models import Model
from .privacy import anonymous_id


@dataclass(slots=True)
class Pending:
    value: Any
    since: float
    samples: int = 1


class EventEngine:
    def __init__(self, inventory: Inventory, options: dict[str, Any], salt: str) -> None:
        self.inventory = inventory
        self.options = options
        self.salt = salt
        self.baseline: dict[str, Any] = {}
        self.sources: dict[str, str] = {}
        self.pending: dict[str, Pending] = {}
        self.known = set(inventory.devices)
        self.started = False
        self.alerts: dict[str, bool] = {}

    def invalidate(self, endpoint: str | None = None) -> None:
        for key in set(self.baseline) | set(self.alerts) | set(self.pending) | set(self.sources):
            if endpoint is None or self.sources.get(key) == endpoint:
                self.baseline.pop(key, None)
                self.alerts.pop(key, None)
                self.pending.pop(key, None)
                self.sources.pop(key, None)

    def payload(self, event: str, key: str, old: Any, new: Any, now: float) -> dict[str, Any]:
        stamp = datetime.fromtimestamp(now, UTC).isoformat()
        # Preserve the full stable subject key for a port/metric, and a device key for clients.
        subject = key
        device_key = next(
            (candidate for candidate in self.inventory.devices if key == candidate or key.startswith(candidate + ":")),
            None,
        )
        if device_key:
            subject = device_key
        result = {
            "event_type": EVENT_PREFIX + event,
            "device_id": subject,
            "old_value": old,
            "new_value": new,
            "timestamp": stamp,
        }
        if device_key:
            device = self.inventory.devices[device_key]
            if self.options["event_identity"]:
                result.update(mac=device.mac, name=device.name)
            else:
                result["device_id"] = anonymous_id(device_key, self.salt)
                if event == "device_ip_changed":
                    result["old_value"] = "redacted"
                    result["new_value"] = "redacted"
            if event == "device_connected":
                device.last_connected = now
            if event == "device_disconnected":
                device.last_disconnected = now
            self.inventory.history(
                device_key,
                {"type": event, "timestamp": stamp, "old": result["old_value"], "new": result["new_value"]},
                int(self.options["history_size"]),
            )
        return result

    def _settled(self, key: str, value: Any, now: float, delay: float) -> bool:
        pending = self.pending.get(key)
        if pending is None or pending.value != value:
            self.pending[key] = Pending(value, now)
            return False
        pending.samples += 1
        return pending.samples >= 2 and now - pending.since >= delay

    def update(self, model: Model, healthy: set[str], changed: set[str], now: float) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for source in set(self.sources.values()) - healthy:
            self.invalidate(source)
        current = set(self.inventory.devices)
        if not self.started:
            self.known.update(current)
        elif self.options["track_new_devices"]:
            for key in sorted(current - self.known):
                device = self.inventory.devices[key]
                if device.online is True and key in model.observed_devices:
                    events.append(self.payload("device_discovered", key, None, True, now))
                    self.known.add(key)
        for key, (value, source) in model.observations.items():
            if value is None:
                self.baseline.pop(key, None)
                self.pending.pop(key, None)
                self.sources.pop(key, None)
                continue
            if source not in healthy or source not in changed:
                continue
            self.sources[key] = source
            if key not in self.baseline:
                self.baseline[key] = value
                continue
            old = self.baseline[key]
            if old == value:
                self.pending.pop(key, None)
                continue
            delay = (
                (
                    self.options.get("wifi_disconnect_delay", 10)
                    if source.endswith("/stations/") or source == "wifi/ap/"
                    else self.options["disconnect_delay"]
                )
                if key.endswith(":online") and value is False
                else self.options["event_delay"]
            )
            if not self._settled(key, value, now, delay):
                continue
            self.pending.pop(key, None)
            self.baseline[key] = value
            suffix = key.rsplit(":", 1)[-1]
            event = None
            if suffix == "online":
                event = "device_connected" if value else "device_disconnected"
            elif suffix == "ip":
                event = "device_ip_changed"
            elif suffix == "connection":
                event = "device_connection_changed"
            elif suffix == "ap":
                event = "wifi_client_roamed"
            elif suffix == "band":
                event = "wifi_band_changed"
            elif key.startswith("port:") and suffix == "link":
                event = "ethernet_link_up" if value else "ethernet_link_down"
            elif key == "wan:connected":
                event = "wan_reconnected" if value else "wan_disconnected"
            if event:
                events.append(self.payload(event, key, old, value, now))

        for metric in model.metrics.values():
            value = number(metric.value)
            if value is None or metric.endpoint not in changed or metric.endpoint not in healthy:
                continue
            event, threshold, hysteresis, low = None, 0.0, 0.0, False
            if metric.family == "wifi_clients" and metric.key.endswith(":wifi.signal"):
                event, threshold, hysteresis, low = (
                    "wifi_signal_low",
                    self.options["wifi_signal_threshold"],
                    self.options["wifi_signal_hysteresis"],
                    True,
                )
            elif metric.device_class == "temperature" and metric.family == "system":
                event, threshold, hysteresis = (
                    "system_temperature_high",
                    self.options["temperature_threshold"],
                    self.options["temperature_hysteresis"],
                )
            elif metric.key == "fibre:sfp_pwr_rx":
                event, threshold, hysteresis, low = (
                    "fibre_signal_warning",
                    self.options["fibre_rx_threshold"],
                    self.options["fibre_rx_hysteresis"],
                    True,
                )
            if event is None:
                continue
            key = f"alert:{metric.key}"
            self.sources[key] = metric.endpoint
            active = self.alerts.get(key, False)
            bad = value < threshold if low else value > threshold
            recovered = value >= threshold + hysteresis if low else value <= threshold - hysteresis
            if active:
                if recovered:
                    self.alerts[key] = False
                continue
            if not bad:
                self.pending.pop(key, None)
                continue
            # Candidate value is the condition, not the fluctuating reading.
            if self._settled(key, True, now, self.options["alert_delay"]):
                self.alerts[key] = True
                self.pending.pop(key, None)
                payload = self.payload(event, metric.device, None, value, now)
                payload.update(metric=metric.key, threshold=threshold, unit=metric.unit)
                events.append(payload)
        self.started = True
        return events if self.options["events_enabled"] else []
