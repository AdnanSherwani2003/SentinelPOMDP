from __future__ import annotations

from datetime import datetime, timezone
from math import log
import secrets

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from sentinel_pomdp.calibration import (
    ExtractionExample, PilotPrediction, SourcePair, build_candidate_domain_pack,
    estimate_categorical_model, evaluate_extraction, evaluate_predictions,
    evaluate_source_independence,
)
from sentinel_pomdp.domains import DomainPackService, DomainPackStatus
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.ingestion import LocalDocumentStore
from sentinel_pomdp.pilot import (
    LabelReview, LabelStatus, PilotSplit, add_label_review, adjudicate_label,
    chronological_group_split, validate_dataset, validate_manifest,
)
from sentinel_pomdp.pilot.fixtures import representative_shipment_fixture
from sentinel_pomdp.pilot.replay import ReplayPolicy, replay_logged_policy
from sentinel_pomdp.calibration.reward_sensitivity import (
    RewardAssumptions, paired_utility_difference,
)
from sentinel_pomdp.api.app import build_dependencies, create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.security import Permission


def test_dataset_contract_hides_ground_truth_from_evaluation_view():
    dataset = representative_shipment_fixture(15)
    report = validate_dataset(dataset)
    assert report.valid and report.definitive_labels == 15
    view = dataset.cases[0].evaluation_view()
    assert "ground_truth_label" not in view
    assert "ground_truth_source_ids" not in view
    first = dataset.cases[0]
    leaked_case = first.model_copy(update={
        "ground_truth_source_ids": [dataset.observations[0].source_document_id]})
    leaked = dataset.model_copy(update={"cases": [leaked_case, *dataset.cases[1:]]})
    assert not validate_dataset(leaked).valid
    assert validate_dataset(leaked).errors[0].startswith("GROUND_TRUTH_EVIDENCE_LEAKAGE")


def test_label_disagreement_and_independent_adjudication():
    case = representative_shipment_fixture(15).cases[0].model_copy(update={
        "ground_truth_label": None, "ground_truth_source_ids": [],
        "independent_ground_truth": False, "label_status": LabelStatus.UNLABELED})
    first = add_label_review(case, LabelReview(
        reviewer_ref="reviewer-a", label="delayed", reviewed_at=datetime.now(timezone.utc),
        method="independent operations review", source_ids=["outcome-a"]))
    disputed = add_label_review(first, LabelReview(
        reviewer_ref="reviewer-b", label="on_time", reviewed_at=datetime.now(timezone.utc),
        method="independent finance review", source_ids=["outcome-b"]))
    assert disputed.label_status == LabelStatus.DISPUTED
    resolved = adjudicate_label(
        disputed, label="delayed", adjudicator_ref="adjudicator-c",
        source_ids=["authoritative-receipt"], method="cross-system adjudication")
    assert resolved.label_status == LabelStatus.ADJUDICATED
    assert resolved.independent_ground_truth
    with pytest.raises(ValueError, match="independent"):
        adjudicate_label(disputed, label="delayed", adjudicator_ref="reviewer-a",
                         source_ids=["x"], method="invalid")


def test_chronological_split_has_no_group_leakage_and_rejects_version_mismatch():
    dataset = representative_shipment_fixture(30)
    manifest = chronological_group_split(dataset)
    validate_manifest(dataset, manifest)
    times = {split: [case.event_time for case in dataset.cases
                     if manifest.assignments[case.case_id] == split] for split in PilotSplit}
    assert max(times[PilotSplit.TRAIN]) < min(times[PilotSplit.VALIDATION])
    assert max(times[PilotSplit.VALIDATION]) < min(times[PilotSplit.TEST])
    broken = manifest.model_copy(update={"dataset_version": "wrong"})
    with pytest.raises(ValueError, match="version mismatch"):
        validate_manifest(dataset, broken)


def test_prior_and_likelihood_estimation_are_normalized_and_training_only():
    dataset = representative_shipment_fixture(60)
    manifest = chronological_group_split(dataset)
    estimate = estimate_categorical_model(dataset, manifest)
    assert estimate.usable_cases == 36
    assert estimate.class_counts == {"delayed": 18, "on_time": 18}
    assert estimate.prior == pytest.approx({"delayed": .5, "on_time": .5})
    assert sum(estimate.prior.values()) == pytest.approx(1)
    for rows in estimate.observation_model.values():
        for row in rows.values():
            assert sum(row.values()) == pytest.approx(1)
            assert all(0 < probability < 1 for probability in row.values())
    assert estimate.status == "EMPIRICALLY_ESTIMATED"
    assert estimate.prior_intervals["delayed"].low < .5 < estimate.prior_intervals["delayed"].high


