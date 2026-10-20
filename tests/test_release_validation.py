"""Final release regressions at independently audited trust boundaries."""
import secrets

from fastapi.testclient import TestClient
import pytest

from sentinel_pomdp.api.app import create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.domains import DomainPackStatus, procurement_demo_pack
from sentinel_pomdp.multistep import MultiStepPlanner, PlanningConfig
from sentinel_pomdp.security import Permission


@pytest.mark.parametrize("route", ["/api/v1/domains", "/api/v1/company-data/domain-packs"])
@pytest.mark.parametrize("status", [DomainPackStatus.APPROVED, DomainPackStatus.ACTIVE])
def test_author_cannot_upload_approved_or_active_pack(tmp_path, route, status):
    key = secrets.token_urlsafe(32)
    settings = AppSettings(api_key=key, tenant_id="release-test", principal_id="author",
        permissions=frozenset({Permission.DOMAIN_PACK_MANAGE}),
        document_store_path=str(tmp_path / "docs"),
        operations_database_path=str(tmp_path / "ops.db"))
    app = create_app(settings)
    pack = procurement_demo_pack("release-test", status=status, approved_by="author")
    with TestClient(app) as client:
        response = client.post(route, headers={"Authorization": f"Bearer {key}"},
                               json=pack.model_dump(mode="json"))
        assert response.status_code == 422
        assert app.state.dependencies.domain_packs.get("release-test", pack.domain_id) is None


@pytest.mark.parametrize("route", ["/api/v1/domains", "/api/v1/company-data/domain-packs"])
def test_upload_cannot_demote_or_rewrite_reviewed_metadata(tmp_path, route):
    key = secrets.token_urlsafe(32)
    settings = AppSettings(api_key=key, tenant_id="release-test",
        permissions=frozenset({Permission.DOMAIN_PACK_MANAGE}),
        document_store_path=str(tmp_path / "docs"),
        operations_database_path=str(tmp_path / "ops.db"))
    app = create_app(settings)
    packs = app.state.dependencies.domain_packs
    original = procurement_demo_pack("release-test", status=DomainPackStatus.ACTIVE,
                                     approved_by="trusted-reviewer")
    packs.save("release-test", original)
    changed = original.model_copy(update={"status": DomainPackStatus.DRAFT, "approved_by": None})
    with TestClient(app) as client:
        response = client.post(route, headers={"Authorization": f"Bearer {key}"},
                               json=changed.model_dump(mode="json"))
        assert response.status_code == 422
        retained = packs.get_version("release-test", original.domain_id, original.model_version)
        assert retained.status == DomainPackStatus.ACTIVE
        assert retained.approved_by == "trusted-reviewer"


def test_independent_two_state_bayes_reference_and_invalid_input():
    # P(A|+) = (3/5 * 4/5) / (3/5 * 4/5 + 2/5 * 1/5) = 6/7.
    planner = MultiStepPlanner(states=["A", "B"],
        observation_model={"inspect": {"A": {"+": .8, "-": .2},
                                       "B": {"+": .2, "-": .8}}},
        action_costs={"inspect": .1}, config=PlanningConfig(horizon=1))
    posterior = planner.posterior({"A": .6, "B": .4}, "inspect", "+")
    assert posterior == pytest.approx({"A": 6 / 7, "B": 1 / 7})
    assert sum(posterior.values()) == pytest.approx(1)
    with pytest.raises(ValueError):
        planner.posterior({"A": float("nan"), "B": .4}, "inspect", "+")
    with pytest.raises(KeyError):
        planner.posterior({"A": .6, "B": .4}, "unregistered", "+")


def test_web_concurrency_cannot_bypass_single_api_process_guard(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.setenv("SENTINEL_API_WORKERS", "1")
    settings = AppSettings.from_environment()
    assert any("multi-process API is disabled" in error for error in settings.validate())


@pytest.mark.parametrize("invalid", [-1.0, float("nan"), float("inf")])
def test_legacy_belief_rejects_invalid_weights_and_priors(invalid):
    from sentinel_pomdp.belief import BeliefDistribution, initial_belief, update_belief
    from sentinel_pomdp.actions import InvestigationAction
    from sentinel_pomdp.observations import Observation
    from sentinel_pomdp.states import SecurityState

    with pytest.raises(ValueError):
        BeliefDistribution({SecurityState.BENIGN: invalid})
    belief = initial_belief()
    belief[SecurityState.BENIGN] = invalid
    # Input rejection must precede action/observation table access.
    with pytest.raises(ValueError, match="Belief probabilities"):
        update_belief(belief, next(iter(InvestigationAction)), next(iter(Observation)))


def test_checkpoint_revalidates_source_without_repeating_updates():
    from langgraph.checkpoint.memory import InMemorySaver
    from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
    from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
    from sentinel_pomdp.graph.repository import InMemoryGraphRepository
    from sentinel_pomdp.investigation import supplier_shipment_delay_scenario, build_scenario_planner
    from sentinel_pomdp.orchestration import InvestigationWorkflow

    graph = InMemoryGraphRepository()
    assert KnowledgeGraphIngestionPipeline(graph).ingest_dataset(generate_supplier_delay_dataset()).is_success
    scenario = supplier_shipment_delay_scenario()
    workflow = InvestigationWorkflow(graph, scenario, build_scenario_planner(scenario), checkpointer=InMemorySaver())
    first = workflow.run("tenant_alpha", thread_id="interrupted-job")
    assert first.decision == "ANSWER"
    graph.deactivate_document("doc_wh_log_001", "tenant_alpha")
    restored = workflow.run("tenant_alpha", thread_id="interrupted-job")
    assert restored.decision == "ABSTAIN"
    assert restored.final_belief == first.final_belief
    assert restored.total_cost == first.total_cost
    assert restored.metadata["tool_calls"] == first.metadata["tool_calls"] == 1


def test_all_registered_required_facts_must_be_supported():
    from sentinel_pomdp.investigation.evidence_policy import EvidencePolicy
    from sentinel_pomdp.investigation.schemas import EvidenceObservation, ObservationToken, ToolStatus

    policy = EvidencePolicy(required_fact_ids={"claim": {"f1", "f2"}})
    observed = EvidenceObservation(action_name="inspect", observation_token=ObservationToken.SUPPORTED,
        source_fact_ids=["f1"], source_evidence_ids=["e1"], source_document_ids=["d1"],
        source_signal_groups=["g1"], evidence_status=ToolStatus.EVIDENCE_FOUND, provenance_verified=True)
    assert not policy.evaluate("claim", [observed]).sufficient
