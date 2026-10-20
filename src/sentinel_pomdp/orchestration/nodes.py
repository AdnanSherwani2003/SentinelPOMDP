"""Small deterministic nodes for the graph-backed investigation workflow."""
from __future__ import annotations

from time import perf_counter
from typing import Any

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.investigation.observations import UnsafeToolResult, adapt_result
from sentinel_pomdp.investigation.scenario import InvestigationScenario
from sentinel_pomdp.investigation.schemas import (
    EvidenceObservation, GraphInvestigationResult, InvestigationStep, ToolStatus,
)
from sentinel_pomdp.investigation.tools import GraphInvestigationTools
from sentinel_pomdp.multistep import MultiStepPlanner

from .state import InitialWorkflowInput, InvestigationGraphState, WorkflowTraceEvent


def _event(state: InvestigationGraphState, node_name: str, **values: Any) -> dict[str, Any]:
    return WorkflowTraceEvent(sequence=len(state.get("workflow_trace", [])) + 1,
                              node_name=node_name, **values).model_dump(mode="json")


def _trace(state: InvestigationGraphState, event: dict[str, Any]) -> list[dict[str, Any]]:
    return [*state.get("workflow_trace", []), event]


def _checkpoint_safe_result(result: GraphInvestigationResult) -> dict[str, Any]:
    """Keep typed metadata and references while omitting untrusted text snippets."""
    payload = result.model_dump(mode="json")
    for record in payload["supporting_evidence"] + payload["contradicting_evidence"]:
        record["content"] = "[omitted from workflow state]"
    return payload


