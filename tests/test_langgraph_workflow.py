from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.graph.schemas import Document
from sentinel_pomdp.investigation import (
    build_scenario_planner, conflicting_delivery_scenario, missing_evidence_scenario,
    multi_investigation_scenario, run_graph_investigation, supplier_delay_scenario,
    supplier_shipment_delay_scenario,
)
from sentinel_pomdp.multistep import PlanDecision
from sentinel_pomdp.orchestration import InvestigationWorkflow, build_investigation_workflow


@pytest.fixture()
def repository():
    repo = InMemoryGraphRepository()
    assert KnowledgeGraphIngestionPipeline(repo).ingest_dataset(generate_supplier_delay_dataset()).is_success
    return repo


def workflow_for(repo, scenario, horizon=2, checkpoint=False):
    return build_investigation_workflow(repo, scenario, build_scenario_planner(scenario, horizon),
                                        checkpoint=checkpoint)


def test_stategraph_has_explicit_nodes_start_end_and_cycle(repository):
    workflow = workflow_for(repository, supplier_shipment_delay_scenario())
    graph = workflow.app.get_graph()
    assert {"__start__", "initialize", "plan", "investigate", "adapt_observation",
            "bayesian_update", "evidence_gate", "finalize", "__end__"}.issubset(graph.nodes)
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("__start__", "initialize") in edges
    assert ("bayesian_update", "plan") in edges
    assert ("finalize", "__end__") in edges


def test_answer_branch_uses_actual_tool_observation_and_bayes(repository):
    scenario = supplier_shipment_delay_scenario()
    outcome = workflow_for(repository, scenario).run("tenant_alpha")
    assert outcome.decision == "ANSWER"
    assert outcome.selected_hypothesis == "shipment_delayed"
    assert outcome.final_belief["shipment_delayed"] == pytest.approx(.8869109947643979)
    assert outcome.evidence_verdict.document_ids == ["doc_telematics_002", "doc_wh_log_001"]
    routes = [e["route"] for e in outcome.metadata["workflow_trace"]]
    assert "INVESTIGATE" in routes and "bayesian_update" in routes and "finalize" in routes


@pytest.mark.parametrize("factory, expected_status", [
    (conflicting_delivery_scenario, "CONFLICTED"),
    (missing_evidence_scenario, "INSUFFICIENT"),
])
def test_abstain_branches_preserve_evidence_status(repository, factory, expected_status):
    scenario = factory()
    outcome = workflow_for(repository, scenario).run("tenant_alpha")
    assert outcome.decision == "ABSTAIN"
    assert outcome.evidence_verdict.provenance_status == expected_status


def test_high_posterior_causal_claim_is_rejected_as_irrelevant_support(repository):
    scenario = supplier_delay_scenario()
    outcome = workflow_for(repository, scenario).run("tenant_alpha")
    assert outcome.final_belief["supplier_a"] == pytest.approx(.84)
    assert outcome.decision == "ABSTAIN"
    assert outcome.evidence_verdict.provenance_status == "IRRELEVANT_SUPPORT"
    assert "claim-specific" in outcome.termination_reason


def test_genuine_two_cycle_workflow_replans_after_each_posterior(repository):
    scenario = multi_investigation_scenario()
    outcome = workflow_for(repository, scenario, horizon=2).run("tenant_alpha", max_tool_calls=3)
    investigations = [step for step in outcome.steps if step.tool_invoked]
    assert [step.chosen_action for step in investigations] == [
        "inspect_supplier_signal", "inspect_internal_signal"]
    assert investigations[0].belief_after != investigations[0].belief_before
    assert investigations[1].belief_before == investigations[0].belief_after
    assert investigations[1].belief_after != investigations[1].belief_before
    assert outcome.total_cost == pytest.approx(.16)


def test_limits_terminate_without_duplicate_cost(repository):
    scenario = multi_investigation_scenario()
    outcome = workflow_for(repository, scenario).run("tenant_alpha", max_tool_calls=1)
    assert outcome.decision == "ABSTAIN"
    assert outcome.metadata["tool_calls"] == 1
    assert outcome.total_cost == pytest.approx(.08)
    assert "maximum" in outcome.termination_reason

    no_budget = workflow_for(repository, scenario).run("tenant_alpha", budget=0)
    assert no_budget.total_cost == 0
    assert no_budget.metadata["tool_calls"] == 0
    assert "budget" in no_budget.termination_reason


