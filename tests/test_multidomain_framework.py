from __future__ import annotations

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
import secrets
from concurrent.futures import ThreadPoolExecutor

from sentinel_pomdp.api.app import create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.domains import (
    DomainInvestigationService, DomainPack, DomainPackService, DomainPackStatus,
    OlistLogisticsAdapter, ProcurementAdapter, olist_logistics_pack,
    procurement_demo_pack, seed_synthetic_procurement,
)
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.ingestion.storage import LocalDocumentStore
from sentinel_pomdp.security import Permission
from sentinel_pomdp.operations import (
    DurableWorker, JobState, NewOperationJob, OperationType, SQLiteOperationRepository,
)
from sentinel_pomdp.operations.handlers import (
    domain_investigation_handler, domain_validation_handler,
)
from sentinel_pomdp.operations.worker import OperationContext


def approved_runtime(tmp_path, *, tenant="tenant-a", require_receipt=False):
    repository = InMemoryGraphRepository()
    packs = DomainPackService(LocalDocumentStore(tmp_path), repository)
    draft = procurement_demo_pack(tenant, require_goods_receipt=require_receipt)
    validated = packs.validate(tenant, draft)
    packs.save(tenant, validated)
    packs.submit_for_review(tenant, draft.domain_id, draft.model_version)
    packs.approve(tenant, draft.domain_id, draft.model_version, "reviewer-1")
    active = packs.activate(tenant, draft.domain_id, draft.model_version)
    runtime = DomainInvestigationService(packs, [ProcurementAdapter(repository)])
    return repository, packs, runtime, active


def test_factual_contract_rejects_executable_or_unknown_configuration():
    payload = procurement_demo_pack("tenant-a").model_dump(mode="json")
    payload["shell_command"] = "whoami"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DomainPack.model_validate(payload)
    payload.pop("shell_command")
    payload["registered_tools"] = ["arbitrary_cypher"]
    with pytest.raises(ValidationError, match="unknown registered tool"):
        DomainPack.model_validate(payload)
    payload = procurement_demo_pack("tenant-a").model_dump(mode="json")
    payload["schema_version"] = "999"
    with pytest.raises(ValidationError, match="unsupported domain-pack schema"):
        DomainPack.model_validate(payload)
    payload = procurement_demo_pack("tenant-a").model_dump(mode="json")
    payload["rewards"] = {"ABSTAIN": float("nan")}
    with pytest.raises(ValidationError, match="finite"):
        DomainPack.model_validate(payload)


def test_shared_langgraph_gate_rejects_an_ungrounded_factual_answer(tmp_path):
    from sentinel_pomdp.domains.execution import FactualInvestigationResult

    _, packs, _, active = approved_runtime(tmp_path)

    class UngroundedAdapter:
        domain_id = active.domain_id
        registered_tools = ProcurementAdapter.registered_tools

        def investigate(self, tenant_id, pack, question):
            return FactualInvestigationResult(domain_id=pack.domain_id,
                domain_version=pack.model_version, subject_id="INV-1001",
                decision="ANSWER", classification="MATCH_SUPPORTED",
                provenance_verified=False)

    runtime = DomainInvestigationService(packs, [UngroundedAdapter()])
    with pytest.raises(ValueError, match="verified supporting provenance"):
        runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")


