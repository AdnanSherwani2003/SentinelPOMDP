"""Tenant-scoped process-local counters and timing summaries."""
from __future__ import annotations

from collections import defaultdict
from threading import Lock


class MetricsStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tenants: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self._auth_failures = 0

    def record_auth_failure(self) -> None:
        with self._lock:
            self._auth_failures += 1

    def record(self, tenant_id: str, *, status: str, latency_ms: float,
               tool_calls: int = 0, investigation_cost: float = 0,
               planning_ms: float = 0, graph_ms: float = 0,
               model_ms: float = 0, fallback: bool = False) -> None:
        with self._lock:
            values = self._tenants[tenant_id]
            values["requests"] += 1
            values["latency_ms_total"] += latency_ms
            values["tool_calls"] += tool_calls
            values["investigation_cost_total"] += investigation_cost
            values["planning_ms_total"] += planning_ms
            values["graph_ms_total"] += graph_ms
            values["model_ms_total"] += model_ms
            values["fallback_count"] += int(fallback)
            values[f"status:{status}"] += 1

    def snapshot(self, tenant_id: str) -> dict[str, float | int | dict[str, int]]:
        with self._lock:
            values = dict(self._tenants.get(tenant_id, {}))
        requests = int(values.get("requests", 0))
        statuses = {
            key.removeprefix("status:"): int(value)
            for key, value in values.items() if key.startswith("status:")
        }
        return {
            "requests": requests,
            "statuses": statuses,
            "average_latency_ms": values.get("latency_ms_total", 0) / requests if requests else 0,
            "tool_calls": int(values.get("tool_calls", 0)),
            "investigation_cost_total": values.get("investigation_cost_total", 0),
            "planning_ms_total": values.get("planning_ms_total", 0),
            "graph_ms_total": values.get("graph_ms_total", 0),
            "model_ms_total": values.get("model_ms_total", 0),
            "fallback_count": int(values.get("fallback_count", 0)),
        }