def test_checkpointed_completed_run_is_idempotent(repository):
    scenario = supplier_shipment_delay_scenario()
    workflow = InvestigationWorkflow(repository, scenario, build_scenario_planner(scenario),
                                     checkpointer=InMemorySaver())
    first = workflow.run("tenant_alpha", thread_id="stable-run")
    second = workflow.run("tenant_alpha", thread_id="stable-run")
    assert second.total_cost == first.total_cost
    assert second.final_belief == first.final_belief
    assert second.metadata["tool_calls"] == 1
    assert len(second.metadata["workflow_trace"]) == len(first.metadata["workflow_trace"])
    with pytest.raises(ValueError, match="tenant"):
        workflow.run("tenant_beta", thread_id="stable-run")


def test_direct_runner_and_langgraph_preserve_mathematical_result(repository):
    scenario = supplier_shipment_delay_scenario()
    direct = run_graph_investigation(repository, scenario, build_scenario_planner(scenario),
                                     "tenant_alpha")
    graph = workflow_for(repository, scenario).run("tenant_alpha")
    assert graph.decision == direct.decision
    assert graph.selected_hypothesis == direct.selected_hypothesis
    assert graph.final_belief == pytest.approx(direct.final_belief)
    assert graph.evidence_verdict.evidence_ids == direct.evidence_verdict.evidence_ids
    assert graph.total_cost == direct.total_cost


def test_database_failure_routes_to_safe_abstention(repository, monkeypatch):
    scenario = supplier_shipment_delay_scenario()
    monkeypatch.setattr(repository, "get_provenance_chain",
                        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("offline")))
    outcome = workflow_for(repository, scenario).run("tenant_alpha")
    assert outcome.decision == "ABSTAIN"
    assert outcome.final_belief == scenario.prior
    assert "DATABASE_UNAVAILABLE" in str(outcome.metadata["workflow_trace"])
    assert "unsafe tool result" in outcome.termination_reason


class InvalidPlanner:
    config = SimpleNamespace(horizon=2)

    def decide(self, belief, history=(), horizon=None):
        return PlanDecision("MAGIC", None, None, 0.0, ())


def test_invalid_planner_decision_routes_to_safe_terminal(repository):
    scenario = supplier_shipment_delay_scenario()
    outcome = InvestigationWorkflow(repository, scenario, InvalidPlanner()).run("tenant_alpha")
    assert outcome.decision == "ABSTAIN"
    assert outcome.total_cost == 0
    assert "invalid planner decision" in str(outcome.metadata["workflow_trace"])


class UnknownActionPlanner(InvalidPlanner):
    def decide(self, belief, history=(), horizon=None):
        return PlanDecision("INVESTIGATE", "unregistered_tool", None, 0.0, ())


def test_unknown_action_never_reaches_tool_layer(repository):
    scenario = supplier_shipment_delay_scenario()
    outcome = InvestigationWorkflow(repository, scenario, UnknownActionPlanner()).run("tenant_alpha")
    assert outcome.decision == "ABSTAIN"
    assert outcome.total_cost == 0
    assert "unknown action" in str(outcome.metadata["workflow_trace"])


def test_hash_mismatch_and_missing_source_fail_evidence_gate(repository):
    scenario = supplier_shipment_delay_scenario()
    document = repository.get_document("doc_wh_log_001", "tenant_alpha")
    repository.upsert_document(Document(**{**document.model_dump(), "raw_content": "tampered"}))
    mismatch = workflow_for(repository, scenario).run("tenant_alpha")
    assert mismatch.decision == "ABSTAIN"
    assert any(step.observation_token and step.observation_token.value == "SOURCE_HASH_MISMATCH"
               for step in mismatch.steps)

    fresh = InMemoryGraphRepository()
    KnowledgeGraphIngestionPipeline(fresh).ingest_dataset(generate_supplier_delay_dataset())
    del fresh.documents[("tenant_alpha", "doc_wh_log_001")]
    del fresh.documents[("tenant_alpha", "doc_telematics_002")]
    missing = workflow_for(fresh, scenario).run("tenant_alpha")
    assert missing.decision == "ABSTAIN"
    assert not missing.evidence_verdict.evidence_ids


def test_unauthorized_tenant_is_rejected_before_tool_execution(repository):
    scenario = supplier_shipment_delay_scenario()
    with pytest.raises(ValueError, match="tenant scope"):
        workflow_for(repository, scenario).run("tenant_beta")