def test_approved_probability_parameters_reach_existing_planner(tmp_path):
    from sentinel_pomdp.investigation.scenario import build_scenario_planner

    graph = InMemoryGraphRepository()
    seed_synthetic_procurement(graph, "tenant-a")
    packs = DomainPackService(LocalDocumentStore(tmp_path), graph)
    pack = DomainPack(domain_id="engineering_probability_test", name="Engineering only",
        tenant_owner="tenant-a", claim_type="test", hypotheses=["match", "mismatch"],
        prior={"match": .5, "mismatch": .5},
        actions=[{"action_id": "inspect_po", "cost": .2,
            "relation_hypotheses": {"PROCUREMENT_PURCHASE_ORDER_SNAPSHOT": "match"}}],
        observation_model={"inspect_po": {"match": {"EVIDENCE_SUPPORTED": 1.0},
                                             "mismatch": {"EVIDENCE_SUPPORTED": 1.0}}},
        answer_threshold=.8, model_version="engineering-v1",
        calibration_note="Synthetic configuration wiring test only",
        planning_horizon=1, discount_factor=.8,
        rewards={"correct_answer_reward": 6, "incorrect_answer_penalty": 9,
                 "abstain_reward": -1})
    packs.save("tenant-a", pack)
    packs.approve("tenant-a", pack.domain_id, pack.model_version, "test-reviewer")
    scenario = packs.build_scenario("tenant-a", pack.domain_id, "Check PO-2001")
    planner = build_scenario_planner(scenario, horizon=2)
    assert planner.config.horizon == 1
    assert planner.config.gamma == .8
    assert planner.config.correct_answer_reward == 6
    assert planner.config.incorrect_answer_penalty == 9
    assert planner.config.abstain_reward == -1
    assert planner.config.answer_threshold == .8


def test_lifecycle_is_tenant_scoped_versioned_and_immutable(tmp_path):
    repository, packs, _, active = approved_runtime(tmp_path)
    assert active.status == DomainPackStatus.ACTIVE
    assert packs.get("tenant-b", active.domain_id) is None
    changed = active.model_copy(update={
        "factual_policy": active.factual_policy.model_copy(update={"total_tolerance": "999"})})
    with pytest.raises(ValueError, match="cannot be rewritten"):
        packs.save("tenant-a", changed)
    with pytest.raises(ValueError, match="tenant owner"):
        packs.save("tenant-b", procurement_demo_pack("tenant-a", version="v2"))
    revalidation = packs.require_revalidation(
        "tenant-a", active.domain_id, active.model_version, "source withdrawn")
    assert revalidation.status == DomainPackStatus.REVALIDATION_REQUIRED
    with pytest.raises(ValueError, match="not active"):
        DomainInvestigationService(packs, [ProcurementAdapter(repository)]).investigate(
            "tenant-a", active.domain_id, "Does INV-1001 match PO-2001?")


@pytest.mark.parametrize(("quantity", "expected"), [
    ("2", "MATCH_SUPPORTED"), ("3", "MISMATCH_SUPPORTED"),
])
def test_procurement_exact_matching_and_mismatch(tmp_path, quantity, expected):
    repository, _, runtime, active = approved_runtime(tmp_path)
    seed_synthetic_procurement(repository, "tenant-a", quantity=quantity)
    result = runtime.investigate("tenant-a", active.domain_id,
        "Does invoice INV-1001 match purchase order PO-2001?", version=active.model_version)
    assert result.classification == expected
    assert result.decision == "ANSWER"
    assert result.provenance_verified
    assert result.domain_version == active.model_version
    if expected == "MISMATCH_SUPPORTED":
        quantity_finding = next(item for item in result.findings if item["field"].endswith(":quantity"))
        assert quantity_finding["invoice"] == "3"
        assert quantity_finding["purchase_order"] == "2"
        assert "fraud" in result.limitation


def test_procurement_missing_and_withdrawn_evidence_abstains(tmp_path):
    repository, _, runtime, active = approved_runtime(tmp_path)
    seed_synthetic_procurement(repository, "tenant-a", include_po=False)
    result = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert (result.decision, result.classification) == ("ABSTAIN", "INSUFFICIENT_EVIDENCE")
    repository.deactivate_document("doc-INV-1001-base", "tenant-a")
    result = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert result.classification == "INSUFFICIENT_EVIDENCE"


def test_procurement_purchase_order_requires_its_own_active_source(tmp_path):
    repository, _, runtime, active = approved_runtime(tmp_path)
    seed_synthetic_procurement(repository, "tenant-a")
    supported = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert supported.classification == "MATCH_SUPPORTED"
    assert "fact-PO-2001" in supported.fact_ids
    assert "doc-PO-2001" in supported.document_ids
    repository.deactivate_document("doc-PO-2001", "tenant-a")
    withdrawn = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert (withdrawn.decision, withdrawn.classification) == (
        "ABSTAIN", "INSUFFICIENT_EVIDENCE")


