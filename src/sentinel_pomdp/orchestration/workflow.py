"""StateGraph construction, invocation, and lightweight checkpoint handling."""
from __future__ import annotations

from uuid import uuid4
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.investigation.scenario import InvestigationScenario
from sentinel_pomdp.investigation.schemas import InvestigationOutcome
from sentinel_pomdp.multistep import MultiStepPlanner

from .nodes import InvestigationNodes
from .routing import route_after_update, route_observation, route_planner_decision
from .state import InvestigationGraphState


class FactualGraphState(TypedDict, total=False):
    result: Any


def run_factual_investigation(evaluate: Callable[[], Any]) -> Any:
    """Use LangGraph for registered factual evidence retrieval and terminal gating.

    Read-only retries are journaled by the existing durable worker. Probabilistic
    investigations continue through InvestigationWorkflow and its checkpoints.
    """
    def retrieve(_: FactualGraphState) -> FactualGraphState:
        return {"result": evaluate()}

    def gate(state: FactualGraphState) -> FactualGraphState:
        result = state["result"]
        payload = result if isinstance(result, dict) else result.model_dump(mode="json")
        if payload.get("decision") not in {"ANSWER", "ABSTAIN"}:
            raise ValueError("factual adapter returned an unsupported terminal decision")
        if payload["decision"] == "ANSWER" and (
                not payload.get("provenance_verified")
                or payload.get("classification") not in {"MATCH_SUPPORTED", "MISMATCH_SUPPORTED"}):
            raise ValueError("factual answer requires verified supporting provenance")
        return state

    builder = StateGraph(FactualGraphState)
    builder.add_node("retrieve_evidence", retrieve)
    builder.add_node("factual_evidence_gate", gate)
    builder.add_edge(START, "retrieve_evidence")
    builder.add_edge("retrieve_evidence", "factual_evidence_gate")
    builder.add_edge("factual_evidence_gate", END)
    return builder.compile(name="sentinel-factual-investigation").invoke({})["result"]


