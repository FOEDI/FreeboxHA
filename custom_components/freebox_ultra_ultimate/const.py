"""Integration constants and polling policy."""

from dataclasses import dataclass
from typing import Any

DOMAIN = "freebox_ultra_ultimate"
NAME = "Freebox HA"
VERSION = "1.0.0"
PLATFORMS = ["sensor", "binary_sensor", "device_tracker", "event"]
DEFAULT_HOST = "mafreebox.freebox.fr"
DEFAULT_PORT = 443
DEFAULT_TIMEOUT = 8
MAX_RESPONSE_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Family:
    interval: int
    endpoints: tuple[tuple[str, str], ...]
    enabled: bool = True
    permission: str | None = None


FAMILIES: dict[str, Family] = {
    "wan": Family(10, (("connection/", "object"),)),
    "fibre": Family(30, (("connection/ftth/", "object"),)),
    "presence": Family(20, (("lan/browser/interfaces/", "list"),)),
    "wifi_clients": Family(10, (("wifi/ap/", "list"),)),
    "ethernet": Family(15, (("switch/status/", "list"),)),
    "system": Family(30, (("system/", "object"),)),
    "wifi_radios": Family(30, (("wifi/ap/", "list"), ("wifi/bss/", "list"), ("wifi/config/", "object"))),
    "dhcp": Family(
        120, (("dhcp/dynamic_lease/", "list"), ("dhcp/static_lease/", "list"), ("dhcp/config/", "object")), False
    ),
    "network": Family(
        300, (("lan/config/", "object"), ("connection/ipv6/config/", "object"), ("connection/config/", "object")), False
    ),
    "wifi_environment": Family(300, (("wifi/ap/", "list"),), False),
    "storage": Family(
        30, (("storage/disk/", "list"), ("storage/partition/", "list"), ("storage/config/", "object")), False
    ),
    "services": Family(
        300,
        (
            ("ftp/config/", "object"),
            ("netshare/samba/", "object"),
            ("netshare/afp/", "object"),
            ("upnpav/config/", "object"),
            ("airmedia/config/", "object"),
        ),
        False,
    ),
    "routing": Family(
        300,
        (
            ("fw/redir/", "list"),
            ("fw/dmz/", "object"),
            ("fw/incoming/", "list"),
            ("upnpigd/config/", "object"),
            ("upnpigd/redir/", "list"),
        ),
        False,
    ),
    "vpn": Family(
        30,
        (("vpn/", "list"), ("vpn/connection/", "list"), ("vpn/ip_pool/", "list"), ("vpn_client/status", "object")),
        False,
    ),
    "downloads": Family(30, (("downloads/", "list"), ("downloads/stats", "object")), False, "downloader"),
    "parental": Family(120, (("parental/config/", "object"), ("parental/filter/", "list")), False, "parental"),
    "freeplug": Family(30, (("freeplug/", "list"),), False),
    "connection_logs": Family(120, (("connection/logs/", "list"),), False),
}
DEFAULT_OPTIONS: dict[str, Any] = {
    "families": [name for name, family in FAMILIES.items() if family.enabled],
    **{f"interval_{name}": family.interval for name, family in FAMILIES.items()},
    "disconnect_delay": 40,
    "wifi_disconnect_delay": 10,
    "event_delay": 10,
    "alert_delay": 30,
    "wifi_signal_threshold": -70,
    "wifi_signal_hysteresis": 5,
    "temperature_threshold": 80,
    "temperature_hysteresis": 5,
    "fibre_rx_threshold": -28,
    "fibre_rx_hysteresis": 2,
    "fibre_power_unit": "hundredths_dbm",
    "detailed_devices": False,
    "advanced_metrics": False,
    "group_by_name": True,
    "unknown_metrics": False,
    "expose_identity": True,
    "event_identity": True,
    "events_enabled": True,
    "track_new_devices": True,
    "websocket": True,
    "history_size": 30,
}
EVENT_TYPES = (
    "device_discovered",
    "device_connected",
    "device_disconnected",
    "device_ip_changed",
    "device_connection_changed",
    "wifi_signal_low",
    "wifi_band_changed",
    "wifi_client_roamed",
    "ethernet_link_down",
    "ethernet_link_up",
    "wan_disconnected",
    "wan_reconnected",
    "fibre_signal_warning",
    "system_temperature_high",
)
EVENT_PREFIX = "freebox_ultra_"


def is_network_list(path: str) -> bool:
    """Network collection endpoints using firmware-dependent empty encodings."""
    return (
        path.startswith("wifi/ap/")
        and path.endswith("/stations/")
        or (path.startswith("lan/browser/") and path != "lan/browser/interfaces/")
    )