def test_procurement_exact_price_mismatch(tmp_path):
    repository, _, runtime, active = approved_runtime(tmp_path)
    seed_synthetic_procurement(repository, "tenant-a", unit_price="11.00")
    result = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert result.classification == "MISMATCH_SUPPORTED"
    finding = next(item for item in result.findings if item["field"] == "line:1:unit_price")
    assert (finding["invoice"], finding["purchase_order"], finding["difference"]) == (
        "11.00", "10.00", "1.00")


def test_incomplete_procurement_evidence_cannot_imply_a_zero_tax_match(tmp_path):
    repository, _, runtime, active = approved_runtime(tmp_path)
    seed_synthetic_procurement(repository, "tenant-a")
    fact = repository.get_relation_fact("fact-INV-1001-v1-base", "tenant-a")
    attributes = dict(fact.attributes)
    attributes.pop("tax")
    repository.upsert_relation_fact(fact.model_copy(update={"attributes": attributes}))
    result = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert (result.decision, result.classification) == ("ABSTAIN", "INSUFFICIENT_EVIDENCE")


def test_procurement_requested_po_must_match_invoice_reference(tmp_path):
    repository, _, runtime, active = approved_runtime(tmp_path)
    seed_synthetic_procurement(repository, "tenant-a")
    result = runtime.investigate("tenant-a", active.domain_id,
        "Does invoice INV-1001 match purchase order PO-9999?")
    assert result.classification == "MISMATCH_SUPPORTED"
    assert result.findings[0] == {"field": "purchase_order_reference",
        "requested": "PO-9999", "invoice": "PO-2001", "status": "MISMATCH"}


def test_three_way_match_and_conflicting_versions_fail_closed(tmp_path):
    repository, _, runtime, active = approved_runtime(tmp_path, require_receipt=True)
    seed_synthetic_procurement(repository, "tenant-a", include_receipt=False)
    missing = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert missing.classification == "INSUFFICIENT_EVIDENCE"
    seed_synthetic_procurement(repository, "tenant-a", include_receipt=True)
    complete = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert complete.classification == "MATCH_SUPPORTED"
    assert "doc-GR-PO-2001" in complete.document_ids
    seed_synthetic_procurement(repository, "tenant-a", source_suffix="conflict",
                               version=2, quantity="7", include_receipt=True)
    conflict = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert (conflict.decision, conflict.classification) == ("ABSTAIN", "CONFLICTING_EVIDENCE")


def test_cross_tenant_and_cross_domain_tool_access_are_denied(tmp_path):
    repository, packs, runtime, active = approved_runtime(tmp_path)
    seed_synthetic_procurement(repository, "tenant-a")
    with pytest.raises(KeyError, match="tenant scope"):
        runtime.investigate("tenant-b", active.domain_id, "Check INV-1001")
    restricted = active.model_copy(update={"model_version": "restricted-v2",
        "status": DomainPackStatus.DRAFT, "approved_by": None,
        "registered_tools": ["fetch_invoice"]})
    packs.save("tenant-a", restricted)
    packs.submit_for_review("tenant-a", restricted.domain_id, restricted.model_version)
    packs.approve("tenant-a", restricted.domain_id, restricted.model_version, "reviewer-1")
    with pytest.raises(ValueError, match="unavailable or unregistered tool"):
        runtime.investigate("tenant-a", restricted.domain_id, "Check INV-1001",
                            version=restricted.model_version)
    unsafe = active.model_copy(update={"domain_id": "unsafe-domain", "model_version": "v1",
        "status": DomainPackStatus.DRAFT, "approved_by": None,
        "registered_tools": ["fetch_order"]})
    packs.save("tenant-a", unsafe)
    packs.submit_for_review("tenant-a", unsafe.domain_id, unsafe.model_version)
    packs.approve("tenant-a", unsafe.domain_id, unsafe.model_version, "reviewer-1")
    packs.activate("tenant-a", unsafe.domain_id, unsafe.model_version)
    with pytest.raises(ValueError, match="no registered factual adapter"):
        runtime.investigate("tenant-a", unsafe.domain_id, "Check INV-1001")


