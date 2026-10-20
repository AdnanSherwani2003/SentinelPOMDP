"""Clearly labeled representative data for framework verification only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .dataset import (
    ClaimType, DataClassification, LabelStatus, PilotCase, PilotDataset,
    PilotObservation, SelectionMechanism,
)


def representative_shipment_fixture(case_count: int = 60) -> PilotDataset:
    if case_count < 15:
        raise ValueError("representative fixture requires at least 15 cases")
    cases = []
    observations = []
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    for index in range(case_count):
        delayed = index % 2 == 0
        label = "delayed" if delayed else "on_time"
        case_id = f"synthetic-{index:04d}"
        cases.append(PilotCase(
            case_id=case_id, tenant_id="synthetic-pilot", domain_id="shipment-timeliness",
            dataset_version="synthetic-v1", event_time=start + timedelta(days=index),
            entity_id=f"PO-SYN-{index:04d}", leakage_group_id=f"shipment-{index:04d}",
            source_family_ids=[f"operational-system-{index % 4}"],
            subgroup={"supplier_category": "A" if index % 3 else "B", "format": "csv"},
            claim_type=ClaimType.DELIVERY_TIMELINESS, ground_truth_label=label,
            ground_truth_source_ids=[f"independent-outcome-{index:04d}"],
            independent_ground_truth=True, label_status=LabelStatus.APPROVED,
            label_method="synthetic fixture rule; not organizational evidence"))
        # Fixed deterministic error pattern: 80% sensitivity and 83.3% specificity.
        supports_delay = (delayed and index % 10 != 0) or (not delayed and index % 12 == 1)
        token = "EVIDENCE_SUPPORTED" if supports_delay else "EVIDENCE_CONTRADICTED"
        observations.append(PilotObservation(
            case_id=case_id, action_id="inspect_delivery", observation_token=token,
            observed=True, source_document_id=f"evidence-{index:04d}",
            source_group_id=f"warehouse-{index:04d}",
            upstream_source_id=f"warehouse-system-{index % 4}",
            observation_time=start + timedelta(days=index, hours=1),
            available_at_decision_time=True, selection_mechanism=SelectionMechanism.ROUTINE))
    return PilotDataset(
        dataset_id="representative-shipment-pilot", version="synthetic-v1",
        tenant_id="synthetic-pilot", domain_id="shipment-timeliness",
        classification=DataClassification.SYNTHETIC_REPRESENTATIVE, authorized_use=True,
        usage_basis="Generated fixture authorized only for software verification; not real company data.",
        created_at=start, cases=cases, observations=observations,
        allowed_labels=["delayed", "on_time"],
        allowed_observations=["EVIDENCE_SUPPORTED", "EVIDENCE_CONTRADICTED"],
        retention_note="Ephemeral synthetic fixture; contains no organizational records.")
