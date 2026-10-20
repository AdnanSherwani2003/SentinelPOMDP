"""Behavioral comparison of direct and LangGraph orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from sentinel_pomdp.investigation import (
    build_scenario_planner, conflicting_delivery_scenario, missing_evidence_scenario,
    multi_investigation_scenario, run_graph_investigation, supplier_shipment_delay_scenario,
)

from .workflow import run_langgraph_investigation


@dataclass(frozen=True)
class OrchestrationComparison:
    scenario_id: str
    horizon: int
    equivalent: bool
    decision: str
    tool_calls: int
    cost: float
    direct_runtime_ms: float
    langgraph_runtime_ms: float


def compare_orchestrators(repository, tenant_id: str = "tenant_alpha") -> list[OrchestrationComparison]:
    scenarios = [supplier_shipment_delay_scenario(tenant_id),
                 conflicting_delivery_scenario(tenant_id),
                 missing_evidence_scenario(tenant_id),
                 multi_investigation_scenario(tenant_id)]
    rows = []
    for horizon in (1, 2):
        for scenario in scenarios:
            direct_planner = build_scenario_planner(scenario, horizon)
            started = perf_counter()
            direct = run_graph_investigation(repository, scenario, direct_planner, tenant_id,
                                             max_steps=4, budget=1.0)
            direct_ms = (perf_counter() - started) * 1000
            graph_planner = build_scenario_planner(scenario, horizon)
            started = perf_counter()
            graph = run_langgraph_investigation(repository, scenario, graph_planner, tenant_id,
                                                max_tool_calls=4, budget=1.0)
            graph_ms = (perf_counter() - started) * 1000
            direct_actions = [s.chosen_action for s in direct.steps if s.tool_invoked]
            graph_actions = [s.chosen_action for s in graph.steps if s.tool_invoked]
            equivalent = (
                direct.decision == graph.decision
                and direct.selected_hypothesis == graph.selected_hypothesis
                and all(abs(direct.final_belief[k] - graph.final_belief[k]) < 1e-12
                        for k in direct.final_belief)
                and direct.evidence_verdict.evidence_ids == graph.evidence_verdict.evidence_ids
                and direct.total_cost == graph.total_cost
                and direct_actions == graph_actions
            )
            rows.append(OrchestrationComparison(
                scenario_id=scenario.scenario_id, horizon=horizon,
                equivalent=equivalent, decision=graph.decision,
                tool_calls=graph.metadata["tool_calls"], cost=graph.total_cost,
                direct_runtime_ms=direct_ms, langgraph_runtime_ms=graph_ms,
            ))
    return rows
