"""Bounded redaction rules shared by collection and diagnostics."""

from __future__ import annotations

import hashlib
import re
from typing import Any

SECRET_KEY = re.compile(r"password|passwd|token|secret|credential|private|^key$|_key$|certificate|^psk$", re.I)
PRIVATE_KEY = re.compile(
    r"mac|bssid|ssid|hostname|primary_name|vendor_name|serial|uuid|uid|address|addr|ipv[46]|ip$|prefix|next_hop|host$|name$|label|url|path|user|login|comment|description",
    re.I,
)


def strip_secrets(value: Any, depth: int = 0) -> Any:
    """Drop secrets before caching; bound pathological payloads."""
    if depth > 8:
        return None
    if isinstance(value, dict):
        return {
            str(k): strip_secrets(v, depth + 1) for k, v in list(value.items())[:256] if not SECRET_KEY.search(str(k))
        }
    if isinstance(value, list):
        return [strip_secrets(v, depth + 1) for v in value[:2048]]
    if isinstance(value, str):
        return value[:1024]
    return value if isinstance(value, (int, float, bool, type(None))) else None


def anonymous_id(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]


def anonymize(value: Any, salt: str, key: str = "") -> Any:
    """Conservative export: redact all strings except explicitly operational enums."""
    if SECRET_KEY.search(key):
        return "**REDACTED**"
    if isinstance(value, dict):
        return {k: anonymize(v, salt, k) for k, v in value.items()}
    if isinstance(value, list):
        return [anonymize(v, salt, key) for v in value[:256]]
    if PRIVATE_KEY.search(key):
        return "**REDACTED**"
    if isinstance(value, str):
        if key in {
            "state",
            "status",
            "error",
            "permission",
            "family",
            "version",
            "api_version",
            "unit",
            "device_class",
            "platform",
        } and re.fullmatch(r"[a-zA-Z0-9_. /°%-]{1,64}", value):
            return value
        return anonymous_id(value, salt)
    return value
