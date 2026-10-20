"""Readable formatting for structured LangGraph node traces."""
from __future__ import annotations

from sentinel_pomdp.investigation.schemas import InvestigationOutcome


def format_workflow_trace(outcome: InvestigationOutcome) -> str:
    lines = []
    for event in outcome.metadata.get("workflow_trace", []):
        details = []
        for key in ("route", "planner_action", "tool_name", "tool_status", "observation",
                    "evidence_gate_verdict", "termination_reason", "error"):
            if event.get(key) is not None:
                details.append(f"{key}={event[key]}")
        if event.get("evidence_ids"):
            details.append(f"evidence={event['evidence_ids']}")
        if event.get("belief_after") is not None:
            details.append(f"belief_after={event['belief_after']}")
        details.append(f"runtime_ms={event['node_runtime_ms']:.3f}")
        lines.append(f"{event['sequence']:02d} {event['node_name']}: " + "; ".join(details))
    return "\n".join(lines)
