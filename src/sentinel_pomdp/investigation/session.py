"""Bounded orchestration loop joining planner decisions to real graph evidence."""
from __future__ import annotations

from time import perf_counter

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.multistep import MultiStepPlanner

from .observations import UnsafeToolResult, adapt_result
from .scenario import InvestigationScenario
from .schemas import EvidenceVerdict, InvestigationOutcome, InvestigationStep, ToolStatus
from .tools import GraphInvestigationTools


def run_graph_investigation(
    repository: BaseGraphRepository,
    scenario: InvestigationScenario,
    planner: MultiStepPlanner,
    tenant_id: str,
    *,
    max_steps: int = 3,
    budget: float = 1.0,
) -> InvestigationOutcome:
    belief = dict(scenario.prior)
    history: list[tuple[str, str]] = []
    observations = []
    steps = []
    seen_evidence: set[str] = set()
    seen_documents: set[str] = set()
    total_cost = tool_ms = planning_ms = 0.0
    tools = GraphInvestigationTools(repository)
    final_candidate = None
    reason = "step limit reached"

    for number in range(1, max_steps + 1):
        planning_started = perf_counter()
        decision = planner.decide(belief, history=history)
        planning_ms += (perf_counter() - planning_started) * 1000
        before = dict(belief)
        if decision.kind != "INVESTIGATE":
            final_candidate = decision.hypothesis if decision.kind == "ANSWER" else None
            verdict = scenario.evidence_policy.evaluate(final_candidate, observations)
            if decision.kind == "ANSWER" and verdict.sufficient:
                reason = "mathematical answer and evidence gate both satisfied"
                final_decision = "ANSWER"
            else:
                reason = verdict.reason if decision.kind == "ANSWER" else "planner selected abstention"
                final_decision = "ABSTAIN"
            steps.append(InvestigationStep(
                step_number=number, belief_before=before, chosen_action=decision.kind,
                planner_horizon=planner.config.horizon,
                expected_action_utility=decision.expected_utility,
                action_scores=dict(decision.action_scores), belief_after=before,
                evidence_support=verdict.provenance_status,
            ))
            return InvestigationOutcome(
                decision=final_decision, selected_hypothesis=final_candidate if final_decision == "ANSWER" else None,
                final_belief=belief, evidence_verdict=verdict, steps=steps, total_cost=total_cost,
                termination_reason=reason, planning_runtime_ms=planning_ms, tool_runtime_ms=tool_ms,
                metadata={"scenario": scenario.name, "tenant_id": tenant_id},
            )

        request = scenario.requests[decision.action]
        projected_cost = tools.costs[request.action_name]
        if total_cost + projected_cost > budget:
            reason = "investigation budget exhausted before selected action"
            break
        result = tools.execute(request, authorized_tenant_id=tenant_id)
        tool_ms += result.latency_ms or 0.0
        total_cost += result.cost
        try:
            observation = adapt_result(decision.action, result,
                                       seen_evidence_ids=seen_evidence,
                                       seen_document_ids=seen_documents)
        except UnsafeToolResult as exc:
            verdict = scenario.evidence_policy.evaluate(None, observations)
            steps.append(InvestigationStep(
                step_number=number, belief_before=before, chosen_action=decision.action,
                planner_horizon=planner.config.horizon,
                expected_action_utility=decision.expected_utility,
                action_scores=dict(decision.action_scores), tool_invoked=request.action_name.value,
                tool_status=result.status, belief_after=before, investigation_cost=result.cost,
                latency_ms=result.latency_ms, evidence_support="OPERATIONAL_FAILURE",
            ))
            return InvestigationOutcome(
                decision="ABSTAIN", final_belief=belief, evidence_verdict=verdict, steps=steps,
                total_cost=total_cost, termination_reason=f"tool outcome cannot enter Bayes: {exc}",
                planning_runtime_ms=planning_ms, tool_runtime_ms=tool_ms,
                metadata={"scenario": scenario.name, "tenant_id": tenant_id},
            )
        token = observation.observation_token.value
        belief = planner.posterior(belief, decision.action, token)
        history.append((decision.action, token))
        observations.append(observation)
        seen_evidence.update(observation.source_evidence_ids)
        seen_documents.update(observation.source_document_ids)
        candidate = max(belief, key=belief.get)
        interim = scenario.evidence_policy.evaluate(candidate, observations)
        steps.append(InvestigationStep(
            step_number=number, belief_before=before, chosen_action=decision.action,
            planner_horizon=planner.config.horizon,
            expected_action_utility=decision.expected_utility,
            action_scores=dict(decision.action_scores), tool_invoked=request.action_name.value,
            tool_status=result.status, fact_ids=observation.source_fact_ids,
            evidence_ids=observation.source_evidence_ids,
            document_ids=observation.source_document_ids,
            observation_token=observation.observation_token, belief_after=belief,
            investigation_cost=result.cost, latency_ms=result.latency_ms,
            evidence_support=interim.provenance_status,
        ))

    verdict = scenario.evidence_policy.evaluate(final_candidate, observations)
    return InvestigationOutcome(
        decision="ABSTAIN", final_belief=belief, evidence_verdict=verdict, steps=steps,
        total_cost=total_cost, termination_reason=reason,
        planning_runtime_ms=planning_ms, tool_runtime_ms=tool_ms,
        metadata={"scenario": scenario.name, "tenant_id": tenant_id},
    )
