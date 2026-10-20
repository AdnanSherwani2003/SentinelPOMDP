"""Deterministic policy comparison for the small static synthetic graph."""
from __future__ import annotations

from dataclasses import dataclass

from sentinel_pomdp.multistep import MultiStepPlanner, PlanDecision

from .scenario import (
    InvestigationScenario, build_scenario_planner, conflicting_delivery_scenario,
    missing_evidence_scenario, supplier_shipment_delay_scenario,
)
from .session import run_graph_investigation


class FixedSequencePlanner:
    """Baseline that executes a preset order while reusing the same Bayes model."""

    def __init__(self, base: MultiStepPlanner, sequence: list[str]) -> None:
        self.base = base
        self.sequence = sequence
        self.config = base.config

    def posterior(self, *args, **kwargs):
        return self.base.posterior(*args, **kwargs)

    def decide(self, belief, history=(), horizon=None):
        terminal = self.base.decide(belief, history=history, horizon=0)
        if terminal.kind == "ANSWER":
            return terminal
        used = {action for action, _ in history}
        for action in self.sequence:
            if action not in used:
                return PlanDecision("INVESTIGATE", action, None, 0.0, tuple())
        return terminal


@dataclass(frozen=True)
class PolicyMetrics:
    policy: str
    supported_answers: int
    unsupported_answers: int
    abstentions: int
    coverage: float
    investigation_actions: int
    investigation_cost: float
    realized_utility: float
    provenance_valid: int
    conflicts_handled: int
    planning_runtime_ms: float
    tool_runtime_ms: float


def evaluate_policies(repository, tenant_id: str = "tenant_alpha") -> list[PolicyMetrics]:
    scenarios = [supplier_shipment_delay_scenario(tenant_id), conflicting_delivery_scenario(tenant_id),
                 missing_evidence_scenario(tenant_id)]
    rows = []
    for label, horizon in (("fixed", None), ("horizon_1", 1), ("horizon_2", 2)):
        outcomes = []
        for scenario in scenarios:
            base = build_scenario_planner(scenario, horizon=horizon or 2)
            planner = FixedSequencePlanner(base, list(scenario.requests)) if label == "fixed" else base
            outcomes.append(run_graph_investigation(repository, scenario, planner, tenant_id,
                                                    max_steps=len(scenario.requests) + 1, budget=1.0))
        answers = [o for o in outcomes if o.decision == "ANSWER"]
        supported = sum(o.evidence_verdict.sufficient for o in answers)
        actions = sum(sum(s.tool_invoked is not None for s in o.steps) for o in outcomes)
        cost = sum(o.total_cost for o in outcomes)
        rows.append(PolicyMetrics(
            policy=label, supported_answers=supported,
            unsupported_answers=len(answers) - supported,
            abstentions=sum(o.decision == "ABSTAIN" for o in outcomes),
            coverage=len(answers) / len(outcomes), investigation_actions=actions,
            investigation_cost=cost, realized_utility=supported * 5 - (len(answers) - supported) * 7 - cost,
            provenance_valid=sum(o.evidence_verdict.provenance_status == "VERIFIED_SUPPORTED" for o in outcomes),
            conflicts_handled=sum(o.decision == "ABSTAIN" and any(
                s.observation_token and s.observation_token.value == "EVIDENCE_CONFLICTED" for s in o.steps
            ) for o in outcomes),
            planning_runtime_ms=sum(o.planning_runtime_ms for o in outcomes),
            tool_runtime_ms=sum(o.tool_runtime_ms for o in outcomes),
        ))
    return rows