def test_duplicate_seed_is_idempotent_and_source_group_not_double_counted(tmp_path):
    repository, _, runtime, active = approved_runtime(tmp_path)
    seed_synthetic_procurement(repository, "tenant-a")
    seed_synthetic_procurement(repository, "tenant-a")
    result = runtime.investigate("tenant-a", active.domain_id, "Check INV-1001")
    assert result.classification == "MATCH_SUPPORTED"
    assert len(result.fact_ids) == 2
    assert len(result.evidence_ids) == 2
    assert len(result.source_groups) == 2


def test_domain_management_api_lifecycle_and_investigation(tmp_path):
    key = secrets.token_urlsafe(36)
    permissions = frozenset({Permission.DOMAIN_PACK_MANAGE, Permission.MODEL_APPROVE,
        Permission.DOCUMENT_READ, Permission.INVESTIGATION_EXECUTE})
    settings = AppSettings(api_key=key, principal_id="domain-reviewer",
        tenant_id="tenant-api", roles=frozenset({"reviewer"}), permissions=permissions,
        document_store_path=str(tmp_path / "documents"),
        operations_database_path=str(tmp_path / "operations.db"))
    app = create_app(settings)
    auth = {"Authorization": f"Bearer {key}"}
    draft = procurement_demo_pack("tenant-api")
    with TestClient(app) as client:
        validated = client.post("/api/v1/domains/validate", headers=auth,
                                json=draft.model_dump(mode="json"))
        assert validated.status_code == 200
        assert validated.json()["valid"] is True
        created = client.post("/api/v1/domains", headers=auth,
                              json=draft.model_dump(mode="json"))
        assert created.status_code == 200
        for action in ("SUBMIT", "APPROVE", "ACTIVATE"):
            response = client.post(
                f"/api/v1/domains/{draft.domain_id}/{draft.model_version}/lifecycle",
                headers=auth, json={"action": action})
            assert response.status_code == 200, response.text
        seed_synthetic_procurement(app.state.dependencies.graph_repository, "tenant-api")
        result = client.post(f"/api/v1/domains/{draft.domain_id}/investigate",
            headers=auth, json={"question": "Does INV-1001 match PO-2001?",
                                "version": draft.model_version})
        assert result.status_code == 200, result.text
        assert result.json()["classification"] == "MATCH_SUPPORTED"
        assert client.get("/api/v1/domains", headers=auth).json()[0]["tenant_owner"] == "tenant-api"


def test_domain_validation_uses_existing_durable_worker(tmp_path):
    operations = SQLiteOperationRepository(tmp_path / "ops.db")
    packs = DomainPackService(LocalDocumentStore(tmp_path / "packs"), InMemoryGraphRepository())
    draft = procurement_demo_pack("tenant-a")
    job = operations.create_job(NewOperationJob(
        tenant_id="tenant-a", principal_id="author-a",
        operation_type=OperationType.DOMAIN_VALIDATION, correlation_id="corr-domain",
        payload={"domain_pack": draft.model_dump(mode="json")},
        idempotency_key="validate-procurement-v1", replay_safe=True))[0]
    worker = DurableWorker(operations, {
        OperationType.DOMAIN_VALIDATION: domain_validation_handler(packs)})
    assert worker.run_once()
    restored = operations.get_job("tenant-a", job.job_id)
    assert restored.state is JobState.COMPLETED
    assert restored.result["domain_id"] == draft.domain_id
    assert restored.result["status"] == "VALIDATED"