def test_sparse_estimate_cannot_become_model_candidate():
    dataset = representative_shipment_fixture(15)
    manifest = chronological_group_split(dataset)
    estimate = estimate_categorical_model(dataset, manifest, minimum_state_samples=100)
    assert estimate.status == "INSUFFICIENT_DATA"
    with pytest.raises(ValueError, match="insufficient"):
        build_candidate_domain_pack(
            estimate=estimate, domain_id="delivery", name="Delivery", claim_type="timeliness",
            model_version="v1", relation_hypotheses={"EXPERIENCED_DELAY": "delayed"},
            action_costs={"inspect_delivery": .1}, answer_threshold=.7,
            minimum_independent_sources=1)


def test_calibration_metrics_match_hand_calculation():
    predictions = [
        PilotPrediction(case_id="a", probabilities={"delayed": .8, "on_time": .2},
                        decision="ANSWER", predicted_label="delayed", evidence_sufficient=True),
        PilotPrediction(case_id="b", probabilities={"delayed": .6, "on_time": .4},
                        decision="ABSTAIN", evidence_sufficient=False),
    ]
    metrics = evaluate_predictions(predictions, {"a": "delayed", "b": "on_time"}, num_bins=5)
    assert metrics.coverage == .5
    assert metrics.selective_accuracy == 1
    assert metrics.multiclass_brier_score == pytest.approx(.4)
    assert metrics.log_loss == pytest.approx(-(log(.8) + log(.4)) / 2)
    assert metrics.unsupported_answer_rate == 0


def test_policy_utility_comparison_is_paired_and_reproducible():
    labels = {"a": "delayed", "b": "on_time"}
    abstain = [PilotPrediction(
        case_id=case_id, probabilities={"delayed": .5, "on_time": .5},
        decision="ABSTAIN", evidence_sufficient=False) for case_id in labels]
    investigate = [
        PilotPrediction(case_id="a", probabilities={"delayed": .9, "on_time": .1},
                        decision="ANSWER", predicted_label="delayed", evidence_sufficient=True,
                        actions_taken=["inspect"], investigation_cost=.1),
        PilotPrediction(case_id="b", probabilities={"delayed": .9, "on_time": .1},
                        decision="ANSWER", predicted_label="delayed", evidence_sufficient=True,
                        actions_taken=["inspect"], investigation_cost=.1),
    ]
    assumptions = RewardAssumptions(
        correct_answer_reward=1, incorrect_answer_penalty=5, abstention_cost=.25)
    first = paired_utility_difference(
        investigate, abstain, labels, assumptions=assumptions, seed=4, bootstrap_samples=100)
    second = paired_utility_difference(
        investigate, abstain, labels, assumptions=assumptions, seed=4, bootstrap_samples=100)
    assert first == second
    assert first["paired_cases"] == 2


def test_extraction_and_source_independence_metrics_are_explicit():
    quality = evaluate_extraction([ExtractionExample(
        example_id="one", expected_facts={"a", "b"}, extracted_facts={"a", "c"},
        supported_extracted_facts={"a"}, correct_source_locations={"row:2"},
        expected_source_locations={"row:2", "row:3"}, document_type="csv")])
    assert quality.precision == .5 and quality.recall == .5 and quality.f1 == .5
    assert quality.unsupported_fact_rate == .5
    assert quality.source_location_accuracy == .5
    independence = evaluate_source_independence([
        SourcePair(left_id="a", right_id="b", genuinely_independent=False,
                   predicted_independent=True, relationship="copied export"),
        SourcePair(left_id="a", right_id="c", genuinely_independent=True,
                   predicted_independent=True, relationship="separate operational system"),
    ])
    assert independence.accuracy == .5
    assert independence.false_independence_rate == 1


def test_logged_replay_does_not_invent_missing_counterfactuals():
    dataset = representative_shipment_fixture(30)
    manifest = chronological_group_split(dataset)
    estimate = estimate_categorical_model(dataset, manifest, minimum_state_samples=2)
    target = next(case for case in dataset.cases
                  if manifest.assignments[case.case_id] == PilotSplit.TEST)
    observations = [item.model_copy(update={"observed": False, "observation_token": None,
                                            "observation_time": None, "missing_reason": "not logged"})
                    if item.case_id == target.case_id else item for item in dataset.observations]
    modified = dataset.model_copy(update={"observations": observations})
    predictions = replay_logged_policy(
        modified, manifest, estimate, ReplayPolicy("logged", True, .6))
    prediction = next(item for item in predictions if item.case_id == target.case_id)
    assert prediction.actions_taken == []
    assert prediction.decision == "ABSTAIN"


def test_timeliness_observation_cannot_answer_causal_claim():
    dataset = representative_shipment_fixture(30)
    manifest = chronological_group_split(dataset)
    estimate = estimate_categorical_model(dataset, manifest, minimum_state_samples=2)
    target = next(case for case in dataset.cases
                  if manifest.assignments[case.case_id] == PilotSplit.TEST)
    from sentinel_pomdp.pilot import ClaimType
    modified = dataset.model_copy(update={
        "cases": [case.model_copy(update={"claim_type": ClaimType.CAUSAL_ATTRIBUTION})
                  if case.case_id == target.case_id else case for case in dataset.cases]})
    result = replay_logged_policy(
        modified, manifest, estimate, ReplayPolicy("logged", True, .5))
    prediction = next(item for item in result if item.case_id == target.case_id)
    assert prediction.decision == "ABSTAIN"
    assert not prediction.evidence_sufficient


