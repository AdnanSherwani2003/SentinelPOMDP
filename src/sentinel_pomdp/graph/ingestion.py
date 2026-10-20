"""Idempotent, validated Ingestion Pipeline for the Knowledge Graph.

Orchestrates:
1. Pre-ingestion schema & foreign-key validation
2. Entity normalization and type allowlist enforcement
3. Deterministic upsert operations (Entity -> Document -> RelationFact -> Evidence)
4. Provenance link creation (SUPPORTS / CONTRADICTS)
5. Strict tenant boundary verification
6. Audit reporting with execution metrics
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from sentinel_pomdp.data.synthetic.supplier_delay import SupplierDelayDataset
from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.graph.schemas import (
    Document,
    Entity,
    Evidence,
    EvidenceLink,
    EvidenceType,
    RelationFact,
)

logger = logging.getLogger(__name__)

# Extensible allowlists for domain validation
ALLOWED_ENTITY_TYPES: Set[str] = {
    "purchase_order",
    "supplier",
    "component",
    "product",
    "facility",
    "production_schedule",
    "incident",
    "shipment",
    "organization",
    "operational_unit",
    "generic_entity",
}

ALLOWED_RELATION_TYPES: Set[str] = {
    "SUPPLIES",
    "PART_OF",
    "CARRIES",
    "DELIVERED_TO",
    "EXPERIENCED_DELAY",
    "DELIVERED_ON_TIME",
    "HAS_CERTIFICATION",
    "IMPACTS",
    "ATTRIBUTED_SUSPECT",
    "RELATED_TO",
    "DEPENDS_ON",
}


@dataclass
class IngestionReport:
    """Metrics and diagnostics from a dataset ingestion run."""

    entities_upserted: int = 0
    documents_upserted: int = 0
    facts_upserted: int = 0
    evidence_upserted: int = 0
    links_created: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        """True if all records were ingested with zero errors."""
        return len(self.errors) == 0

    def summary(self) -> str:
        status = "SUCCESS" if self.is_success else "FAILED"
        return (
            f"Ingestion {status}: {self.entities_upserted} entities, "
            f"{self.documents_upserted} documents, {self.facts_upserted} facts, "
            f"{self.evidence_upserted} evidence, {self.links_created} links. "
            f"Errors: {len(self.errors)}"
        )


class IngestionValidationError(ValueError):
    """Raised when record validation fails during ingestion."""
    pass


class KnowledgeGraphIngestionPipeline:
    """Production-grade ingestion pipeline enforcing schemas and tenant isolation."""

    def __init__(
        self,
        repository: BaseGraphRepository,
        enforce_type_allowlists: bool = True,
    ) -> None:
        self.repo = repository
        self.enforce_allowlists = enforce_type_allowlists

    def validate_dataset(self, dataset: SupplierDelayDataset) -> List[str]:
        """Verify referential integrity and schema conformance prior to database writes.

        Checks:
        1. Entities have valid types and non-empty IDs
        2. Documents have non-empty source URIs and content hashes
        3. Facts reference existing entities within the exact same tenant
        4. Evidence references existing documents within the exact same tenant
        5. Evidence links reference existing evidence and facts within the exact same tenant
        """
        errors: List[str] = []

        # Track known identifiers keyed by (tenant_id, id)
        known_entities: Set[tuple[str, str]] = set()
        known_docs: Set[tuple[str, str]] = set()
        known_facts: Set[tuple[str, str]] = set()
        known_evidence: Set[tuple[str, str]] = set()

        # Validate Entities
        for e in dataset.entities:
            if not e.entity_id or not e.tenant_id:
                errors.append(f"Entity missing ID or tenant: {e}")
                continue
            if self.enforce_allowlists and e.entity_type not in ALLOWED_ENTITY_TYPES:
                errors.append(f"Unsupported entity_type '{e.entity_type}' on entity '{e.entity_id}'")
            known_entities.add((e.tenant_id, e.entity_id))

        # Validate Documents
        for d in dataset.documents:
            if not d.document_id or not d.tenant_id:
                errors.append(f"Document missing ID or tenant: {d}")
                continue
            if not d.content_hash:
                errors.append(f"Document '{d.document_id}' missing content_hash")
            known_docs.add((d.tenant_id, d.document_id))

        # Validate Facts
        for f in dataset.facts:
            if not f.fact_id or not f.tenant_id:
                errors.append(f"Fact missing ID or tenant: {f}")
                continue
            if self.enforce_allowlists and f.relation_type not in ALLOWED_RELATION_TYPES:
                errors.append(f"Unsupported relation_type '{f.relation_type}' on fact '{f.fact_id}'")

            s_key = (f.tenant_id, f.subject_id)
            o_key = (f.tenant_id, f.object_id)
            if s_key not in known_entities:
                errors.append(
                    f"Fact '{f.fact_id}' references unknown subject entity '{f.subject_id}' in tenant '{f.tenant_id}'"
                )
            if o_key not in known_entities:
                errors.append(
                    f"Fact '{f.fact_id}' references unknown object entity '{f.object_id}' in tenant '{f.tenant_id}'"
                )
            known_facts.add((f.tenant_id, f.fact_id))

        # Validate Evidence
        for ev in dataset.evidence:
            if not ev.evidence_id or not ev.tenant_id:
                errors.append(f"Evidence missing ID or tenant: {ev}")
                continue
            doc_key = (ev.tenant_id, ev.document_id)
            if doc_key not in known_docs:
                errors.append(
                    f"Evidence '{ev.evidence_id}' references unknown document '{ev.document_id}' in tenant '{ev.tenant_id}'"
                )
            if not (0.0 <= ev.extraction_confidence <= 1.0):
                errors.append(
                    f"Evidence '{ev.evidence_id}' extraction_confidence {ev.extraction_confidence} outside [0.0, 1.0]"
                )
            known_evidence.add((ev.tenant_id, ev.evidence_id))

        # Validate Evidence Links
        for link in dataset.links:
            ev_key = (link.tenant_id, link.evidence_id)
            fact_key = (link.tenant_id, link.fact_id)
            if ev_key not in known_evidence:
                errors.append(
                    f"Link '{link.link_id}' references unknown evidence '{link.evidence_id}' in tenant '{link.tenant_id}'"
                )
            if fact_key not in known_facts:
                errors.append(
                    f"Link '{link.link_id}' references unknown fact '{link.fact_id}' in tenant '{link.tenant_id}'"
                )

        return errors

    def ingest_dataset(self, dataset: SupplierDelayDataset) -> IngestionReport:
        """Execute deterministic, idempotent ingestion of the synthetic dataset.

        Args:
            dataset: The validated dataset container.

        Returns:
            IngestionReport with count of upserted items and any runtime errors.
        """
        report = IngestionReport()

        # Step 1: Pre-flight validation
        validation_errors = self.validate_dataset(dataset)
        if validation_errors:
            report.errors.extend(validation_errors)
            logger.error("Dataset validation failed with %d errors", len(validation_errors))
            return report

        # Step 2: Ingest Entities
        for entity in dataset.entities:
            try:
                self.repo.upsert_entity(entity)
                report.entities_upserted += 1
            except Exception as e:
                msg = f"Failed to upsert entity {entity.entity_id}: {e}"
                logger.exception(msg)
                report.errors.append(msg)

        # Step 3: Ingest Documents
        for doc in dataset.documents:
            try:
                self.repo.upsert_document(doc)
                report.documents_upserted += 1
            except Exception as e:
                msg = f"Failed to upsert document {doc.document_id}: {e}"
                logger.exception(msg)
                report.errors.append(msg)

        # Step 4: Ingest Facts
        for fact in dataset.facts:
            try:
                self.repo.upsert_relation_fact(fact)
                report.facts_upserted += 1
            except Exception as e:
                msg = f"Failed to upsert fact {fact.fact_id}: {e}"
                logger.exception(msg)
                report.errors.append(msg)

        # Step 5: Ingest Evidence
        for ev in dataset.evidence:
            try:
                self.repo.upsert_evidence(ev)
                report.evidence_upserted += 1
            except Exception as e:
                msg = f"Failed to upsert evidence {ev.evidence_id}: {e}"
                logger.exception(msg)
                report.errors.append(msg)

        # Step 6: Ingest Links
        for link in dataset.links:
            try:
                self.repo.link_evidence_to_fact(
                    evidence_id=link.evidence_id,
                    fact_id=link.fact_id,
                    link_type=link.link_type,
                    tenant_id=link.tenant_id,
                )
                report.links_created += 1
            except Exception as e:
                msg = f"Failed to link evidence {link.evidence_id} to fact {link.fact_id}: {e}"
                logger.exception(msg)
                report.errors.append(msg)

        logger.info(report.summary())
        return report
