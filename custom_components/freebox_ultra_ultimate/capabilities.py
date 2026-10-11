"""Endpoint health and bounded discovery of field names, without values."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


def field_paths(value: Any, prefix: str = "", depth: int = 0) -> set[str]:
    if depth > 6:
        return set()
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in list(value.items())[:128]:
            path = f"{prefix}.{key}".lstrip(".")
            result.add(path)
            result.update(field_paths(item, path, depth + 1))
    elif isinstance(value, list):
        for item in value[:5]:
            result.update(field_paths(item, prefix + "[]", depth + 1))
    return set(sorted(result)[:256])


@dataclass(slots=True)
class Capability:
    status: str = "unknown"
    error: str | None = None
    last_success: float | None = None
    last_attempt: float | None = None
    latency_ms: float | None = None
    failures: int = 0
    next_retry: float = 0
    fields: set[str] = field(default_factory=set)
    response_type: str | None = None

    def success(self, value: Any, elapsed: float, now: float) -> None:
        self.status, self.error = "supported", None
        self.last_success = now
        self.latency_ms = round(elapsed * 1000, 2)
        self.failures = 0
        self.next_retry = 0
        self.fields.update(field_paths(value))
        self.fields = set(sorted(self.fields)[:256])

    def fail(self, status: str, error: str, now: float) -> None:
        self.status, self.error = status, error
        self.failures += 1
        delay = 900 if status in {"unsupported", "forbidden"} else min(300, 5 * 2 ** min(self.failures, 6))
        self.next_retry = time.monotonic() + delay

    def export(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error": self.error,
            "last_success": self.last_success,
            "last_attempt": self.last_attempt,
            "latency_ms": self.latency_ms,
            "failures": self.failures,
            "fields": sorted(self.fields),
            "response_type": self.response_type,
        }
