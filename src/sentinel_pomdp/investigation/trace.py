"""Human-readable formatting over the machine-readable episode trace."""
from __future__ import annotations

from .schemas import InvestigationOutcome


def format_investigation_trace(outcome: InvestigationOutcome) -> str:
    lines: list[str] = []
    for step in outcome.steps:
        lines.extend([
            f"STEP {step.step_number}",
            f"  belief before: {step.belief_before}",
            f"  decision: {step.chosen_action} (utility={step.expected_action_utility:.6f}, horizon={step.planner_horizon})",
        ])
        if step.tool_invoked:
            lines.extend([
                f"  tool: {step.tool_invoked} [{step.tool_status.value}]",
                f"  facts: {step.fact_ids}",
                f"  evidence: {step.evidence_ids}",
                f"  documents: {step.document_ids}",
                f"  observation: {step.observation_token.value}",
                f"  belief after: {step.belief_after}",
                f"  cost: {step.investigation_cost:.3f}; latency: {step.latency_ms:.3f} ms",
            ])
        lines.append(f"  evidence gate: {step.evidence_support}")
    lines.extend([
        "FINAL",
        f"  decision: {outcome.decision}",
        f"  hypothesis: {outcome.selected_hypothesis}",
        f"  posterior: {outcome.final_belief}",
        f"  provenance: {outcome.evidence_verdict.provenance_status}",
        f"  fact refs: {outcome.evidence_verdict.fact_ids}",
        f"  evidence refs: {outcome.evidence_verdict.evidence_ids}",
        f"  document refs: {outcome.evidence_verdict.document_ids}",
        f"  reason: {outcome.termination_reason}",
        f"  total cost: {outcome.total_cost:.3f}",
    ])
    return "\n".join(lines)
