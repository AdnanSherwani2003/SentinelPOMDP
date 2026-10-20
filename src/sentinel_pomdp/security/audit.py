"""Bounded metadata-only security audit events."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock


@dataclass(frozen=True)
class SecurityAuditEvent:
    event_id: str
    occurred_at: datetime
    correlation_id: str
    operation: str
    outcome: str
    reason_code: str
    principal_id: str | None = None
    tenant_id: str | None = None
    resource_id: str | None = None


class BoundedAuditLog:
    """Process-local sink; use append-only centralized storage in production."""

    def __init__(self, max_events: int = 1_000) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self._events: deque[SecurityAuditEvent] = deque(maxlen=max_events)
        self._ids: set[str] = set()
        self._lock = Lock()

    def emit(self, event: SecurityAuditEvent) -> None:
        with self._lock:
            if event.event_id in self._ids:
                return
            if len(self._events) == self._events.maxlen:
                removed = self._events[0]
                self._ids.discard(removed.event_id)
            self._events.append(event)
            self._ids.add(event.event_id)

    def snapshot(self) -> tuple[SecurityAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)


def audit_event(*, event_id: str, correlation_id: str, operation: str, outcome: str,
                reason_code: str, principal_id: str | None = None,
                tenant_id: str | None = None, resource_id: str | None = None) -> SecurityAuditEvent:
    return SecurityAuditEvent(
        event_id=event_id, occurred_at=datetime.now(timezone.utc), correlation_id=correlation_id,
        operation=operation, outcome=outcome, reason_code=reason_code,
        principal_id=principal_id, tenant_id=tenant_id, resource_id=resource_id,
    )
