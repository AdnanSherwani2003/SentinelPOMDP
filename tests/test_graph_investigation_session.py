from __future__ import annotations

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.investigation.evidence_policy import EvidencePolicy
from sentinel_pomdp.investigation.scenario import (
    InvestigationScenario, build_scenario_planner, supplier_delay_scenario,
    supplier_shipment_delay_scenario,
)
from sentinel_pomdp.investigation.schemas import GraphInvestigationRequest, InvestigationAction
from sentinel_pomdp.investigation.session import run_graph_investigation


def populated():
    repo = InMemoryGraphRepository()
    KnowledgeGraphIngestionPipeline(repo).ingest_dataset(generate_supplier_delay_dataset())
    return repo


def test_planner_selected_action_executes_graph_and_changes_posterior():
    scenario = supplier_shipment_delay_scenario()
    planner = build_scenario_planner(scenario, horizon=2)
    result = run_graph_investigation(populated(), scenario, planner, "tenant_alpha")
    first = result.steps[0]
    assert first.chosen_action == planner.decide(scenario.prior).action
    assert first.tool_invoked == "investigate_fact_evidence"
    assert first.fact_ids == ["fact_sup_a_caused_delay"]
    assert first.belief_after != first.belief_before
    assert result.decision == "ANSWER"
    assert result.selected_hypothesis == "shipment_delayed"
    assert result.evidence_verdict.evidence_ids == ["ev_telematics_truck_customs", "ev_wh_log_apx101_late"]


def test_causal_attribution_requires_claim_specific_evidence():
    scenario = supplier_delay_scenario()
    result = run_graph_investigation(populated(), scenario, build_scenario_planner(scenario),
                                     "tenant_alpha")
    assert result.final_belief["supplier_a"] > .8
    assert result.decision == "ABSTAIN"
    assert result.evidence_verdict.provenance_status == "IRRELEVANT_SUPPORT"


def single_action_scenario(fact_id, *, required_fact, prior=None):
    return InvestigationScenario(
        name=fact_id,
        prior=prior or {"claim": .7, "alternative": .3},
        requests={"inspect_claim": GraphInvestigationRequest(
            tenant_id="tenant_alpha", action_name=InvestigationAction.FACT_EVIDENCE,
            target_id=fact_id)},
        action_targets={"inspect_claim": "claim"},
        evidence_policy=EvidencePolicy(required_fact_ids={"claim": {required_fact}, "alternative": set()}),
        answer_threshold=.7,
    )


def test_conflicting_evidence_forces_abstention_even_if_prior_is_high():
    scenario = single_action_scenario("fact_sup_b_delivered_ontime",
                                      required_fact="fact_sup_b_delivered_ontime",
                                      prior={"claim": .9, "alternative": .1})
    result = run_graph_investigation(populated(), scenario, build_scenario_planner(scenario),
                                     "tenant_alpha")
    assert result.steps[0].observation_token.value == "EVIDENCE_CONFLICTED"
    assert result.decision == "ABSTAIN"
    assert result.evidence_verdict.provenance_status == "CONFLICTED"
    assert result.evidence_verdict.evidence_ids == ["ev_dock_b_late_damaged", "ev_sup_b_claimed_ontime"]


def test_missing_evidence_forces_abstention():
    scenario = single_action_scenario("fact_comp_a_qa_certified",
                                      required_fact="fact_comp_a_qa_certified")
    result = run_graph_investigation(populated(), scenario, build_scenario_planner(scenario),
                                     "tenant_alpha")
    assert result.steps[0].observation_token.value == "EVIDENCE_NOT_FOUND"
    assert result.decision == "ABSTAIN"


def test_budget_prevents_tool_execution():
    scenario = supplier_delay_scenario()
    result = run_graph_investigation(populated(), scenario, build_scenario_planner(scenario),
                                     "tenant_alpha", budget=.01)
    assert result.decision == "ABSTAIN"
    assert result.total_cost == 0
    assert not result.steps
    assert "budget" in result.termination_reason


def test_high_posterior_cannot_bypass_registered_evidence_gate():
    policy = EvidencePolicy(required_fact_ids={"claim": {"causal_fact"}})
    verdict = policy.evaluate("claim", [])
    assert not verdict.sufficient