def test_empirical_domain_pack_requires_human_approval_and_is_versioned(tmp_path):
    dataset = representative_shipment_fixture(60)
    manifest = chronological_group_split(dataset)
    estimate = estimate_categorical_model(dataset, manifest)
    labels = {case.case_id: case.ground_truth_label for case in dataset.cases
              if manifest.assignments[case.case_id] == PilotSplit.TEST}
    predictions = replay_logged_policy(
        dataset, manifest, estimate, ReplayPolicy("logged", True, .6))
    metrics = evaluate_predictions(predictions, labels)
    candidate = build_candidate_domain_pack(
        estimate=estimate, domain_id="delivery", name="Delivery", claim_type="timeliness",
        model_version="cal-v1", relation_hypotheses={"EXPERIENCED_DELAY": "delayed"},
        action_costs={"inspect_delivery": .1}, answer_threshold=.6,
        minimum_independent_sources=1, holdout_metrics=metrics)
    assert candidate.status == DomainPackStatus.PROVISIONAL
    service = DomainPackService(LocalDocumentStore(tmp_path), InMemoryGraphRepository())
    service.save("tenant-a", candidate)
    approved = service.approve("tenant-a", "delivery", "cal-v1", "reviewer-1")
    assert approved.status == DomainPackStatus.APPROVED
    assert approved.approved_by == "reviewer-1"
    assert service.rollback("tenant-a", "delivery", "cal-v1").model_version == "cal-v1"
    second_candidate = candidate.model_copy(update={"model_version": "cal-v2"})
    service.save("tenant-a", second_candidate)
    assert service.get("tenant-a", "delivery").model_version == "cal-v1"
    assert {item.model_version for item in service.versions("tenant-a", "delivery")} == {
        "cal-v1", "cal-v2"}
    changed = approved.model_copy(update={"prior": {"delayed": .9, "on_time": .1}})
    with pytest.raises(ValueError, match="cannot be rewritten"):
        service.save("tenant-a", changed)
    invalidated = service.invalidate_for_dataset(
        "tenant-a", dataset.dataset_id, "calibration source withdrawn")
    assert all(item.status == DomainPackStatus.RETIRED for item in invalidated)
    assert all("REVALIDATION_REQUIRED" in item.calibration.limitations[-1]
               for item in invalidated)


def test_calibration_api_is_tenant_scoped_and_requires_separate_approval(tmp_path):
    key = secrets.token_urlsafe(36)
    permissions = frozenset({
        Permission.CALIBRATION_RUN, Permission.EVALUATION_READ,
        Permission.MODEL_APPROVE, Permission.DOMAIN_PACK_MANAGE})
    settings = AppSettings(
        api_key=key, roles=frozenset({"reviewer"}), permissions=permissions,
        document_store_path=str(tmp_path / "calibration-api"))
    dataset = representative_shipment_fixture(60)
    cases = [case.model_copy(update={"tenant_id": settings.tenant_id}) for case in dataset.cases]
    dataset = dataset.model_copy(update={"tenant_id": settings.tenant_id, "cases": cases})
    payload = {
        "dataset": dataset.model_dump(mode="json"), "model_version": "empirical-v1",
        "name": "Shipment calibration", "claim_type": "shipment_timeliness",
        "relation_hypotheses": {"EXPERIENCED_DELAY": "delayed"},
        "action_costs": {"inspect_delivery": .08}, "answer_threshold": .8,
        "minimum_independent_sources": 1,
    }
    headers = {"Authorization": f"Bearer {key}"}
    with TestClient(create_app(settings, build_dependencies(settings))) as client:
        response = client.post("/api/v1/pilot/calibrations", headers=headers, json=payload)
        assert response.status_code == 200
        assert response.json()["activated"] is False
        assert response.json()["candidate"]["status"] == "PROVISIONAL"
        status = client.get("/api/v1/pilot/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["real_world_validation_status"] == "PENDING"
        approval = client.post(
            "/api/v1/pilot/models/shipment-timeliness/empirical-v1/review",
            headers=headers, json={"action": "APPROVE"})
        assert approval.status_code == 200
        assert approval.json()["status"] == "APPROVED"

        wrong_tenant = dataset.model_copy(update={
            "tenant_id": "another-tenant",
            "cases": [case.model_copy(update={"tenant_id": "another-tenant"})
                      for case in dataset.cases]})
        payload["dataset"] = wrong_tenant.model_dump(mode="json")
        denied = client.post("/api/v1/pilot/calibrations", headers=headers, json=payload)
        assert denied.status_code == 403
