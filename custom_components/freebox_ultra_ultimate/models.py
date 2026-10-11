"""Build native scalar metrics and a coherent inventory from API snapshots."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from .collectors import Collectors
from .inventory import Inventory, host_mac, normalize_mac
from .metrics import Device, Metric, describe, essential_metric, flatten, number, timestamp

ROOTS = {
    "connection/": ("wan", "Internet / WAN"),
    "connection/ftth/": ("fibre", "Fibre / SFP"),
    "system/": ("box", "Freebox"),
}


class Model:
    def __init__(self, inventory: Inventory) -> None:
        self.inventory = inventory
        self.devices: dict[str, Device] = {}
        self.metrics: dict[str, Metric] = {}
        self.observations: dict[str, tuple[Any, str]] = {}
        self.observed_devices: set[str] = set()
        self.unknown_fields: dict[str, list[str]] = {}
        self.uptime: float | None = None
        self.options: dict[str, Any] = {}

    def add(self, metric: Metric) -> None:
        detailed = metric.device.startswith(("mac:", "host:")) and self.options.get("detailed_devices", False)
        metric.enabled = metric.enabled and bool(
            self.options.get("advanced_metrics", False) or detailed or essential_metric(metric)
        )
        self.metrics[metric.key] = metric

    def object(
        self,
        device: str,
        name: str,
        data: dict[str, Any],
        path: str,
        family: str,
        options: dict[str, Any],
        prefix: str = "",
    ) -> None:
        self.devices.setdefault(device, Device(device, name))
        unknown = []
        for field, value in flatten(data).items():
            if field.split(".")[-1] in {"id", "mac", "serial", "primary_name", "vendor_name", "uptime"}:
                continue
            metric = describe(device, f"{prefix}.{field}".lstrip("."), value, path, family, options)
            if metric:
                self.add(metric)
            else:
                unknown.append(field)
        self.unknown_fields[path] = sorted(set(self.unknown_fields.get(path, [])) | set(unknown))[:128]

    def build(self, collectors: Collectors, options: dict[str, Any]) -> None:
        self.options = options
        self.inventory.configure(options.get("group_by_name", True))
        self.devices = {"box": Device("box", "Freebox", parent=None)}
        self.metrics = {}
        self.observations = {}
        self.observed_devices = set()
        self.unknown_fields = {}
        snapshots = collectors.snapshots
        enabled = set(options["families"])
        ap_info: dict[str, dict[str, Any]] = {}
        bss_info: dict[str, dict[str, Any]] = {}
        for path, snapshot in snapshots.items():
            if path == "wifi/ap/" and isinstance(snapshot.value, list):
                ap_info = {str(item["id"]): item for item in snapshot.value if isinstance(item, dict) and "id" in item}
            if path.startswith("wifi/ap/") and path.count("/") == 3 and isinstance(snapshot.value, dict):
                ap_info[path.split("/")[2]] = snapshot.value
            if path == "wifi/bss/" and isinstance(snapshot.value, list):
                bss_info = {
                    str(item.get("bssid", item.get("id", ""))).lower(): item
                    for item in snapshot.value
                    if isinstance(item, dict)
                }

        # Merge LAN observations through stable identities and configured name aliases.
        presence_sources: dict[str, str] = {}
        wifi_links: dict[str, list[dict[str, Any]]] = defaultdict(list)
        wifi_known: set[str] = set()
        wifi_fresh: set[str] = set()
        presence_evidence: dict[str, str] = {}
        lan_hosts: dict[str, list[tuple[dict[str, Any], str, str, float]]] = defaultdict(list)
        lan_paths = {
            path for path in snapshots if path.startswith("lan/browser/") and path != "lan/browser/interfaces/"
        }
        if "presence" in enabled:
            for path in sorted(lan_paths):
                snapshot = snapshots[path]
                for host in snapshot.value if isinstance(snapshot.value, list) else []:
                    if not isinstance(host, dict):
                        continue
                    interface = path.split("/")[2]
                    key = self.inventory.resolve_host(host, interface)
                    if key and (
                        options["track_new_devices"] or not self.inventory.initialized or key in self.inventory.devices
                    ):
                        self.inventory.upsert(host, interface, path, snapshot.updated)
                        lan_hosts[key].append((host, interface, path, snapshot.updated))
            for key, records in lan_hosts.items():
                states = []
                ipv4: set[str] = set()
                ipv6: set[str] = set()
                for host, interface, path, now in records:
                    device = self.inventory.upsert(host, interface, path, now)
                    if device:
                        ipv4.update(device.ipv4)
                        ipv6.update(device.ipv6)
                    if collectors.healthy(path):
                        if isinstance(host.get("active"), bool) or isinstance(host.get("reachable"), bool):
                            active = bool(host.get("active") or host.get("reachable"))
                            states.append(active)
                            if active:
                                presence_sources[key] = path
                    if path in collectors.changed:
                        self.observed_devices.add(key)
                device = self.inventory.devices[key]
                device.ipv4, device.ipv6 = tuple(sorted(ipv4)), tuple(sorted(ipv6))
                known_paths = {p for p in device.source_paths if p in lan_paths}
                complete = all(collectors.healthy(p) for p in known_paths)
                device.online = True if any(states) else False if states and complete else None
            # A known host disappearing from all complete, successfully refreshed interfaces is offline.
            for key, device in self.inventory.devices.items():
                previous = {path for path in device.source_paths if path in lan_paths}
                if (
                    key not in lan_hosts
                    and previous
                    and previous <= collectors.changed
                    and all(collectors.healthy(p) for p in previous)
                ):
                    device.online = False
                    self.observed_devices.add(key)

        # DHCP reservations and names are metadata, never proof of online presence.
        if "dhcp" in enabled:
            for path in ("dhcp/static_lease/", "dhcp/dynamic_lease/"):
                lease_snapshot = snapshots.get(path)
                if not lease_snapshot:
                    continue
                for lease in lease_snapshot.value if isinstance(lease_snapshot.value, list) else []:
                    if not isinstance(lease, dict) or not (mac := normalize_mac(lease.get("mac"))):
                        continue
                    key = self.inventory.resolve_host({"mac": mac, "hostname": lease.get("hostname")}, "dhcp")
                    if key is None:
                        continue
                    device = self.inventory.devices.get(key)
                    if device is None and options["track_new_devices"]:
                        device = self.inventory.upsert(
                            {"mac": mac, "hostname": lease.get("hostname")}, "dhcp", path, lease_snapshot.updated
                        )
                    if device:
                        device.dhcp_name = str(lease.get("hostname") or device.dhcp_name or "")[:128]
                        if not device.ipv4 and lease.get("ip"):
                            from .inventory import addresses

                            device.ipv4, _ = addresses({"l3connectivities": [{"addr": lease["ip"]}]})
                        if "static" in path:
                            device.reserved = True
                        elif device.reserved is None:
                            device.reserved = False
                        device.lease = {
                            k: lease[k]
                            for k in ("ip", "hostname", "lease_remaining", "lease_time", "expire", "timestamp")
                            if k in lease
                        }
            static = snapshots.get("dhcp/static_lease/")
            if static and collectors.healthy("dhcp/static_lease/"):
                reserved = {normalize_mac(item.get("mac")) for item in static.value if isinstance(item, dict)}
                for device in self.inventory.devices.values():
                    device.reserved = device.mac in reserved if device.mac else None

        if "wifi_clients" in enabled:
            # Forget station gauges on each new authoritative station list, retaining device identity/history.
            station_paths = {path for path in snapshots if path.endswith("/stations/")}
            expected_stations = {
                p
                for p, cap in collectors.capabilities.items()
                if p.endswith("/stations/") and cap.error != "discovery_removed"
            }
            discovery = snapshots.get("wifi/ap/")
            if discovery and isinstance(discovery.value, list):
                from urllib.parse import quote

                expected_stations.update(
                    f"wifi/ap/{quote(str(ap['id']), safe='')}/stations/"
                    for ap in discovery.value
                    if isinstance(ap, dict) and "id" in ap
                )
            else:
                expected_stations = station_paths | {p for p in collectors.capabilities if p.endswith("/stations/")}
            associated: set[str] = set()
            for device in self.inventory.devices.values():
                if device.ap_id and f"wifi/ap/{device.ap_id}/stations/" in collectors.changed:
                    device.wifi = {}
            for path in sorted(station_paths):
                if path not in expected_stations:
                    continue
                snapshot = snapshots[path]
                ap_id = path.split("/")[2]
                for station in snapshot.value if isinstance(snapshot.value, list) else []:
                    if not isinstance(station, dict) or not host_mac(station):
                        continue
                    host = dict(station.get("host", {})) if isinstance(station.get("host"), dict) else {}
                    host.update(mac=host_mac(station), hostname=station.get("hostname"))
                    key = self.inventory.resolve_host(host, "wifi")
                    if (
                        key not in self.inventory.devices
                        and self.inventory.initialized
                        and not options["track_new_devices"]
                    ):
                        continue
                    device = self.inventory.upsert(host, "wifi", path, snapshot.updated)
                    if device is None:
                        continue
                    device.wifi = station
                    device.ap_id = ap_id
                    config = ap_info.get(ap_id, {}).get("config", {})
                    device.band = str(config.get("band", "")) or None if isinstance(config, dict) else None
                    if station.get("state") in {"associated", "authenticated"} and collectors.healthy(path):
                        bss = bss_info.get(str(station.get("bssid", "")).lower(), {})
                        bss_config = bss.get("config", {})
                        ssid = (
                            bss_config.get("ssid")
                            if isinstance(bss_config, dict) and collectors.healthy("wifi/bss/")
                            else None
                        )
                        wifi_links[device.key].append(
                            {
                                "access_point": ap_id,
                                "band": device.band,
                                "ssid": ssid,
                                "signal": number(station.get("signal")),
                                "inactive": number(station.get("inactive")),
                                "rx_rate": number(station.get("rx_rate")),
                                "tx_rate": number(station.get("tx_rate")),
                                "updated": snapshot.updated,
                            }
                        )
                        associated.add(device.key)
                        presence_sources[device.key] = path
                        device.online = True
                        device.connection = "wifi"
                        device.last_seen = snapshot.updated
                        if path in collectors.changed:
                            self.observed_devices.add(device.key)
                            wifi_fresh.add(device.key)
                    if not options["detailed_devices"] and "signal" in station:
                        signal = describe(device.key, "wifi.signal", station["signal"], path, "wifi_clients", options)
                        if signal:
                            self.add(signal)
                    if options["detailed_devices"]:
                        enriched = {k: v for k, v in station.items() if k != "host"}
                        enriched["ap_id"] = ap_id
                        if device.band:
                            enriched["band"] = device.band
                        bss = bss_info.get(str(station.get("bssid", "")).lower(), {})
                        if isinstance(bss.get("config"), dict) and "ssid" in bss["config"]:
                            enriched["ssid"] = bss["config"]["ssid"]
                        self.object(device.key, device.name, enriched, path, "wifi_clients", options, "wifi")

            for key in associated:
                self.inventory.devices[key].online = True

            # The LAN browser lags Wi-Fi departures. Radio association is authoritative
            # for known Wi-Fi clients, including persisted identities and MAC aliases.
            complete = collectors.healthy("wifi/ap/") and all(
                collectors.healthy(p)
                and isinstance(snapshots[p].value, list)
                and all(
                    isinstance(station, dict)
                    and host_mac(station)
                    and station.get("state") in {"associated", "authenticated"}
                    for station in snapshots[p].value
                )
                for p in expected_stations
            )
            fresh_coverage = complete and (
                expected_stations <= collectors.changed if expected_stations else "wifi/ap/" in collectors.changed
            )
            for key, device in self.inventory.devices.items():
                if "wifi" not in device.interfaces:
                    continue
                wifi_known.add(key)
                if key in associated:
                    presence_evidence[key] = "wifi_association"
                    continue
                device.online = False if complete else None
                presence_evidence[key] = "wifi_absence" if complete else "api_unavailable"
                presence_sources[key] = min(expected_stations) if expected_stations else "wifi/ap/"
                if fresh_coverage:
                    self.observed_devices.add(key)
                    wifi_fresh.add(key)

        # Only infer Ethernet attachment when the switch MAC table actually lists the client.
        switch = snapshots.get("switch/status/")
        if switch and "ethernet" in enabled and isinstance(switch.value, list):
            for port in switch.value:
                if not isinstance(port, dict) or "id" not in port:
                    continue
                port_id = str(port["id"])
                for item in port.get("mac_list", []) if isinstance(port.get("mac_list"), list) else []:
                    mac = normalize_mac(item.get("mac")) if isinstance(item, dict) else None
                    if mac and (device := self.inventory.devices.get(self.inventory.resolve(f"mac:{mac}"))):
                        device.switch_port = port_id
                        if not device.wifi and port.get("link") == "up":
                            device.connection = "ethernet"
                            if "switch/status/" in collectors.changed:
                                self.observed_devices.add(device.key)
                if port.get("link") in {"up", "down"}:
                    self.observations[f"port:{port_id}:link"] = (port["link"] == "up", "switch/status/")

        for path, snapshot in snapshots.items():
            family = snapshot.family
            if family not in enabled:
                continue
            value = snapshot.value
            if path in ROOTS and isinstance(value, dict):
                root_key, name = ROOTS[path]
                self.object(root_key, name, value, path, family, options)
                if path == "system/":
                    self.devices["box"] = Device(
                        "box",
                        "Freebox",
                        model=str(value.get("model_name") or value.get("board_name") or "Freebox"),
                        firmware=value.get("firmware_version"),
                        hardware=value.get("board_revision"),
                        parent=None,
                    )
                    self.uptime = number(value.get("uptime_val"))
                    if self.uptime is not None:
                        self.add(
                            Metric(
                                "box:last_boot",
                                "box",
                                "Last boot (calculated)",
                                datetime.fromtimestamp(snapshot.updated - self.uptime, UTC),
                                path,
                                family,
                                device_class="timestamp",
                            )
                        )
                    for group in ("sensors", "fans"):
                        for sensor in value.get(group, []) if isinstance(value.get(group), list) else []:
                            if (
                                not isinstance(sensor, dict)
                                or "id" not in sensor
                                or number(sensor.get("value")) is None
                            ):
                                continue
                            sensor_id = str(sensor["id"])
                            kind = sensor.get("type")
                            unit = (
                                "°C"
                                if kind in {"temp", "temperature"}
                                else "rpm"
                                if group == "fans" or kind in {"fan", "rpm"}
                                else None
                            )
                            if unit is None and not options["unknown_metrics"]:
                                continue
                            self.add(
                                Metric(
                                    f"box:{group}:{sensor_id}",
                                    "box",
                                    str(sensor.get("name", sensor_id)),
                                    sensor["value"],
                                    path,
                                    family,
                                    unit=unit,
                                    device_class="temperature" if unit == "°C" else None,
                                    state_class="measurement" if unit else None,
                                    enabled=bool(unit),
                                )
                            )
                if path == "connection/" and value.get("state") in {"up", "down", "going_up", "going_down"}:
                    self.add(
                        Metric(
                            "wan:connected",
                            "wan",
                            "Internet connected",
                            value["state"] == "up",
                            path,
                            family,
                            "binary_sensor",
                            device_class="connectivity",
                        )
                    )
                    if value["state"] in {"up", "down"}:
                        self.observations["wan:connected"] = (value["state"] == "up", path)
                if path == "connection/ftth/":
                    if value.get("sfp_has_power_report") is False or value.get("sfp_present") is False:
                        self.metrics.pop("fibre:sfp_pwr_rx", None)
                        self.metrics.pop("fibre:sfp_pwr_tx", None)
            elif path == "switch/status/" and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "id" in item:
                        key = f"port:{item['id']}"
                        self.object(key, f"Ethernet {item['id']}", item, path, family, options)
                        if item.get("link") in {"up", "down"}:
                            self.add(
                                Metric(
                                    f"{key}:link",
                                    key,
                                    "Link",
                                    item["link"] == "up",
                                    path,
                                    family,
                                    "binary_sensor",
                                    device_class="connectivity",
                                )
                            )
            elif path.startswith("switch/port/") and isinstance(value, dict):
                key = f"port:{path.split('/')[2]}"
                self.object(
                    key, key, value, path, family, options, "stats" if path.endswith("stats") else "negotiation"
                )
            elif (
                path == "wifi/ap/"
                and isinstance(value, list)
                or path.startswith("wifi/ap/")
                and path.count("/") == 3
                and isinstance(value, dict)
            ):
                for item in value if isinstance(value, list) else [value]:
                    if isinstance(item, dict) and "id" in item:
                        key = f"ap:{item['id']}"
                        self.object(key, str(item.get("name") or f"Wi-Fi AP {item['id']}"), item, path, family, options)
                        status = item.get("status", {})
                        if isinstance(status, dict) and status.get("state"):
                            self.add(
                                Metric(
                                    f"{key}:active",
                                    key,
                                    "Radio active",
                                    status["state"] == "active",
                                    path,
                                    family,
                                    "binary_sensor",
                                    device_class="connectivity",
                                )
                            )
            elif path.endswith("/stations/"):
                ap_id = path.split("/")[2]
                self.add(
                    Metric(
                        f"ap:{ap_id}:clients",
                        f"ap:{ap_id}",
                        "Associated clients",
                        len(value),
                        path,
                        family,
                        state_class="measurement",
                    )
                )
            elif path.endswith("/channel_usage/") and isinstance(value, list):
                ap_id = path.split("/")[2]
                for channel in value:
                    if isinstance(channel, dict) and "channel" in channel:
                        self.object(
                            f"ap:{ap_id}",
                            f"Wi-Fi AP {ap_id}",
                            channel,
                            path,
                            family,
                            options,
                            f"channel_{channel.get('band', '')}_{channel['channel']}",
                        )
            elif path.endswith("/neighbors/") and isinstance(value, list):
                ap_id = path.split("/")[2]
                self.add(
                    Metric(
                        f"ap:{ap_id}:neighbors",
                        f"ap:{ap_id}",
                        "Cached neighboring networks",
                        len(value),
                        path,
                        family,
                        state_class="measurement",
                    )
                )
            elif path.startswith("lan/browser/") or path.startswith("dhcp/") and isinstance(value, list):
                self.add(
                    Metric(
                        f"box:{path}:count",
                        "box",
                        path.replace("/", " ") + " count",
                        len(value),
                        path,
                        family,
                        diagnostic=True,
                    )
                )
            elif isinstance(value, dict):
                key = f"family:{family}"
                self.object(
                    key, family.replace("_", " "), value, path, family, options, path.strip("/").replace("/", ".")
                )
                for list_name, items in value.items():
                    if list_name == "delegations" and isinstance(items, list):
                        for index, item in enumerate(items):
                            if isinstance(item, dict):
                                self.object(key, family, item, path, family, options, f"delegation_{index}")
            elif isinstance(value, list):
                key = f"family:{family}"
                self.devices.setdefault(key, Device(key, family.replace("_", " ")))
                self.add(
                    Metric(f"{key}:{path}:count", key, path.replace("/", " ") + " count", len(value), path, family)
                )
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    item_id = item.get("id")
                    if item_id is None:
                        continue
                    if path == "wifi/bss/":
                        item_key = f"bss:{item_id}"
                    elif path.startswith("storage/"):
                        item_key = f"{path.split('/')[1]}:{item_id}"
                    elif family in {"downloads", "routing", "parental", "vpn", "freeplug"}:
                        item_key = f"{family}:{path}:{item_id}"
                    else:
                        continue
                    self.object(item_key, f"{family} {item_id}", item, path, family, options)
                    if isinstance(item.get("partitions"), list):
                        for part in item["partitions"]:
                            if isinstance(part, dict) and "id" in part:
                                self.object(
                                    f"partition:{part['id']}", f"Partition {part['id']}", part, path, family, options
                                )

        for key, device in self.inventory.devices.items():
            self.devices[key] = Device(key, device.name, device.vendor or "Unknown", device.host_type)
            paths = device.source_paths
            endpoint = next(
                (p for p in paths if p.startswith("lan/browser/") and collectors.healthy(p)),
                next(
                    (p for p in paths if collectors.healthy(p) and p.endswith("/stations/")),
                    paths[0] if paths else "lan/browser/interfaces/",
                ),
            )
            endpoint = presence_sources.get(key, endpoint)
            family = (
                "presence"
                if endpoint.startswith("lan/")
                else "wifi_clients"
                if endpoint.endswith("/stations/")
                else "dhcp"
            )
            if family not in enabled:
                continue
            self.add(
                Metric(
                    f"{key}:connected",
                    key,
                    "Connected",
                    device.online,
                    endpoint,
                    family,
                    "binary_sensor",
                    device_class="connectivity",
                )
            )
            tracker = Metric(f"{key}:tracker", key, "Presence", device.online, endpoint, family, "device_tracker")
            links = wifi_links.get(key, []) if device.online is True else []
            bands = sorted({link["band"] for link in links if link["band"]})
            access_points = sorted({link["access_point"] for link in links})
            tracker.attributes = {
                "connection_evidence": presence_evidence.get(
                    key, "lan_status" if device.online is not None else "api_unavailable"
                ),
                "presence_observed_at": datetime.fromtimestamp(snapshots[endpoint].updated, UTC).isoformat()
                if endpoint in snapshots and device.online is not None
                else None,
                "connection_type": "wifi"
                if links
                else "ethernet"
                if device.online is True and device.connection == "ethernet"
                else None,
                "wifi_band": bands[0] if len(bands) == 1 else None,
                "wifi_bands": bands,
                "access_point": access_points[0] if len(access_points) == 1 else None,
                "access_points": access_points,
            }
            if links:
                signals = [link["signal"] for link in links if link["signal"] is not None]
                inactive = [
                    link["inactive"] for link in links if link["inactive"] is not None and link["inactive"] >= 0
                ]
                rates = [
                    link[field]
                    for link in links
                    for field in ("rx_rate", "tx_rate")
                    if link[field] is not None and link[field] >= 0
                ]
                tracker.attributes.update(
                    wifi_signal=max(signals) if signals else None,
                    wifi_signal_unit="dB" if signals else None,
                    wifi_inactive_seconds=min(inactive) if inactive else None,
                    wifi_traffic_active=any(rate > 0 for rate in rates) if rates else None,
                )
            if options["expose_identity"]:
                ssids = sorted({link["ssid"] for link in links if isinstance(link["ssid"], str)})
                tracker.attributes.update(ssid=ssids[0] if len(ssids) == 1 else None, ssids=ssids)
            self.add(tracker)
            basic = {
                "connection_type": device.connection,
                "wifi_band": device.band,
                "switch_port": device.switch_port,
                "access_point": device.ap_id,
                "dhcp_reserved": device.reserved,
                "private_mac": device.private_mac,
            }
            if options["expose_identity"]:
                basic.update(
                    ipv4=device.ipv4[0] if device.ipv4 else None,
                    ipv6=device.ipv6[0] if device.ipv6 else None,
                    hostname=device.name,
                    mac_address=device.mac,
                    dhcp_name=device.dhcp_name,
                )
            for field, item in basic.items():
                if item is not None:
                    self.add(
                        Metric(
                            f"{key}:{field}",
                            key,
                            field.replace("_", " "),
                            item,
                            endpoint,
                            family,
                            "binary_sensor" if isinstance(item, bool) else "sensor",
                            diagnostic=field in {"private_mac", "mac_address"},
                            cached=True,
                            attributes={"data_source": "inventory", "last_known": device.online is not True},
                        )
                    )
            for field in ("first_seen", "last_seen", "last_activity", "last_connected", "last_disconnected"):
                if (stamp := timestamp(getattr(device, field))) is not None:
                    self.add(
                        Metric(
                            f"{key}:{field}",
                            key,
                            field.replace("_", " "),
                            stamp,
                            endpoint,
                            family,
                            device_class="timestamp",
                            diagnostic=True,
                            cached=True,
                            attributes={"data_source": "inventory"},
                        )
                    )
            if device.reserved is not None:
                for field in ("lease_remaining", "lease_time", "expire", "timestamp"):
                    if field in device.lease:
                        item = (
                            timestamp(device.lease[field])
                            if field in {"expire", "timestamp"}
                            else number(device.lease[field])
                        )
                        self.add(
                            Metric(
                                f"{key}:dhcp:{field}",
                                key,
                                f"DHCP {field}",
                                item,
                                "dhcp/dynamic_lease/",
                                "dhcp",
                                unit="s" if field in {"lease_remaining", "lease_time"} else None,
                                device_class="duration" if field in {"lease_remaining", "lease_time"} else "timestamp",
                            )
                        )
            if key in self.observed_devices or device.online is None:
                if key not in wifi_known or key in wifi_fresh or device.online is None:
                    self.observations[f"{key}:online"] = (device.online, endpoint)
                if device.ipv4 or device.ipv6:
                    self.observations[f"{key}:ip"] = ((device.ipv4, device.ipv6), endpoint)
                if device.connection:
                    self.observations[f"{key}:connection"] = (device.connection, endpoint)
                if device.wifi and device.ap_id:
                    wifi_path = f"wifi/ap/{device.ap_id}/stations/"
                    self.observations[f"{key}:ap"] = (device.ap_id, wifi_path)
                    if device.band:
                        self.observations[f"{key}:band"] = (device.band, wifi_path)