class InvestigationWorkflow:
    """Compiled workflow with runtime dependencies kept outside serializable state."""

    def __init__(self, repository: BaseGraphRepository, scenario: InvestigationScenario,
                 planner: MultiStepPlanner, *, checkpointer: BaseCheckpointSaver | None = None) -> None:
        self.scenario = scenario
        self.nodes = InvestigationNodes(repository, scenario, planner)
        self.checkpointer = checkpointer
        builder = StateGraph(InvestigationGraphState)
        builder.add_node("initialize", self.nodes.initialize)
        builder.add_node("plan", self.nodes.plan)
        builder.add_node("investigate", self.nodes.investigate)
        builder.add_node("adapt_observation", self.nodes.adapt_observation)
        builder.add_node("bayesian_update", self.nodes.bayesian_update)
        builder.add_node("evidence_gate", self.nodes.evidence_gate)
        builder.add_node("finalize", self.nodes.finalize)
        builder.add_edge(START, "initialize")
        builder.add_edge("initialize", "plan")
        builder.add_conditional_edges("plan", route_planner_decision, {
            "investigate": "investigate", "evidence_gate": "evidence_gate", "finalize": "finalize",
        })
        builder.add_edge("investigate", "adapt_observation")
        builder.add_conditional_edges("adapt_observation", route_observation, {
            "bayesian_update": "bayesian_update", "finalize": "finalize",
        })
        builder.add_conditional_edges("bayesian_update", route_after_update, {
            "plan": "plan", "finalize": "finalize",
        })
        builder.add_edge("evidence_gate", "finalize")
        builder.add_edge("finalize", END)
        self.builder = builder
        self.app = builder.compile(checkpointer=checkpointer, name="sentinel-investigation")

    def _revalidate_answer(self, outcome: InvestigationOutcome, tenant_id: str) -> InvestigationOutcome:
        """Check current sources without replaying actions, costs or Bayesian updates."""
        if outcome.decision != "ANSWER":
            return outcome
        from sentinel_pomdp.graph.provenance import validate_evidence_chain
        from sentinel_pomdp.investigation.schemas import InvestigationStep

        verdict = outcome.evidence_verdict
        evidence, documents, groups = set(), set(), set()
        valid = bool(verdict.fact_ids and verdict.evidence_ids)
        try:
            for fact_id in verdict.fact_ids:
                checked = validate_evidence_chain(self.nodes.repository, fact_id, tenant_id)
                valid = valid and checked.is_reliable
                if checked.chain:
                    for source in checked.chain.supporting_evidence:
                        if source.evidence_id in verdict.evidence_ids:
                            evidence.add(source.evidence_id)
                            documents.add(source.document_id)
                            groups.add(source.source_group or source.evidence_id)
        except Exception:
            # An unavailable source store is operational uncertainty, never new
            # negative evidence or an observation to feed back into Bayes.
            valid = False
        policy = self.scenario.evidence_policy
        valid = (valid and set(verdict.evidence_ids).issubset(evidence)
                 and len(documents) >= policy.minimum_distinct_documents
                 and len(groups) >= policy.minimum_independent_sources)
        if valid:
            return outcome
        reason = "Current source evidence changed or is unavailable; revalidation is required."
        revised = verdict.model_copy(update={"sufficient": False, "hypothesis": None,
            "provenance_status": "REVALIDATION_REQUIRED", "reason": reason})
        gate_step = InvestigationStep(step_number=len(outcome.steps) + 1,
            belief_before=outcome.final_belief, belief_after=outcome.final_belief,
            chosen_action="ABSTAIN", planner_horizon=self.nodes.planner.config.horizon,
            expected_action_utility=0, action_scores={},
            investigation_cost=0, evidence_support="REVALIDATION_REQUIRED")
        return outcome.model_copy(update={"decision": "ABSTAIN", "selected_hypothesis": None,
            "evidence_verdict": revised, "termination_reason": reason,
            "steps": [*outcome.steps, gate_step],
            "metadata": {**outcome.metadata, "source_revalidation_required": True,
                         "original_terminal_decision": outcome.decision}})

    def run(self, tenant_id: str, *, thread_id: str | None = None,
            max_tool_calls: int = 3, budget: float = 1.0,
            recursion_limit: int = 50) -> InvestigationOutcome:
        run_id = thread_id or str(uuid4())
        config = {"configurable": {"thread_id": run_id}, "recursion_limit": recursion_limit}
        resume = False
        if self.checkpointer is not None:
            snapshot = self.app.get_state(config)
            if snapshot.values:
                if snapshot.values.get("tenant_id") != tenant_id:
                    raise ValueError("checkpoint tenant does not match the requested tenant")
                if snapshot.values.get("scenario_id") != self.nodes.scenario_id:
                    raise ValueError("checkpoint scenario does not match this workflow")
                if snapshot.values.get("model_version") != self.scenario.model_version:
                    raise ValueError("checkpoint model version does not match this workflow")
                resume = True
            if snapshot.values.get("final_outcome"):
                return self._revalidate_answer(
                    InvestigationOutcome.model_validate(snapshot.values["final_outcome"]), tenant_id)
        initial: InvestigationGraphState = {
            "tenant_id": tenant_id,
            "scenario_id": self.nodes.scenario_id,
            "model_version": self.scenario.model_version,
            "planning_horizon": self.nodes.planner.config.horizon,
            "max_tool_calls": max_tool_calls,
            "initial_budget": budget,
        }
        final = self.app.invoke(None if resume else initial, config)
        return self._revalidate_answer(InvestigationOutcome.model_validate(final["final_outcome"]), tenant_id)


def build_investigation_workflow(repository: BaseGraphRepository, scenario: InvestigationScenario,
                                 planner: MultiStepPlanner, *, checkpoint: bool = False) -> InvestigationWorkflow:
    return InvestigationWorkflow(repository, scenario, planner,
                                 checkpointer=InMemorySaver() if checkpoint else None)


def run_langgraph_investigation(repository: BaseGraphRepository, scenario: InvestigationScenario,
                                planner: MultiStepPlanner, tenant_id: str, *, max_tool_calls: int = 3,
                                budget: float = 1.0, thread_id: str | None = None,
                                checkpoint: bool = False) -> InvestigationOutcome:
    workflow = build_investigation_workflow(repository, scenario, planner, checkpoint=checkpoint)
    return workflow.run(tenant_id, thread_id=thread_id, max_tool_calls=max_tool_calls, budget=budget)
