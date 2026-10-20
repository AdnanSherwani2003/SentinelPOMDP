"""Synthetic procurement domain adapter using exact decimal reconciliation."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP
from datetime import datetime, timezone
from hashlib import sha256
import re

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.graph.schemas import Document, Entity, Evidence, EvidenceType, RelationFact

from .execution import FactualInvestigationResult, extract_identifier
from .models import (
    DataMapping, DomainPack, DomainPackStatus, EvidenceRequirement, FactualPolicy,
    GovernanceMetadata, InvestigationMode, ParameterSource,
)

_ROUNDING = {
    "ROUND_HALF_UP": ROUND_HALF_UP, "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_DOWN": ROUND_DOWN, "ROUND_UP": ROUND_UP,
}


def procurement_demo_pack(tenant_id: str, *, version: str = "synthetic-v1",
                          status: DomainPackStatus = DomainPackStatus.DRAFT,
                          approved_by: str | None = None,
                          require_goods_receipt: bool = False) -> DomainPack:
    return DomainPack(
        domain_id="procurement_document_match", name="Procurement Document Matching",
        description="Deterministic reconciliation of approved synthetic invoice and purchase-order evidence.",
        tenant_owner=tenant_id, claim_type="procurement_document_match",
        supported_question_types=["invoice_purchase_order_match"],
        investigation_mode=InvestigationMode.FACTUAL,
        entity_types=["invoice", "purchase_order", "goods_receipt"],
        relationship_types=["PROCUREMENT_INVOICE_SNAPSHOT", "PROCUREMENT_PURCHASE_ORDER_SNAPSHOT",
                            "GOODS_RECEIPT_FOR_PO"],
        required_evidence=[EvidenceRequirement(evidence_type="invoice"),
                           EvidenceRequirement(evidence_type="purchase_order")],
        optional_evidence=[EvidenceRequirement(evidence_type="goods_receipt", required=False)],
        registered_tools=sorted(ProcurementAdapter.registered_tools),
        mappings=[
            DataMapping(source_field="invoice.purchase_order_id", entity_type="invoice",
                relationship_type="PROCUREMENT_INVOICE_SNAPSHOT", data_type="string",
                validation_rule="identifier", source_row_field="invoice.row",
                source_group="synthetic-procurement-demo"),
            DataMapping(source_field="invoice.unit_price", entity_type="invoice",
                data_type="decimal", validation_rule="money", source_row_field="invoice.row",
                source_group="synthetic-procurement-demo"),
        ],
        factual_policy=FactualPolicy(
            outcomes=["MATCH_SUPPORTED", "MISMATCH_SUPPORTED", "INSUFFICIENT_EVIDENCE",
                      "CONFLICTING_EVIDENCE"], require_goods_receipt=require_goods_receipt),
        status=status, model_version=version,
        calibration_note="Deterministic synthetic engineering demonstration; no probability model.",
        approved_by=approved_by, parameter_source=ParameterSource.NOT_APPLICABLE,
        governance=GovernanceMetadata(author="sentinel-demo", reviewer=approved_by,
            dataset_provenance=["synthetic://procurement-demo"],
            source_dependencies=["invoice", "purchase_order"],
            validation_findings=["Synthetic data only; business accuracy is not established."],
            created_at=datetime.now(timezone.utc),
            approved_at=datetime.now(timezone.utc) if approved_by else None),
        evaluation_status="SYNTHETIC_ENGINEERING_ONLY")


class ProcurementAdapter:
    domain_id = "procurement_document_match"
    registered_tools = frozenset({
        "fetch_invoice", "fetch_purchase_order", "fetch_invoice_lines",
        "fetch_goods_receipt", "check_source_version", "fetch_source_provenance",
    })

    def __init__(self, repository: BaseGraphRepository) -> None:
        self.repository = repository

    def investigate(self, tenant_id: str, pack: DomainPack,
                    question: str) -> FactualInvestigationResult:
        invoice_id = extract_identifier(question, r"\bINV-[A-Za-z0-9_-]+\b", "an invoice")
        facts = self.repository.find_facts(
            tenant_id, subject_id=invoice_id, relation_type="PROCUREMENT_INVOICE_SNAPSHOT")
        supported = []
        evidence_ids: set[str] = set()
        document_ids: set[str] = set()
        source_groups: set[str] = set()
        for fact in facts:
            evidence, contradictions = self.repository.get_fact_evidence(fact.fact_id, tenant_id)
            if evidence or contradictions:
                supported.append((fact, evidence, contradictions))
                for item in evidence + contradictions:
                    evidence_ids.add(item.evidence_id); document_ids.add(item.document_id)
                    source_groups.add(item.source_group or item.evidence_id)
        base = dict(domain_id=pack.domain_id, domain_version=pack.model_version,
                    subject_id=invoice_id, fact_ids=[item[0].fact_id for item in supported],
                    evidence_ids=sorted(evidence_ids), document_ids=sorted(document_ids),
                    source_groups=sorted(source_groups))
        if not supported:
            return FactualInvestigationResult(**base, decision="ABSTAIN",
                classification="INSUFFICIENT_EVIDENCE", limitation="No active approved invoice evidence is available.")
        current = [item for item in supported if item[0].attributes.get("current_version", True)]
        fingerprints = {self._semantic_fingerprint(item[0].attributes) for item in current}
        if len(current) != 1 or len(fingerprints) != 1 or any(item[2] for item in current):
            return FactualInvestigationResult(**base, decision="ABSTAIN",
                classification="CONFLICTING_EVIDENCE", provenance_verified=True,
                limitation="Multiple current or contradicting invoice versions are active.")
        invoice = current[0][0].attributes
        po_id = str(invoice.get("purchase_order_id", ""))
        requested_po = re.search(r"\bPO-[A-Za-z0-9_-]+\b", question, re.IGNORECASE)
        if requested_po and requested_po.group(0).upper() != po_id.upper():
            return FactualInvestigationResult(**base, decision="ANSWER",
                classification="MISMATCH_SUPPORTED", provenance_verified=True,
                findings=[{"field": "purchase_order_reference",
                           "requested": requested_po.group(0).upper(),
                           "invoice": po_id, "status": "MISMATCH"}],
                limitation="The invoice references a different purchase order; this is not evidence of fraud or intent.")
        po = self.repository.get_entity(po_id, tenant_id) if po_id else None
        if po is None or po.entity_type != "purchase_order":
            return FactualInvestigationResult(**base, decision="ABSTAIN",
                classification="INSUFFICIENT_EVIDENCE", provenance_verified=True,
                findings=[{"field": "purchase_order_id", "invoice": po_id, "purchase_order": None}],
                limitation="The referenced purchase order is unavailable.")
        po_records = []
        for item in self.repository.find_facts(
                tenant_id, subject_id=po_id,
                relation_type="PROCUREMENT_PURCHASE_ORDER_SNAPSHOT"):
            linked, contradictions = self.repository.get_fact_evidence(item.fact_id, tenant_id)
            if linked or contradictions:
                po_records.append((item, linked, contradictions))
                base["fact_ids"].append(item.fact_id)
                for source in linked + contradictions:
                    evidence_ids.add(source.evidence_id)
                    document_ids.add(source.document_id)
                    source_groups.add(source.source_group or source.evidence_id)
        base["evidence_ids"] = sorted(evidence_ids)
        base["document_ids"] = sorted(document_ids)
        base["source_groups"] = sorted(source_groups)
        current_po = [item for item in po_records if item[0].attributes.get("current_version", True)]
        if not current_po:
            return FactualInvestigationResult(**base, decision="ABSTAIN",
                classification="INSUFFICIENT_EVIDENCE", provenance_verified=True,
                limitation="No active approved purchase-order source evidence is available.")
        if len(current_po) != 1 or current_po[0][2]:
            return FactualInvestigationResult(**base, decision="ABSTAIN",
                classification="CONFLICTING_EVIDENCE", provenance_verified=True,
                limitation="Multiple current or contradicting purchase-order versions are active.")
        if pack.factual_policy and pack.factual_policy.require_goods_receipt:
            receipts = self.repository.find_facts(
                tenant_id, subject_id=po_id, relation_type="GOODS_RECEIPT_FOR_PO")
            approved_receipts = [(item, self.repository.get_fact_evidence(item.fact_id, tenant_id)[0])
                                 for item in receipts]
            approved_receipts = [(item, linked) for item, linked in approved_receipts if linked]
            if not approved_receipts:
                return FactualInvestigationResult(**base, decision="ABSTAIN",
                    classification="INSUFFICIENT_EVIDENCE", provenance_verified=True,
                    limitation="A three-way match requires an active approved goods receipt.")
            for receipt, linked in approved_receipts:
                base["fact_ids"].append(receipt.fact_id)
                for source in linked:
                    evidence_ids.add(source.evidence_id)
                    document_ids.add(source.document_id)
                    source_groups.add(source.source_group or source.evidence_id)
            base["evidence_ids"] = sorted(evidence_ids)
            base["document_ids"] = sorted(document_ids)
            base["source_groups"] = sorted(source_groups)
        try:
            findings = self._compare(invoice, current_po[0][0].attributes, pack)
        except (KeyError, ValueError, TypeError, InvalidOperation):
            return FactualInvestigationResult(**base, decision="ABSTAIN",
                classification="INSUFFICIENT_EVIDENCE", provenance_verified=True,
                limitation="Required reconciliation fields are missing, invalid, or ambiguous.")
        mismatch = any(item["status"] == "MISMATCH" for item in findings)
        return FactualInvestigationResult(**base, decision="ANSWER",
            classification="MISMATCH_SUPPORTED" if mismatch else "MATCH_SUPPORTED",
            findings=findings, provenance_verified=True,
            limitation="A discrepancy is not evidence of fraud or intent." if mismatch else None)

    @staticmethod
    def _semantic_fingerprint(attributes: dict) -> str:
        payload = repr(sorted((key, value) for key, value in attributes.items()
                              if key not in {"source_row", "reviewed_by"}))
        return sha256(payload.encode()).hexdigest()

    @staticmethod
    def _compare(invoice: dict, purchase_order: dict, pack: DomainPack) -> list[dict]:
        policy = pack.factual_policy
        assert policy is not None
        for record in (invoice, purchase_order):
            if not all(record.get(key) for key in ("supplier_id", "currency", "lines")):
                raise ValueError("supplier, currency and nonempty line items are required")
            for line in record["lines"]:
                if not line.get("line_id"):
                    raise ValueError("line identifier is required")
                for field in ("quantity", "unit_price"):
                    value = Decimal(str(line[field]))
                    if not value.is_finite() or value < 0:
                        raise ValueError("line values must be finite and nonnegative")
        for field in ("tax", "shipping", "total"):
            value = Decimal(str(invoice[field]))
            if not value.is_finite() or value < 0:
                raise ValueError("explicit finite tax, shipping and total amounts are required")
        findings: list[dict] = []
        for field in ("supplier_id", "currency"):
            actual, expected = invoice.get(field), purchase_order.get(field)
            if field == "currency" and not policy.currency_must_match:
                continue
            findings.append({"field": field, "invoice": actual, "purchase_order": expected,
                             "status": "MATCH" if actual == expected else "MISMATCH"})
        invoice_lines = {str(line["line_id"]): line for line in invoice.get("lines", [])}
        po_lines = {str(line["line_id"]): line for line in purchase_order.get("lines", [])}
        if len(po_lines) != len(purchase_order["lines"]):
            raise ValueError("purchase-order line identifiers must be unique")
        if len(invoice_lines) != len(invoice.get("lines", [])):
            findings.append({"field": "duplicate_invoice_lines", "status": "MISMATCH"})
        for line_id in sorted(set(invoice_lines) | set(po_lines)):
            inv, po = invoice_lines.get(line_id), po_lines.get(line_id)
            if inv is None or po is None:
                findings.append({"field": f"line:{line_id}", "invoice": inv,
                                 "purchase_order": po, "status": "MISMATCH"})
                continue
            for field, tolerance in (("quantity", policy.quantity_tolerance),
                                     ("unit_price", policy.unit_price_tolerance)):
                actual, expected = Decimal(str(inv[field])), Decimal(str(po[field]))
                findings.append({"field": f"line:{line_id}:{field}",
                    "invoice": str(actual), "purchase_order": str(expected),
                    "difference": str(abs(actual - expected)),
                    "status": "MATCH" if abs(actual - expected) <= Decimal(tolerance) else "MISMATCH"})
        quant = Decimal("0.01")
        rounding = _ROUNDING[policy.rounding]
        subtotal = sum((Decimal(str(line["quantity"])) * Decimal(str(line["unit_price"]))
                        for line in invoice.get("lines", [])), Decimal("0")).quantize(quant, rounding=rounding)
        tax = Decimal(str(invoice.get("tax", "0"))).quantize(quant, rounding=rounding)
        shipping = Decimal(str(invoice.get("shipping", "0"))).quantize(quant, rounding=rounding)
        computed = (subtotal + tax + shipping).quantize(quant, rounding=rounding)
        stated = Decimal(str(invoice.get("total", "0"))).quantize(quant, rounding=rounding)
        findings.append({"field": "invoice_total", "computed": str(computed), "stated": str(stated),
                         "difference": str(abs(computed - stated)),
                         "status": "MATCH" if abs(computed - stated) <= Decimal(policy.total_tolerance)
                         else "MISMATCH"})
        return findings


def seed_synthetic_procurement(repository: BaseGraphRepository, tenant_id: str, *,
                               invoice_id: str = "INV-1001", po_id: str = "PO-2001",
                               quantity: str = "2", unit_price: str = "10.00",
                               include_po: bool = True, include_receipt: bool = True,
                               version: int = 1, current_version: bool = True,
                               source_suffix: str = "base") -> None:
    """Reproducible synthetic fixture; callers must use disposable stores only."""
    source_group = f"synthetic-procurement:{invoice_id}:{source_suffix}"
    invoice_doc = f"doc-{invoice_id}-{source_suffix}"
    repository.upsert_document(Document(document_id=invoice_doc, tenant_id=tenant_id,
        title=f"SYNTHETIC invoice {invoice_id}", source_uri=f"synthetic://{invoice_id}/{source_suffix}",
        source_type="synthetic_invoice", raw_content=f"{invoice_id}|{po_id}|{quantity}|{unit_price}"))
    repository.upsert_entity(Entity(entity_id=invoice_id, tenant_id=tenant_id,
        entity_type="invoice", canonical_name=invoice_id, attributes={"synthetic": True}))
    if include_po:
        repository.upsert_entity(Entity(entity_id=po_id, tenant_id=tenant_id,
            entity_type="purchase_order", canonical_name=po_id, attributes={
                "supplier_id": "SUP-1", "currency": "USD",
                "lines": [{"line_id": "1", "quantity": "2", "unit_price": "10.00"}],
                "synthetic": True}))
        po_doc = f"doc-{po_id}"
        repository.upsert_document(Document(document_id=po_doc, tenant_id=tenant_id,
            title=f"SYNTHETIC purchase order {po_id}", source_uri=f"synthetic://{po_id}",
            source_type="synthetic_purchase_order", raw_content=f"{po_id}|SUP-1|USD|2|10.00"))
        po_fact = f"fact-{po_id}"
        repository.upsert_relation_fact(RelationFact(fact_id=po_fact, tenant_id=tenant_id,
            relation_type="PROCUREMENT_PURCHASE_ORDER_SNAPSHOT", subject_id=po_id,
            object_id=po_id, attributes={"supplier_id": "SUP-1", "currency": "USD",
                "lines": [{"line_id": "1", "quantity": "2", "unit_price": "10.00"}],
                "current_version": True, "synthetic": True}, review_status="APPROVED"))
        po_evidence = f"evidence-{po_id}"
        repository.upsert_evidence(Evidence(evidence_id=po_evidence, tenant_id=tenant_id,
            document_id=po_doc, chunk_ref="row:1", content=f"SYNTHETIC {po_id}",
            source_group=f"synthetic-procurement:{po_id}", review_status="APPROVED"))
        repository.link_evidence_to_fact(po_evidence, po_fact, EvidenceType.SUPPORTS, tenant_id)
    else:
        repository.upsert_entity(Entity(entity_id=po_id, tenant_id=tenant_id,
            entity_type="missing_purchase_order", canonical_name=po_id, attributes={"synthetic": True}))
    fact_id = f"fact-{invoice_id}-v{version}-{source_suffix}"
    repository.upsert_relation_fact(RelationFact(fact_id=fact_id, tenant_id=tenant_id,
        relation_type="PROCUREMENT_INVOICE_SNAPSHOT", subject_id=invoice_id, object_id=po_id,
        attributes={"purchase_order_id": po_id, "supplier_id": "SUP-1", "currency": "USD",
            "lines": [{"line_id": "1", "quantity": quantity, "unit_price": unit_price}],
            "tax": "2.00", "shipping": "0.00",
            "total": str((Decimal(quantity) * Decimal(unit_price) + Decimal("2.00")).quantize(Decimal("0.01"))),
            "document_version": version, "current_version": current_version, "synthetic": True},
        review_status="APPROVED"))
    evidence_id = f"evidence-{invoice_id}-v{version}-{source_suffix}"
    repository.upsert_evidence(Evidence(evidence_id=evidence_id, tenant_id=tenant_id,
        document_id=invoice_doc, chunk_ref="row:1", content=f"SYNTHETIC {invoice_id} version {version}",
        source_group=source_group, review_status="APPROVED"))
    repository.link_evidence_to_fact(evidence_id, fact_id, EvidenceType.SUPPORTS, tenant_id)
    if include_receipt:
        receipt_id = f"GR-{po_id}"
        receipt_doc = f"doc-{receipt_id}"
        repository.upsert_document(Document(document_id=receipt_doc, tenant_id=tenant_id,
            title=f"SYNTHETIC receipt {receipt_id}", source_uri=f"synthetic://{receipt_id}",
            source_type="synthetic_goods_receipt", raw_content=receipt_id))
        repository.upsert_entity(Entity(entity_id=receipt_id, tenant_id=tenant_id,
            entity_type="goods_receipt", canonical_name=receipt_id, attributes={"synthetic": True}))
        receipt_fact = f"fact-{receipt_id}"
        repository.upsert_relation_fact(RelationFact(fact_id=receipt_fact, tenant_id=tenant_id,
            relation_type="GOODS_RECEIPT_FOR_PO", subject_id=po_id, object_id=receipt_id,
            attributes={"quantity": "2", "synthetic": True}, review_status="APPROVED"))
        receipt_ev = f"evidence-{receipt_id}"
        repository.upsert_evidence(Evidence(evidence_id=receipt_ev, tenant_id=tenant_id,
            document_id=receipt_doc, chunk_ref="row:1", content=f"SYNTHETIC receipt {receipt_id}",
            source_group=f"synthetic-procurement:{receipt_id}", review_status="APPROVED"))
        repository.link_evidence_to_fact(receipt_ev, receipt_fact, EvidenceType.SUPPORTS, tenant_id)