def test_logistics_and_procurement_switch_through_same_runtime(tmp_path):
    class FakeOlist:
        def lookup(self, tenant_id, order_id):
            assert tenant_id == "tenant-a"
            return {"order_id": order_id, "outcome": "shipment_delayed", "status": "delivered",
                "estimated_delivery_date": "2017-01-10", "actual_delivery_date": "2017-01-12",
                "fact_id": "olist-fact-1", "sources": [{"document_id": "olist-doc-1",
                    "source_group": "olist-release:olist-2018"}]}

        def prospective_snapshot(self, tenant_id, order_id, mode):
            return {"mode": "PROSPECTIVE_POMDP", "status": "INSUFFICIENT_MODEL",
                    "decision": "ABSTAIN", "outcome_hidden": True, "probability_late": None}

    repository = InMemoryGraphRepository()
    packs = DomainPackService(LocalDocumentStore(tmp_path), repository)
    for draft in (procurement_demo_pack("tenant-a"), olist_logistics_pack("tenant-a")):
        packs.save("tenant-a", packs.validate("tenant-a", draft))
        packs.submit_for_review("tenant-a", draft.domain_id, draft.model_version)
        packs.approve("tenant-a", draft.domain_id, draft.model_version, "reviewer-1")
        packs.activate("tenant-a", draft.domain_id, draft.model_version)
    seed_synthetic_procurement(repository, "tenant-a")
    runtime = DomainInvestigationService(packs, [
        ProcurementAdapter(repository), OlistLogisticsAdapter(FakeOlist())])
    procurement = runtime.investigate("tenant-a", "procurement_document_match", "Check INV-1001")
    synthetic_order_id = "a" * 32  # Fake adapter fixture, not an original Olist row.
    logistics = runtime.investigate("tenant-a", "olist_logistics",
        f"Was {synthetic_order_id} delivered late?")
    prospective = runtime.investigate("tenant-a", "olist_logistics",
        f"At purchase time, predict risk for {synthetic_order_id}")
    assert procurement.classification == "MATCH_SUPPORTED"
    assert logistics.classification == "MISMATCH_SUPPORTED"
    assert prospective["status"] == "INSUFFICIENT_MODEL"
    assert prospective["decision"] == "ABSTAIN"
    assert prospective["outcome_hidden"] is True


def test_concurrent_read_only_procurement_investigations_are_stable(tmp_path):
    repository, _, runtime, active = approved_runtime(tmp_path)
    seed_synthetic_procurement(repository, "tenant-a")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: runtime.investigate(
            "tenant-a", active.domain_id, "Check INV-1001", version=active.model_version),
            range(12)))
    assert {item.classification for item in results} == {"MATCH_SUPPORTED"}
    assert {tuple(item.evidence_ids) for item in results} == {(
        "evidence-INV-1001-v1-base", "evidence-PO-2001")}


def test_durable_domain_investigation_resumes_pinned_version_without_writes(tmp_path):
    import hashlib
    import json

    graph, _, runtime, active = approved_runtime(tmp_path / "domain")
    seed_synthetic_procurement(graph, "tenant-a")
    operations = SQLiteOperationRepository(tmp_path / "ops.db")
    payload = {"domain_id": active.domain_id, "model_version": active.model_version,
               "subject_id": "INV-1001", "question_type": "match"}
    job = operations.create_job(NewOperationJob(
        tenant_id="tenant-a", principal_id="analyst-a",
        operation_type=OperationType.DOMAIN_INVESTIGATION, correlation_id="corr-resume",
        payload=payload, idempotency_key="domain-resume", replay_safe=True))[0]
    claim = operations.claim("worker-before-crash", lease_seconds=30)
    assert claim and claim.job.job_id == job.job_id
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    operations.journal_put(claim, "domain-investigation", "STARTED",
                           hashlib.sha256(encoded.encode()).hexdigest())
    before = (len(graph.entities), len(graph.facts), len(graph.evidence))
    result = domain_investigation_handler(runtime)(OperationContext(operations, claim, 30), payload)
    operations.complete(claim, result)
    restored = operations.get_job("tenant-a", job.job_id)
    assert restored.state is JobState.COMPLETED
    assert restored.result["domain_version"] == active.model_version
    assert restored.result["classification"] == "MATCH_SUPPORTED"
    assert before == (len(graph.entities), len(graph.facts), len(graph.evidence))
