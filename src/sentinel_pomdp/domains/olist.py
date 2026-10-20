"""Adapter exposing the existing Olist service through the shared domain runtime."""
from __future__ import annotations

from datetime import datetime, timezone

from sentinel_pomdp.olist import OlistService, Snapshot

from .execution import FactualInvestigationResult, extract_identifier
from .models import (
    DataMapping, DomainPack, DomainPackStatus, EvidenceRequirement, FactualPolicy,
    GovernanceMetadata, InvestigationMode, ParameterSource,
)


def olist_logistics_pack(tenant_id: str, *, version: str = "olist-historical-v1",
                         status: DomainPackStatus = DomainPackStatus.DRAFT,
                         approved_by: str | None = None) -> DomainPack:
    return DomainPack(
        domain_id="olist_logistics", name="Olist Logistics",
        description="Historical delivery lookup and leakage-safe prospective model gate.",
        tenant_owner=tenant_id, claim_type="delivery_timeliness",
        supported_question_types=["historical_delivery_outcome", "prospective_delivery_risk"],
        investigation_mode=InvestigationMode.FACTUAL,
        entity_types=["olist_order", "olist_order_item", "olist_seller"],
        relationship_types=["OLIST_DELIVERY_OUTCOME", "ORDER_CONTAINS_ITEM"],
        required_evidence=[EvidenceRequirement(evidence_type="olist_order_row")],
        registered_tools=sorted(OlistLogisticsAdapter.registered_tools),
        mappings=[DataMapping(source_field="order.order_id", entity_type="olist_order",
            relationship_type="OLIST_DELIVERY_OUTCOME", data_type="string",
            validation_rule="identifier", source_row_field="source_row",
            available_at_field="order_delivered_customer_date",
            source_group="olist-release:olist-2018")],
        factual_policy=FactualPolicy(outcomes=["MATCH_SUPPORTED", "MISMATCH_SUPPORTED",
            "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"]),
        status=status, model_version=version, approved_by=approved_by,
        parameter_source=ParameterSource.NOT_APPLICABLE,
        calibration_note="Historical lookup only; prospective risk requires a separately approved model.",
        governance=GovernanceMetadata(author="sentinel-olist-integration",
            reviewer=approved_by, dataset_provenance=["Olist public research archive"],
            source_dependencies=["olist_orders_dataset.csv"],
            validation_findings=["Historical outcomes are facts, not forecasts."],
            created_at=datetime.now(timezone.utc),
            approved_at=datetime.now(timezone.utc) if approved_by else None),
        evaluation_status="HISTORICAL_FACTUAL_ONLY")


class OlistLogisticsAdapter:
    domain_id = "olist_logistics"
    registered_tools = frozenset({
        "fetch_order", "fetch_delivery_events", "fetch_source_provenance",
    })

    def __init__(self, service: OlistService) -> None:
        self.service = service

    def investigate(self, tenant_id: str, pack: DomainPack, question: str):
        order_id = extract_identifier(question, r"\b[a-fA-F0-9]{32}\b", "an Olist order")
        lower = question.lower()
        if any(term in lower for term in ("risk", "purchase time", "prospective", "predict")):
            result = self.service.prospective_snapshot(tenant_id, order_id.lower(), Snapshot.PURCHASE)
            return {**result, "domain_id": pack.domain_id, "domain_version": pack.model_version}
        result = self.service.lookup(tenant_id, order_id.lower())
        sources = result.get("sources", [])
        actual = result.get("actual_delivery_date")
        outcome = result.get("outcome")
        if actual is None or outcome not in {"LATE", "ON_TIME", "shipment_delayed", "shipment_on_time"}:
            decision, classification = "ABSTAIN", "INSUFFICIENT_EVIDENCE"
        else:
            decision, classification = "ANSWER", (
                "MISMATCH_SUPPORTED" if outcome in {"LATE", "shipment_delayed"}
                else "MATCH_SUPPORTED")
        return FactualInvestigationResult(
            domain_id=pack.domain_id, domain_version=pack.model_version,
            decision=decision, classification=classification, subject_id=order_id.lower(),
            findings=[{"field": "delivery_outcome", "value": outcome,
                       "estimated_delivery_date": result.get("estimated_delivery_date"),
                       "actual_delivery_date": actual}], fact_ids=[result["fact_id"]],
            document_ids=sorted({item["document_id"] for item in sources}),
            source_groups=sorted({item["source_group"] for item in sources}),
            sources=sources,
            provenance_verified=bool(sources),
            limitation="Historical date comparison is a factual lookup, not a Bayesian forecast.")