class InvestigationNodes:
    def __init__(self, repository: BaseGraphRepository, scenario: InvestigationScenario,
                 planner: MultiStepPlanner) -> None:
        self.repository = repository
        self.scenario = scenario
        self.planner = planner
        self.tools = GraphInvestigationTools(repository)
        self.scenario_id = scenario.scenario_id or scenario.name

    def initialize(self, state: InvestigationGraphState) -> dict[str, Any]:
        started = perf_counter()
        inputs = InitialWorkflowInput.model_validate(state)
        if inputs.scenario_id != self.scenario_id:
            raise ValueError(f"scenario_id must be {self.scenario_id!r}")
        if inputs.model_version != self.scenario.model_version:
            raise ValueError("checkpoint model version does not match this workflow")
        if any(request.tenant_id != inputs.tenant_id for request in self.scenario.requests.values()):
            raise ValueError("tenant scope does not match the scenario's authorized requests")
        if abs(sum(self.scenario.prior.values()) - 1.0) > 1e-9:
            raise ValueError("scenario prior must sum to one")
        base: InvestigationGraphState = {
            "tenant_id": inputs.tenant_id,
            "scenario_id": inputs.scenario_id,
            "model_version": inputs.model_version,
            "hypotheses": list(self.scenario.prior),
            "current_belief": dict(self.scenario.prior),
            "planning_horizon": inputs.planning_horizon,
            "max_tool_calls": inputs.max_tool_calls,
            "investigation_count": 0,
            "remaining_budget": inputs.initial_budget,
            "total_cost": 0.0,
            "pending_action": None,
            "planner_decision": None,
            "proposed_hypothesis": None,
            "latest_tool_result": None,
            "latest_observation": None,
            "action_history": [],
            "observations": [],
            "seen_evidence_ids": [],
            "seen_document_ids": [],
            "investigation_steps": [],
            "workflow_trace": [],
            "evidence_status": None,
            "evidence_verdict": None,
            "terminal_decision": None,
            "final_hypothesis": None,
            "termination_reason": None,
            "error": None,
            "planning_runtime_ms": 0.0,
            "tool_runtime_ms": 0.0,
            "final_outcome": None,
        }
        event = _event(base, "initialize", belief_after=base["current_belief"],
                       node_runtime_ms=(perf_counter() - started) * 1000)
        base["workflow_trace"] = [event]
        return dict(base)

    def plan(self, state: InvestigationGraphState) -> dict[str, Any]:
        started = perf_counter()
        try:
            decision = self.planner.decide(
                state["current_belief"],
                history=tuple(tuple(item) for item in state["action_history"]),
                horizon=state["planning_horizon"],
            )
            if decision.kind not in {"INVESTIGATE", "ANSWER", "ABSTAIN"}:
                raise ValueError(f"invalid planner decision: {decision.kind!r}")
            pending = decision.action
            error = None
            reason = None
            kind = decision.kind
            if kind == "INVESTIGATE":
                if not pending or pending not in self.scenario.requests:
                    raise ValueError(f"planner selected unknown action {pending!r}")
                used = {item[0] for item in state["action_history"]}
                if pending in used:
                    raise ValueError(f"planner repeated action {pending!r}")
                cost = self.tools.costs[self.scenario.requests[pending].action_name]
                if state["investigation_count"] >= state["max_tool_calls"]:
                    kind, pending, reason = "ABSTAIN", None, "maximum investigation tool calls exhausted"
                elif cost > state["remaining_budget"] + 1e-12:
                    kind, pending, reason = "ABSTAIN", None, "investigation budget exhausted"
            payload = {
                "kind": kind, "action": pending,
                "hypothesis": decision.hypothesis,
                "expected_utility": decision.expected_utility,
                "action_scores": list(decision.action_scores),
            }
        except Exception as exc:
            payload = {"kind": "INVALID", "action": None, "hypothesis": None,
                       "expected_utility": 0.0, "action_scores": []}
            pending, reason = None, "planner failure"
            error = f"{type(exc).__name__}: {exc}"
        elapsed = (perf_counter() - started) * 1000
        event = _event(state, "plan", route=payload["kind"], planner_action=pending,
                       planner_horizon=state["planning_horizon"],
                       expected_utility=payload["expected_utility"],
                       belief_before=state["current_belief"], node_runtime_ms=elapsed,
                       termination_reason=reason, error=error)
        return {
            "pending_action": pending,
            "planner_decision": payload,
            "proposed_hypothesis": payload.get("hypothesis"),
            "termination_reason": reason,
            "error": error,
            "planning_runtime_ms": state["planning_runtime_ms"] + elapsed,
            "workflow_trace": _trace(state, event),
        }

    def investigate(self, state: InvestigationGraphState) -> dict[str, Any]:
        started = perf_counter()
        action = state["pending_action"]
        request = self.scenario.requests[action]
        result = self.tools.execute(request, authorized_tenant_id=state["tenant_id"])
        elapsed = (perf_counter() - started) * 1000
        event = _event(state, "investigate", route="adapt_observation", planner_action=action,
                       tool_name=request.action_name.value, tool_status=result.status.value,
                       evidence_ids=result.evidence_ids, source_document_ids=result.document_ids,
                       investigation_cost=result.cost, node_runtime_ms=elapsed)
        return {
            "latest_tool_result": _checkpoint_safe_result(result),
            "investigation_count": state["investigation_count"] + 1,
            "remaining_budget": max(0.0, state["remaining_budget"] - result.cost),
            "total_cost": state["total_cost"] + result.cost,
            "tool_runtime_ms": state["tool_runtime_ms"] + (result.latency_ms or elapsed),
            "workflow_trace": _trace(state, event),
        }

    def adapt_observation(self, state: InvestigationGraphState) -> dict[str, Any]:
        started = perf_counter()
        result = GraphInvestigationResult.model_validate(state["latest_tool_result"])
        error = None
        observation_payload = None
        try:
            observation = adapt_result(
                state["pending_action"], result,
                seen_evidence_ids=set(state["seen_evidence_ids"]),
                seen_document_ids=set(state["seen_document_ids"]),
            )
            observation_payload = observation.model_dump(mode="json")
            route = "bayesian_update"
        except UnsafeToolResult as exc:
            error = f"unsafe tool result: {exc}"
            route = "finalize"
        elapsed = (perf_counter() - started) * 1000
        event = _event(state, "adapt_observation", route=route,
                       planner_action=state["pending_action"],
                       tool_status=result.status.value,
                       observation=(observation_payload or {}).get("observation_token"),
                       node_runtime_ms=elapsed, error=error)
        return {"latest_observation": observation_payload, "error": error,
                "termination_reason": error,
                "workflow_trace": _trace(state, event)}

    def bayesian_update(self, state: InvestigationGraphState) -> dict[str, Any]:
        started = perf_counter()
        before = dict(state["current_belief"])
        observation = EvidenceObservation.model_validate(state["latest_observation"])
        action = state["pending_action"]
        token = observation.observation_token.value
        error = None
        try:
            after = self.planner.posterior(before, action, token)
            if abs(sum(after.values()) - 1.0) > 1e-9:
                raise ValueError("posterior is not normalized")
        except Exception as exc:
            after = before
            error = f"Bayesian update failed: {type(exc).__name__}: {exc}"
        elapsed = (perf_counter() - started) * 1000
        result = GraphInvestigationResult.model_validate(state["latest_tool_result"])
        observations = [*state["observations"], observation.model_dump(mode="json")]
        candidate = max(after, key=after.get)
        interim = self.scenario.evidence_policy.evaluate(
            candidate, [EvidenceObservation.model_validate(item) for item in observations]
        )
        decision = state["planner_decision"]
        step = InvestigationStep(
            step_number=state["investigation_count"], belief_before=before,
            chosen_action=action, planner_horizon=state["planning_horizon"],
            expected_action_utility=decision["expected_utility"],
            action_scores=dict(decision["action_scores"]),
            tool_invoked=result.action_name.value, tool_status=result.status,
            fact_ids=observation.source_fact_ids,
            evidence_ids=observation.source_evidence_ids,
            document_ids=observation.source_document_ids,
            observation_token=observation.observation_token,
            belief_after=after, investigation_cost=result.cost,
            latency_ms=result.latency_ms, evidence_support=interim.provenance_status,
        ).model_dump(mode="json")
        event = _event(state, "bayesian_update", route="plan", planner_action=action,
                       observation=token, belief_before=before, belief_after=after,
                       evidence_ids=observation.source_evidence_ids,
                       source_document_ids=observation.source_document_ids,
                       evidence_gate_verdict=interim.provenance_status,
                       node_runtime_ms=elapsed, error=error)
        return {
            "current_belief": after,
            "action_history": [*state["action_history"], [action, token]],
            "observations": observations,
            "seen_evidence_ids": sorted(set(state["seen_evidence_ids"]) | set(observation.source_evidence_ids)),
            "seen_document_ids": sorted(set(state["seen_document_ids"]) | set(observation.source_document_ids)),
            "investigation_steps": [*state["investigation_steps"], step],
            "latest_tool_result": None,
            "latest_observation": None,
            "pending_action": None,
            "error": error,
            "termination_reason": error,
            "workflow_trace": _trace(state, event),
        }

    def evidence_gate(self, state: InvestigationGraphState) -> dict[str, Any]:
        started = perf_counter()
        observations = [EvidenceObservation.model_validate(item) for item in state["observations"]]
        candidate = state["proposed_hypothesis"]
        verdict = self.scenario.evidence_policy.evaluate(candidate, observations)
        approved = verdict.sufficient
        decision = "ANSWER" if approved else "ABSTAIN"
        reason = ("mathematical answer and evidence gate both satisfied" if approved else verdict.reason)
        elapsed = (perf_counter() - started) * 1000
        event = _event(state, "evidence_gate", route="finalize",
                       evidence_gate_verdict=verdict.provenance_status,
                       node_runtime_ms=elapsed, termination_reason=reason)
        return {"terminal_decision": decision,
                "final_hypothesis": candidate if approved else None,
                "evidence_status": verdict.provenance_status,
                "evidence_verdict": verdict.model_dump(mode="json"),
                "termination_reason": reason,
                "workflow_trace": _trace(state, event)}

    def finalize(self, state: InvestigationGraphState) -> dict[str, Any]:
        from sentinel_pomdp.investigation.schemas import EvidenceVerdict, InvestigationOutcome

        started = perf_counter()
        observations = [EvidenceObservation.model_validate(item) for item in state["observations"]]
        decision = state.get("terminal_decision")
        if not decision:
            planner_kind = (state.get("planner_decision") or {}).get("kind")
            decision = "ABSTAIN" if planner_kind != "ANSWER" else "ABSTAIN"
        hypothesis = state.get("final_hypothesis") if decision == "ANSWER" else None
        verdict = (EvidenceVerdict.model_validate(state["evidence_verdict"])
                   if state.get("evidence_verdict")
                   else self.scenario.evidence_policy.evaluate(hypothesis, observations))
        reason = state.get("termination_reason") or (
            "planner selected abstention" if decision == "ABSTAIN" else verdict.reason
        )
        steps = list(state["investigation_steps"])
        planner = state.get("planner_decision") or {}
        if planner.get("kind") in {"ANSWER", "ABSTAIN"}:
            steps.append(InvestigationStep(
                step_number=state["investigation_count"] + 1,
                belief_before=state["current_belief"], chosen_action=planner["kind"],
                planner_horizon=state["planning_horizon"],
                expected_action_utility=planner.get("expected_utility", 0.0),
                action_scores=dict(planner.get("action_scores", [])),
                belief_after=state["current_belief"],
                evidence_support=verdict.provenance_status,
            ).model_dump(mode="json"))
        elapsed = (perf_counter() - started) * 1000
        event = _event(state, "finalize", route="END",
                       belief_after=state["current_belief"],
                       evidence_gate_verdict=verdict.provenance_status,
                       node_runtime_ms=elapsed, termination_reason=reason,
                       error=state.get("error"))
        workflow_trace = _trace(state, event)
        outcome = InvestigationOutcome(
            decision=decision, selected_hypothesis=hypothesis,
            final_belief=state["current_belief"], evidence_verdict=verdict,
            steps=steps, total_cost=state["total_cost"], termination_reason=reason,
            planning_runtime_ms=state["planning_runtime_ms"],
            tool_runtime_ms=state["tool_runtime_ms"],
            metadata={"scenario": self.scenario.name, "scenario_id": self.scenario_id,
                      "tenant_id": state["tenant_id"], "orchestrator": "langgraph",
                      "tool_calls": state["investigation_count"],
                      "workflow_trace": workflow_trace},
        )
        return {"terminal_decision": decision, "final_hypothesis": hypothesis,
                "termination_reason": reason, "workflow_trace": workflow_trace,
                "final_outcome": outcome.model_dump(mode="json")}
