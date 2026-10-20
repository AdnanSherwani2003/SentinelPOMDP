"""Secure deterministic ingestion, extraction, review, and graph publication."""
from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from typing import Callable

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.graph.schemas import Document, Entity, Evidence, EvidenceType, RelationFact

from .models import (
    CandidateSource, CandidateStatus, CompanyDocument, DatasetConfiguration,
    DocumentStatus, FactCandidate, IngestionResult, NormalizedDocument, ReviewAction,
    utc_now,
)
from .parsers import DocumentParseError, MEDIA_TYPES, parse_document
from .storage import LocalDocumentStore


class IngestionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("\0".join(values).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


class EnterpriseDataService:
    def __init__(self, store: LocalDocumentStore, repository: BaseGraphRepository, *,
                 max_upload_bytes: int = 10 * 1024 * 1024,
                 max_uncompressed_bytes: int = 50 * 1024 * 1024,
                 max_documents_per_tenant: int = 100) -> None:
        self.store = store
        self.repository = repository
        self.max_upload_bytes = max_upload_bytes
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_documents_per_tenant = max_documents_per_tenant

    def configure_dataset(self, tenant_id: str, configuration: DatasetConfiguration) -> DatasetConfiguration:
        self.store.put_dataset(tenant_id, configuration)
        return configuration

    def upload(self, tenant_id: str, *, dataset_id: str, filename: str, content: bytes,
               declared_media_type: str = "application/octet-stream",
               source_group: str | None = None) -> IngestionResult:
        if not content:
            raise IngestionError("EMPTY_UPLOAD", "uploaded content is empty")
        if len(content) > self.max_upload_bytes:
            raise IngestionError("UPLOAD_TOO_LARGE", "upload exceeds the configured byte limit")
        dataset = self.store.get_dataset(tenant_id, dataset_id)
        if dataset is None:
            raise IngestionError("DATASET_NOT_FOUND", "a configured dataset is required")
        documents = self.store.list_documents(tenant_id)
        digest = sha256(content).hexdigest()
        duplicate = next((item for item in documents if item.source_hash == digest and item.active), None)
        if duplicate:
            return IngestionResult(ingestion_id=duplicate.ingestion_id,
                                   document=duplicate, duplicate=True, candidates_created=0)
        if sum(item.active for item in documents) >= self.max_documents_per_tenant:
            raise IngestionError("DOCUMENT_LIMIT", "tenant document-count limit reached")
        safe_name = Path(filename).name
        if (not safe_name or safe_name in {".", ".."}
                or any(ord(character) < 32 or ord(character) == 127 for character in safe_name)):
            raise IngestionError("INVALID_FILENAME", "source name is invalid")
        history = sorted((item for item in documents
                          if item.dataset_id == dataset_id
                          and item.source_name.casefold() == safe_name.casefold()),
                         key=lambda item: item.version)
        active_previous = [item for item in history if item.active]
        version = (history[-1].version + 1) if history else 1
        ingestion_id = f"ing_{uuid4().hex}"
        document_id = _stable_id(
            "doc", tenant_id, dataset_id, safe_name, str(version), digest)
        group = (source_group or document_id).strip()
        if not group or len(group) > 256:
            raise IngestionError("INVALID_SOURCE_GROUP", "source group must contain 1-256 characters")
        started = perf_counter()
        try:
            source_type, normalized = parse_document(
                filename=safe_name, data=content, tenant_id=tenant_id,
                document_id=document_id, version=version, source_group=group,
                max_uncompressed_bytes=self.max_uncompressed_bytes)
        except DocumentParseError as exc:
            status = DocumentStatus.NEEDS_OCR if exc.code == "OCR_REQUIRED" else DocumentStatus.FAILED
            failed = CompanyDocument(
                document_id=document_id, tenant_id=tenant_id, dataset_id=dataset_id,
                source_name=safe_name, source_type=Path(safe_name).suffix.lstrip(".").lower() or "unknown",
                media_type=declared_media_type, source_hash=digest, version=version,
                ingestion_id=ingestion_id, status=status, byte_size=len(content),
                failure_code=exc.code, active=False)
            self.store.put_document(failed, content, NormalizedDocument(
                document_id=document_id, tenant_id=tenant_id, source_type="txt", warnings=[str(exc)]))
            raise IngestionError(exc.code, str(exc)) from None
        if source_type not in dataset.allowed_source_types:
            raise IngestionError("SOURCE_TYPE_NOT_ALLOWED", "dataset does not permit this source type")
        document = CompanyDocument(
            document_id=document_id, tenant_id=tenant_id, dataset_id=dataset_id,
            source_name=safe_name, source_type=source_type,
            media_type=MEDIA_TYPES[source_type], source_hash=digest, version=version,
            ingestion_id=ingestion_id, status=DocumentStatus.PARSED, byte_size=len(content),
            supersedes_document_id=history[-1].document_id if history else None,
            parser_warnings=normalized.warnings)
        for old in active_previous:
            updated = old.model_copy(update={"status": DocumentStatus.SUPERSEDED, "active": False})
            self.store.update_document(updated)
            self.repository.deactivate_document(old.document_id, tenant_id)
            self._supersede_candidates(tenant_id, old.document_id)
        self.store.put_document(document, content, normalized)
        candidates = self._extract_delivery_candidates(tenant_id, dataset)
        return IngestionResult(ingestion_id=ingestion_id, document=document,
                               candidates_created=candidates)

    def _supersede_candidates(self, tenant_id: str, document_id: str) -> None:
        for candidate in self.store.list_candidates(tenant_id):
            if candidate.status not in {CandidateStatus.REJECTED, CandidateStatus.SUPERSEDED} and any(
                    source.location.document_id == document_id for source in candidate.sources):
                self.store.put_candidate(candidate.model_copy(update={"status": CandidateStatus.SUPERSEDED}))

    @staticmethod
    def _parse_date(value: str, date_format: str) -> datetime:
        try:
            return datetime.strptime(value.strip(), date_format)
        except ValueError as exc:
            raise IngestionError("INVALID_DATE", "a mapped date does not match the configured format") from exc

    def _extract_delivery_candidates(self, tenant_id: str, dataset: DatasetConfiguration) -> int:
        active_ids = {item.document_id for item in self.store.list_documents(tenant_id)
                      if item.active and item.dataset_id == dataset.dataset_id}
        expected: dict[str, list[tuple[str, object]]] = {}
        actual: dict[str, list[tuple[str, object]]] = {}
        supplier: dict[str, str] = {}
        mapping = dataset.field_mapping
        for normalized in self.store.list_normalized(tenant_id):
            if normalized.document_id not in active_ids:
                continue
            for record in normalized.records:
                po = record.fields.get(mapping["purchase_order"], "").strip().upper()
                if not po:
                    continue
                if "supplier" in mapping and record.fields.get(mapping["supplier"]):
                    supplier[po] = record.fields[mapping["supplier"]].strip()
                if "expected_date" in mapping and record.fields.get(mapping["expected_date"]):
                    expected.setdefault(po, []).append((record.fields[mapping["expected_date"]], record.location))
                if "actual_date" in mapping and record.fields.get(mapping["actual_date"]):
                    actual.setdefault(po, []).append((record.fields[mapping["actual_date"]], record.location))
        # Text/PDF/DOCX may contribute direct expected/received statements.
        date_pattern = r"(\d{4}-\d{2}-\d{2})"
        for normalized in self.store.list_normalized(tenant_id):
            if normalized.document_id not in active_ids:
                continue
            for segment in normalized.segments:
                po_match = re.search(r"\bPO-[A-Za-z0-9_-]+\b", segment.text, re.IGNORECASE)
                if not po_match:
                    continue
                po = po_match.group(0).upper()
                expected_match = re.search(rf"(?:expected|scheduled)[^\n.]{{0,80}}{date_pattern}",
                                           segment.text, re.IGNORECASE)
                actual_match = re.search(rf"(?:received|delivered)[^\n.]{{0,80}}{date_pattern}",
                                         segment.text, re.IGNORECASE)
                if expected_match:
                    expected.setdefault(po, []).append((expected_match.group(1), segment.location))
                if actual_match:
                    actual.setdefault(po, []).append((actual_match.group(1), segment.location))
        created = 0
        existing = {item.candidate_id: item for item in self.store.list_candidates(tenant_id)}
        for po in sorted(set(expected) & set(actual)):
            expected_values = {value for value, _ in expected[po]}
            actual_values = {value for value, _ in actual[po]}
            warnings = []
            if len(expected_values) > 1 or len(actual_values) > 1:
                warnings.append("CONFLICTING_SOURCE_VALUES")
            for expected_value, expected_location in expected[po]:
                for actual_value, actual_location in actual[po]:
                    delayed = self._parse_date(actual_value, dataset.date_format) > self._parse_date(
                        expected_value, dataset.date_format)
                    relation = "EXPERIENCED_DELAY" if delayed else "DELIVERED_ON_TIME"
                    candidate_id = _stable_id("candidate", tenant_id, dataset.dataset_id, po,
                                              expected_value, actual_value)
                    if candidate_id in existing and existing[candidate_id].status != CandidateStatus.SUPERSEDED:
                        continue
                    candidate = FactCandidate(
                        candidate_id=candidate_id, tenant_id=tenant_id, dataset_id=dataset.dataset_id,
                        subject_id=po, subject_name=po,
                        object_id=f"delivery_{po.casefold()}", object_name=f"Delivery for {po}",
                        relation_type=relation,
                        attributes={"expected_date": expected_value, "actual_date": actual_value,
                                    "supplier": supplier.get(po), "timezone": dataset.timezone,
                                    "calculation": "actual_date > expected_date"},
                        sources=[
                            CandidateSource(location=expected_location, extraction_method="structured_mapping",
                                            extraction_confidence=1, direct_statement=True),
                            CandidateSource(location=actual_location, extraction_method="structured_mapping",
                                            extraction_confidence=1, direct_statement=True),
                        ], warnings=warnings)
                    self.store.put_candidate(candidate)
                    created += 1
        return created

    def review(self, tenant_id: str, candidate_id: str, action: ReviewAction,
               reviewer_id: str, note: str | None = None,
               publisher: Callable[[FactCandidate], str] | None = None) -> FactCandidate:
        candidate = self.store.get_candidate(tenant_id, candidate_id)
        if candidate is None or candidate.status not in {
                CandidateStatus.NEEDS_REVIEW, CandidateStatus.EXTRACTED}:
            raise IngestionError("CANDIDATE_NOT_REVIEWABLE", "candidate is unavailable for review")
        if action == ReviewAction.REJECT:
            rejected = candidate.model_copy(update={
                "status": CandidateStatus.REJECTED, "reviewed_at": utc_now(),
                "reviewed_by": reviewer_id, "review_note": note})
            self.store.put_candidate(rejected)
            return rejected
        for source in candidate.sources:
            document = self.store.get_document(tenant_id, source.location.document_id)
            if document is None or not document.active or document.version != source.location.version:
                raise IngestionError("STALE_SOURCE", "candidate source is missing, superseded, or withdrawn")
        if publisher is not None:
            fact_id = publisher(candidate)
            approved = candidate.model_copy(update={
                "status": CandidateStatus.APPROVED, "reviewed_at": utc_now(),
                "reviewed_by": reviewer_id, "review_note": note, "graph_fact_id": fact_id})
            self.store.put_candidate(approved)
            return approved
        fact_id = _stable_id("fact_delivery", tenant_id, candidate.dataset_id, candidate.subject_id)
        self.repository.upsert_entity(Entity(
            entity_id=candidate.subject_id, tenant_id=tenant_id, entity_type="purchase_order",
            canonical_name=candidate.subject_name, attributes={"dataset_id": candidate.dataset_id}))
        self.repository.upsert_entity(Entity(
            entity_id=candidate.object_id, tenant_id=tenant_id, entity_type="shipment",
            canonical_name=candidate.object_name, attributes={"dataset_id": candidate.dataset_id}))
        # The canonical claim is shipment delay. An on-time candidate contradicts it.
        self.repository.upsert_relation_fact(RelationFact(
            fact_id=fact_id, tenant_id=tenant_id, relation_type="EXPERIENCED_DELAY",
            subject_id=candidate.subject_id, object_id=candidate.object_id,
            attributes={**candidate.attributes, "candidate_id": candidate.candidate_id,
                        "model_role": "document-derived observation"},
            review_status="APPROVED", active=True))
        link_type = (EvidenceType.SUPPORTS if candidate.relation_type == "EXPERIENCED_DELAY"
                     else EvidenceType.CONTRADICTS)
        for index, source in enumerate(candidate.sources, start=1):
            metadata = self.store.get_document(tenant_id, source.location.document_id)
            assert metadata is not None
            self.repository.upsert_document(Document(
                document_id=metadata.document_id, tenant_id=tenant_id, title=metadata.source_name,
                source_uri=f"sentinel://documents/{metadata.document_id}",
                source_type=metadata.source_type, classification=metadata.classification,
                raw_content="", content_hash=metadata.source_hash, version=metadata.version,
                review_status="APPROVED", active=True))
            evidence_id = _stable_id("ev", candidate.candidate_id, metadata.document_id,
                                     source.location.locator)
            self.repository.upsert_evidence(Evidence(
                evidence_id=evidence_id, tenant_id=tenant_id, document_id=metadata.document_id,
                chunk_ref=source.location.locator, content=source.location.source_text,
                extraction_method=source.extraction_method,
                extraction_confidence=source.extraction_confidence,
                source_group=source.location.source_group, review_status="APPROVED", active=True))
            self.repository.link_evidence_to_fact(evidence_id, fact_id, link_type, tenant_id)
        approved = candidate.model_copy(update={
            "status": CandidateStatus.APPROVED, "reviewed_at": utc_now(),
            "reviewed_by": reviewer_id, "review_note": note, "graph_fact_id": fact_id})
        self.store.put_candidate(approved)
        return approved

    def withdraw(self, tenant_id: str, document_id: str) -> CompanyDocument:
        document = self.store.get_document(tenant_id, document_id)
        if document is None or not document.active:
            raise IngestionError("DOCUMENT_NOT_FOUND", "document is unavailable")
        withdrawn = document.model_copy(update={"status": DocumentStatus.WITHDRAWN, "active": False})
        self.store.update_document(withdrawn)
        self.repository.deactivate_document(document_id, tenant_id)
        self._supersede_candidates(tenant_id, document_id)
        return withdrawn

    def lookup(self, tenant_id: str, question: str) -> dict:
        match = re.search(r"\bPO-[A-Za-z0-9_-]+\b", question, re.IGNORECASE)
        if not match:
            raise IngestionError("LOOKUP_UNSUPPORTED", "lookup requires a purchase-order identifier")
        po = match.group(0).upper()
        rows = []
        for candidate in self.store.list_candidates(tenant_id):
            if candidate.subject_id == po and candidate.status == CandidateStatus.APPROVED:
                active_sources = []
                for source in candidate.sources:
                    document = self.store.get_document(tenant_id, source.location.document_id)
                    if document and document.active and document.version == source.location.version:
                        active_sources.append(source.location.model_dump())
                if active_sources:
                    rows.append({
                        "candidate_id": candidate.candidate_id,
                        "relation_type": candidate.relation_type,
                        "attributes": candidate.attributes,
                        "sources": active_sources,
                    })
        return {"mode": "DOCUMENT_LOOKUP", "purchase_order": po, "records": rows,
                "status": "FOUND" if rows else "NO_APPROVED_EVIDENCE"}
