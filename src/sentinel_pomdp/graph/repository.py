"""Graph Repository interface and Neo4j implementation.

Provides parameterized, tenant-scoped Cypher queries for entities, documents,
facts, evidence, and provenance links.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from neo4j import Session, Transaction

from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.schemas import (
    Document,
    Entity,
    Evidence,
    EvidenceType,
    ProvenanceChain,
    ProvenanceRecord,
    RelationFact,
    TraversalPath,
)

logger = logging.getLogger(__name__)


class BaseGraphRepository(ABC):
    """Abstract Base Class defining the domain-adaptable graph repository contract."""

    @abstractmethod
    def init_schema_constraints(self) -> None:
        """Create database uniqueness constraints and indexes."""
        pass

    @abstractmethod
    def upsert_entity(self, entity: Entity) -> None:
        """Idempotently create or update an Entity within a tenant boundary."""
        pass

    @abstractmethod
    def upsert_document(self, document: Document) -> None:
        """Idempotently create or update a Document record."""
        pass

    @abstractmethod
    def upsert_evidence(self, evidence: Evidence) -> None:
        """Idempotently create or update an Evidence record linked to its source Document."""
        pass

    @abstractmethod
    def upsert_relation_fact(self, fact: RelationFact) -> None:
        """Idempotently create or update a RelationFact linked to Subject and Object entities."""
        pass

    @abstractmethod
    def link_evidence_to_fact(
        self,
        evidence_id: str,
        fact_id: str,
        link_type: EvidenceType,
        tenant_id: str,
    ) -> None:
        """Connect evidence to a fact with SUPPORTS or CONTRADICTS semantic relationship."""
        pass

    @abstractmethod
    def get_entity(self, entity_id: str, tenant_id: str) -> Optional[Entity]:
        """Retrieve an entity by ID within tenant boundary."""
        pass

    @abstractmethod
    def list_entities(
        self,
        tenant_id: str,
        entity_type: Optional[str] = None,
    ) -> List[Entity]:
        """List entities for a tenant, optionally filtered by type."""
        pass

    @abstractmethod
    def get_document(self, document_id: str, tenant_id: str) -> Optional[Document]:
        """Retrieve a document by ID within tenant boundary."""
        pass

    @abstractmethod
    def list_documents(self, tenant_id: str) -> List[Document]:
        """List active documents within a tenant boundary."""
        pass

    @abstractmethod
    def deactivate_document(self, document_id: str, tenant_id: str) -> bool:
        """Deactivate a document and its derived evidence without deleting audit history."""
        pass

    @abstractmethod
    def get_evidence_record(self, evidence_id: str, tenant_id: str) -> Optional[ProvenanceRecord]:
        """Retrieve evidence plus source metadata within tenant boundary."""
        pass

    @abstractmethod
    def get_relation_fact(self, fact_id: str, tenant_id: str) -> Optional[RelationFact]:
        """Retrieve a fact by ID within tenant boundary."""
        pass

    @abstractmethod
    def find_facts(
        self,
        tenant_id: str,
        subject_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        object_id: Optional[str] = None,
    ) -> List[RelationFact]:
        """Find facts matching subject, relation type, or object filters within tenant."""
        pass

    @abstractmethod
    def get_fact_evidence(
        self,
        fact_id: str,
        tenant_id: str,
    ) -> Tuple[List[ProvenanceRecord], List[ProvenanceRecord]]:
        """Retrieve (supporting_evidence, contradicting_evidence) with document provenance."""
        pass

    @abstractmethod
    def get_provenance_chain(
        self,
        fact_id: str,
        tenant_id: str,
    ) -> Optional[ProvenanceChain]:
        """Assemble full auditable provenance chain for a fact."""
        pass

    @abstractmethod
    def get_multi_hop_relationships(
        self,
        start_entity_id: str,
        tenant_id: str,
        max_hops: int = 2,
    ) -> List[TraversalPath]:
        """Retrieve multi-hop traversal paths from a root entity within tenant."""
        pass


class Neo4jGraphRepository(BaseGraphRepository):
    """Production Neo4j implementation using parameterized Cypher queries."""

    def __init__(self, connection_manager: Neo4jConnectionManager) -> None:
        self.conn = connection_manager

    def init_schema_constraints(self) -> None:
        """Create uniqueness constraints for entities, documents, facts, and evidence."""
        constraints = [
            "CREATE CONSTRAINT entity_tenant_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE (e.tenant_id, e.entity_id) IS UNIQUE",
            "CREATE CONSTRAINT document_tenant_id_unique IF NOT EXISTS FOR (d:Document) REQUIRE (d.tenant_id, d.document_id) IS UNIQUE",
            "CREATE CONSTRAINT evidence_tenant_id_unique IF NOT EXISTS FOR (ev:Evidence) REQUIRE (ev.tenant_id, ev.evidence_id) IS UNIQUE",
            "CREATE CONSTRAINT fact_tenant_id_unique IF NOT EXISTS FOR (f:RelationFact) REQUIRE (f.tenant_id, f.fact_id) IS UNIQUE",
            "CREATE INDEX entity_type_idx IF NOT EXISTS FOR (e:Entity) ON (e.entity_type)",
            "CREATE INDEX fact_type_idx IF NOT EXISTS FOR (f:RelationFact) ON (f.relation_type)",
        ]
        with self.conn.session() as session:
            for statement in constraints:
                try:
                    session.run(statement)
                except Exception as e:
                    logger.warning("Error creating schema constraint/index: %s", e)

    def upsert_entity(self, entity: Entity) -> None:
        cypher = """
        MERGE (e:Entity {tenant_id: $tenant_id, entity_id: $entity_id})
        ON CREATE SET
            e.entity_type = $entity_type,
            e.canonical_name = $canonical_name,
            e.attributes_json = $attributes_json,
            e.created_at = $created_at,
            e.updated_at = $updated_at
        ON MATCH SET
            e.entity_type = $entity_type,
            e.canonical_name = $canonical_name,
            e.attributes_json = $attributes_json,
            e.updated_at = $updated_at
        """
        params = {
            "tenant_id": entity.tenant_id,
            "entity_id": entity.entity_id,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "attributes_json": json.dumps(entity.attributes, sort_keys=True),
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }
        with self.conn.session() as session:
            session.run(cypher, params)

    def upsert_document(self, document: Document) -> None:
        cypher = """
        MERGE (d:Document {tenant_id: $tenant_id, document_id: $document_id})
        ON CREATE SET
            d.title = $title,
            d.source_uri = $source_uri,
            d.source_type = $source_type,
            d.classification = $classification,
            d.content_hash = $content_hash,
            d.raw_content = $raw_content,
            d.created_at = $created_at,
            d.ingested_at = $ingested_at,
            d.version = $version,
            d.review_status = $review_status,
            d.active = $active
        ON MATCH SET
            d.title = $title,
            d.source_uri = $source_uri,
            d.source_type = $source_type,
            d.classification = $classification,
            d.content_hash = $content_hash,
            d.raw_content = $raw_content,
            d.ingested_at = $ingested_at,
            d.version = $version,
            d.review_status = $review_status,
            d.active = $active
        """
        params = {
            "tenant_id": document.tenant_id,
            "document_id": document.document_id,
            "title": document.title,
            "source_uri": document.source_uri,
            "source_type": document.source_type,
            "classification": document.classification,
            "content_hash": document.content_hash,
            "raw_content": document.raw_content,
            "created_at": document.created_at,
            "ingested_at": document.ingested_at,
            "version": document.version,
            "review_status": document.review_status,
            "active": document.active,
        }
        with self.conn.session() as session:
            session.run(cypher, params)

    def upsert_evidence(self, evidence: Evidence) -> None:
        cypher = """
        MATCH (d:Document {tenant_id: $tenant_id, document_id: $document_id})
        MERGE (ev:Evidence {tenant_id: $tenant_id, evidence_id: $evidence_id})
        ON CREATE SET
            ev.document_id = $document_id,
            ev.chunk_ref = $chunk_ref,
            ev.content = $content,
            ev.extraction_method = $extraction_method,
            ev.extraction_confidence = $extraction_confidence,
            ev.observed_at = $observed_at,
            ev.created_at = $created_at,
            ev.source_group = $source_group,
            ev.review_status = $review_status,
            ev.active = $active
        ON MATCH SET
            ev.chunk_ref = $chunk_ref,
            ev.content = $content,
            ev.extraction_method = $extraction_method,
            ev.extraction_confidence = $extraction_confidence,
            ev.observed_at = $observed_at,
            ev.source_group = $source_group,
            ev.review_status = $review_status,
            ev.active = $active
        MERGE (ev)-[:DERIVED_FROM]->(d)
        """
        params = {
            "tenant_id": evidence.tenant_id,
            "document_id": evidence.document_id,
            "evidence_id": evidence.evidence_id,
            "chunk_ref": evidence.chunk_ref,
            "content": evidence.content,
            "extraction_method": evidence.extraction_method,
            "extraction_confidence": float(evidence.extraction_confidence),
            "observed_at": evidence.observed_at,
            "created_at": evidence.created_at,
            "source_group": evidence.source_group,
            "review_status": evidence.review_status,
            "active": evidence.active,
        }
        with self.conn.session() as session:
            result = session.run(cypher, params)
            summary = result.consume()
            if summary.counters.nodes_created == 0 and summary.counters.relationships_created == 0 and summary.counters.properties_set == 0:
                # Check if document was missing
                doc_check = session.run(
                    "MATCH (d:Document {tenant_id: $t, document_id: $doc_id}) RETURN d.document_id",
                    {"t": evidence.tenant_id, "doc_id": evidence.document_id},
                )
                if not doc_check.single():
                    raise ValueError(
                        f"Cannot create evidence {evidence.evidence_id}: Referenced source document {evidence.document_id} does not exist in tenant {evidence.tenant_id}"
                    )

    def upsert_relation_fact(self, fact: RelationFact) -> None:
        cypher = """
        MATCH (s:Entity {tenant_id: $tenant_id, entity_id: $subject_id})
        MATCH (o:Entity {tenant_id: $tenant_id, entity_id: $object_id})
        MERGE (f:RelationFact {tenant_id: $tenant_id, fact_id: $fact_id})
        ON CREATE SET
            f.relation_type = $relation_type,
            f.subject_id = $subject_id,
            f.object_id = $object_id,
            f.attributes_json = $attributes_json,
            f.observed_at = $observed_at,
            f.valid_from = $valid_from,
            f.valid_to = $valid_to,
            f.created_at = $created_at,
            f.review_status = $review_status,
            f.active = $active
        ON MATCH SET
            f.relation_type = $relation_type,
            f.attributes_json = $attributes_json,
            f.observed_at = $observed_at,
            f.valid_from = $valid_from,
            f.valid_to = $valid_to,
            f.review_status = $review_status,
            f.active = $active
        MERGE (s)-[:SUBJECT_OF]->(f)
        MERGE (f)-[:OBJECT]->(o)
        """
        params = {
            "tenant_id": fact.tenant_id,
            "fact_id": fact.fact_id,
            "relation_type": fact.relation_type,
            "subject_id": fact.subject_id,
            "object_id": fact.object_id,
            "attributes_json": json.dumps(fact.attributes, sort_keys=True),
            "observed_at": fact.observed_at,
            "valid_from": fact.valid_from,
            "valid_to": fact.valid_to,
            "created_at": fact.created_at,
            "review_status": fact.review_status,
            "active": fact.active,
        }
        with self.conn.session() as session:
            result = session.run(cypher, params)
            summary = result.consume()
            if summary.counters.nodes_created == 0 and summary.counters.relationships_created == 0 and summary.counters.properties_set == 0:
                # Check missing subject or object
                s_check = session.run("MATCH (s:Entity {tenant_id: $t, entity_id: $s_id}) RETURN s", {"t": fact.tenant_id, "s_id": fact.subject_id}).single()
                o_check = session.run("MATCH (o:Entity {tenant_id: $t, entity_id: $o_id}) RETURN o", {"t": fact.tenant_id, "o_id": fact.object_id}).single()
                if not s_check:
                    raise ValueError(f"Subject entity '{fact.subject_id}' does not exist in tenant '{fact.tenant_id}'")
                if not o_check:
                    raise ValueError(f"Object entity '{fact.object_id}' does not exist in tenant '{fact.tenant_id}'")

    def link_evidence_to_fact(
        self,
        evidence_id: str,
        fact_id: str,
        link_type: EvidenceType,
        tenant_id: str,
    ) -> None:
        rel_label = "SUPPORTS" if link_type == EvidenceType.SUPPORTS else "CONTRADICTS"
        cypher = f"""
        MATCH (ev:Evidence {{tenant_id: $tenant_id, evidence_id: $evidence_id}})
        MATCH (f:RelationFact {{tenant_id: $tenant_id, fact_id: $fact_id}})
        MERGE (ev)-[r:{rel_label}]->(f)
        ON CREATE SET r.created_at = $now
        """
        params = {
            "tenant_id": tenant_id,
            "evidence_id": evidence_id,
            "fact_id": fact_id,
            "now": fact_id,
        }
        with self.conn.session() as session:
            res = session.run(cypher, params)
            summary = res.consume()
            if summary.counters.relationships_created == 0:
                ev_check = session.run("MATCH (ev:Evidence {tenant_id: $t, evidence_id: $e}) RETURN ev", {"t": tenant_id, "e": evidence_id}).single()
                f_check = session.run("MATCH (f:RelationFact {tenant_id: $t, fact_id: $f}) RETURN f", {"t": tenant_id, "f": fact_id}).single()
                if not ev_check:
                    raise ValueError(f"Evidence '{evidence_id}' does not exist in tenant '{tenant_id}'")
                if not f_check:
                    raise ValueError(f"RelationFact '{fact_id}' does not exist in tenant '{tenant_id}'")

    def get_entity(self, entity_id: str, tenant_id: str) -> Optional[Entity]:
        cypher = """
        MATCH (e:Entity {tenant_id: $tenant_id, entity_id: $entity_id})
        RETURN e.entity_id AS entity_id, e.tenant_id AS tenant_id, e.entity_type AS entity_type,
               e.canonical_name AS canonical_name, e.attributes_json AS attributes_json,
               e.created_at AS created_at, e.updated_at AS updated_at
        """
        with self.conn.session() as session:
            record = session.run(cypher, {"tenant_id": tenant_id, "entity_id": entity_id}).single()
            if not record:
                return None
            attrs = json.loads(record["attributes_json"]) if record["attributes_json"] else {}
            return Entity(
                entity_id=record["entity_id"],
                tenant_id=record["tenant_id"],
                entity_type=record["entity_type"],
                canonical_name=record["canonical_name"],
                attributes=attrs,
                created_at=record["created_at"],
                updated_at=record["updated_at"],
            )

    def list_entities(self, tenant_id: str, entity_type: Optional[str] = None) -> List[Entity]:
        where_clause = "WHERE e.tenant_id = $tenant_id"
        params: Dict[str, Any] = {"tenant_id": tenant_id}
        if entity_type:
            where_clause += " AND e.entity_type = $entity_type"
            params["entity_type"] = entity_type

        cypher = f"""
        MATCH (e:Entity)
        {where_clause}
        RETURN e.entity_id AS entity_id, e.tenant_id AS tenant_id, e.entity_type AS entity_type,
               e.canonical_name AS canonical_name, e.attributes_json AS attributes_json,
               e.created_at AS created_at, e.updated_at AS updated_at
        ORDER BY e.canonical_name
        """
        results = []
        with self.conn.session() as session:
            for record in session.run(cypher, params):
                attrs = json.loads(record["attributes_json"]) if record["attributes_json"] else {}
                results.append(
                    Entity(
                        entity_id=record["entity_id"],
                        tenant_id=record["tenant_id"],
                        entity_type=record["entity_type"],
                        canonical_name=record["canonical_name"],
                        attributes=attrs,
                        created_at=record["created_at"],
                        updated_at=record["updated_at"],
                    )
                )
        return results

    def get_document(self, document_id: str, tenant_id: str) -> Optional[Document]:
        cypher = """
        MATCH (d:Document {tenant_id: $tenant_id, document_id: $document_id})
        RETURN d.document_id AS document_id, d.tenant_id AS tenant_id, d.title AS title,
               d.source_uri AS source_uri, d.source_type AS source_type,
               d.classification AS classification, d.content_hash AS content_hash,
               d.raw_content AS raw_content, d.created_at AS created_at,
               d.ingested_at AS ingested_at, d.version AS version,
               d.review_status AS review_status, d.active AS active
        """
        with self.conn.session() as session:
            record = session.run(cypher, {"tenant_id": tenant_id, "document_id": document_id}).single()
            if not record:
                return None
            return Document(
                document_id=record["document_id"],
                tenant_id=record["tenant_id"],
                title=record["title"],
                source_uri=record["source_uri"],
                source_type=record["source_type"],
                classification=record["classification"],
                content_hash=record["content_hash"],
                raw_content=record["raw_content"] or "",
                created_at=record["created_at"],
                ingested_at=record["ingested_at"],
                version=int(record.get("version") or 1),
                review_status=record.get("review_status") or "APPROVED",
                active=record.get("active") is not False,
            )

    def list_documents(self, tenant_id: str) -> List[Document]:
        cypher = """
        MATCH (d:Document {tenant_id: $tenant_id})
        WHERE coalesce(d.active, true) = true
        RETURN d.document_id AS document_id
        ORDER BY d.ingested_at DESC
        """
        with self.conn.session() as session:
            ids = [row["document_id"] for row in session.run(cypher, {"tenant_id": tenant_id})]
        return [document for document_id in ids
                if (document := self.get_document(document_id, tenant_id)) is not None]

    def deactivate_document(self, document_id: str, tenant_id: str) -> bool:
        cypher = """
        MATCH (d:Document {tenant_id: $tenant_id, document_id: $document_id})
        SET d.active = false
        WITH d
        OPTIONAL MATCH (ev:Evidence {tenant_id: $tenant_id})-[:DERIVED_FROM]->(d)
        SET ev.active = false
        RETURN count(d) AS matched
        """
        with self.conn.session() as session:
            row = session.run(cypher, {"tenant_id": tenant_id,
                                      "document_id": document_id}).single()
        return bool(row and row["matched"])

    def get_evidence_record(self, evidence_id: str, tenant_id: str) -> Optional[ProvenanceRecord]:
        cypher = """
        MATCH (ev:Evidence {tenant_id: $tenant_id, evidence_id: $evidence_id})
              -[:DERIVED_FROM]->(d:Document {tenant_id: $tenant_id})
        WHERE coalesce(ev.active, true) = true AND coalesce(d.active, true) = true
          AND coalesce(ev.review_status, 'APPROVED') = 'APPROVED'
        RETURN ev.evidence_id AS evidence_id, ev.chunk_ref AS chunk_ref,
               ev.content AS content, ev.extraction_method AS extraction_method,
               ev.extraction_confidence AS extraction_confidence,
               ev.observed_at AS observed_at, d.document_id AS document_id,
               d.title AS document_title, d.source_uri AS source_uri,
               d.source_type AS source_type, d.classification AS classification,
               d.content_hash AS content_hash, ev.source_group AS source_group,
               d.version AS document_version
        """
        with self.conn.session() as session:
            row = session.run(cypher, {
                "tenant_id": tenant_id, "evidence_id": evidence_id}).single()
        if row is None:
            return None
        return ProvenanceRecord(
            evidence_id=row["evidence_id"], chunk_ref=row["chunk_ref"],
            content=row["content"], extraction_method=row["extraction_method"],
            extraction_confidence=float(row["extraction_confidence"]),
            observed_at=row["observed_at"], document_id=row["document_id"],
            document_title=row["document_title"], source_uri=row["source_uri"],
            source_type=row["source_type"], classification=row["classification"],
            content_hash=row["content_hash"],
            source_group=row.get("source_group") or row["evidence_id"],
            document_version=int(row.get("document_version") or 1),
        )

    def get_relation_fact(self, fact_id: str, tenant_id: str) -> Optional[RelationFact]:
        cypher = """
        MATCH (f:RelationFact {tenant_id: $tenant_id, fact_id: $fact_id})
        WHERE coalesce(f.active, true) = true
          AND coalesce(f.review_status, 'APPROVED') = 'APPROVED'
        RETURN properties(f) AS fact_properties
        """
        with self.conn.session() as session:
            record = session.run(cypher, {"tenant_id": tenant_id, "fact_id": fact_id}).single()
            if not record:
                return None
            props = record["fact_properties"]
            attrs = json.loads(props.get("attributes_json")) if props.get("attributes_json") else {}
            return RelationFact(
                fact_id=props["fact_id"],
                tenant_id=props["tenant_id"],
                relation_type=props["relation_type"],
                subject_id=props["subject_id"],
                object_id=props["object_id"],
                attributes=attrs,
                observed_at=props["observed_at"],
                valid_from=props.get("valid_from"),
                valid_to=props.get("valid_to"),
                created_at=props["created_at"],
            )

    def find_facts(
        self,
        tenant_id: str,
        subject_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        object_id: Optional[str] = None,
    ) -> List[RelationFact]:
        clauses = ["f.tenant_id = $tenant_id", "coalesce(f.active, true) = true",
                   "coalesce(f.review_status, 'APPROVED') = 'APPROVED'"]
        params: Dict[str, Any] = {"tenant_id": tenant_id}
        if subject_id:
            clauses.append("f.subject_id = $subject_id")
            params["subject_id"] = subject_id
        if relation_type:
            clauses.append("f.relation_type = $relation_type")
            params["relation_type"] = relation_type
        if object_id:
            clauses.append("f.object_id = $object_id")
            params["object_id"] = object_id

        where_str = " AND ".join(clauses)
        cypher = f"""
        MATCH (f:RelationFact)
        WHERE {where_str}
        RETURN properties(f) AS fact_properties, f.observed_at AS observed_at
        ORDER BY f.observed_at
        """
        results = []
        with self.conn.session() as session:
            for record in session.run(cypher, params):
                props = record["fact_properties"]
                attrs = json.loads(props.get("attributes_json")) if props.get("attributes_json") else {}
                results.append(
                    RelationFact(
                        fact_id=props["fact_id"],
                        tenant_id=props["tenant_id"],
                        relation_type=props["relation_type"],
                        subject_id=props["subject_id"],
                        object_id=props["object_id"],
                        attributes=attrs,
                        observed_at=props["observed_at"],
                        valid_from=props.get("valid_from"),
                        valid_to=props.get("valid_to"),
                        created_at=props["created_at"],
                    )
                )
        return results

    def get_fact_evidence(
        self,
        fact_id: str,
        tenant_id: str,
    ) -> Tuple[List[ProvenanceRecord], List[ProvenanceRecord]]:
        cypher = """
        MATCH (ev:Evidence {tenant_id: $tenant_id})-[r]->(f:RelationFact {tenant_id: $tenant_id, fact_id: $fact_id})
        MATCH (ev)-[:DERIVED_FROM]->(d:Document {tenant_id: $tenant_id})
        WHERE type(r) IN ['SUPPORTS', 'CONTRADICTS']
          AND coalesce(ev.active, true) = true AND coalesce(d.active, true) = true
          AND coalesce(ev.review_status, 'APPROVED') = 'APPROVED'
          AND coalesce(f.active, true) = true
        RETURN type(r) AS rel_type,
               ev.evidence_id AS evidence_id, ev.chunk_ref AS chunk_ref, ev.content AS content,
               ev.extraction_method AS extraction_method, ev.extraction_confidence AS extraction_confidence,
               ev.observed_at AS observed_at, d.document_id AS document_id, d.title AS document_title,
               d.source_uri AS source_uri, d.source_type AS source_type,
               d.classification AS classification, d.content_hash AS content_hash,
               ev.source_group AS source_group, d.version AS document_version
        ORDER BY ev.observed_at
        """
        supporting = []
        contradicting = []
        with self.conn.session() as session:
            for row in session.run(cypher, {"tenant_id": tenant_id, "fact_id": fact_id}):
                record = ProvenanceRecord(
                    evidence_id=row["evidence_id"],
                    chunk_ref=row["chunk_ref"],
                    content=row["content"],
                    extraction_method=row["extraction_method"],
                    extraction_confidence=float(row["extraction_confidence"]),
                    observed_at=row["observed_at"],
                    document_id=row["document_id"],
                    document_title=row["document_title"],
                    source_uri=row["source_uri"],
                    source_type=row["source_type"],
                    classification=row["classification"],
                    content_hash=row["content_hash"],
                    source_group=row.get("source_group") or row["evidence_id"],
                    document_version=int(row.get("document_version") or 1),
                )
                if row["rel_type"] == "SUPPORTS":
                    supporting.append(record)
                elif row["rel_type"] == "CONTRADICTS":
                    contradicting.append(record)
        return supporting, contradicting

    def get_provenance_chain(self, fact_id: str, tenant_id: str) -> Optional[ProvenanceChain]:
        fact = self.get_relation_fact(fact_id, tenant_id)
        if not fact:
            return None
        subject = self.get_entity(fact.subject_id, tenant_id)
        object_entity = self.get_entity(fact.object_id, tenant_id)
        supporting, contradicting = self.get_fact_evidence(fact_id, tenant_id)
        return ProvenanceChain(
            fact=fact,
            subject=subject,
            object=object_entity,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
        )

    def get_multi_hop_relationships(
        self,
        start_entity_id: str,
        tenant_id: str,
        max_hops: int = 2,
    ) -> List[TraversalPath]:
        hops = max(1, min(max_hops, 2))
        results: List[TraversalPath] = []

        if hops == 1:
            cypher = """
            MATCH (e1:Entity {tenant_id: $tenant_id, entity_id: $start_id})-[:SUBJECT_OF]->(f1:RelationFact {tenant_id: $tenant_id})-[:OBJECT]->(t1:Entity {tenant_id: $tenant_id})
            WHERE e1 <> t1
            RETURN 1 AS hops,
                   e1.entity_id AS e1_id, e1.canonical_name AS e1_name, e1.entity_type AS e1_type,
                   f1.fact_id AS f1_id, f1.relation_type AS f1_rel,
                   t1.entity_id AS t1_id, t1.canonical_name AS t1_name, t1.entity_type AS t1_type,
                   null AS f2_id, null AS f2_rel,
                   null AS t2_id, null AS t2_name, null AS t2_type
            """
        else:
            cypher = """
            MATCH (e1:Entity {tenant_id: $tenant_id, entity_id: $start_id})-[:SUBJECT_OF]->(f1:RelationFact {tenant_id: $tenant_id})-[:OBJECT]->(t1:Entity {tenant_id: $tenant_id})
            WHERE e1 <> t1
            RETURN 1 AS hops,
                   e1.entity_id AS e1_id, e1.canonical_name AS e1_name, e1.entity_type AS e1_type,
                   f1.fact_id AS f1_id, f1.relation_type AS f1_rel,
                   t1.entity_id AS t1_id, t1.canonical_name AS t1_name, t1.entity_type AS t1_type,
                   null AS f2_id, null AS f2_rel,
                   null AS t2_id, null AS t2_name, null AS t2_type
            UNION ALL
            MATCH (e1:Entity {tenant_id: $tenant_id, entity_id: $start_id})-[:SUBJECT_OF]->(f1:RelationFact {tenant_id: $tenant_id})-[:OBJECT]->(t1:Entity {tenant_id: $tenant_id})-[:SUBJECT_OF]->(f2:RelationFact {tenant_id: $tenant_id})-[:OBJECT]->(t2:Entity {tenant_id: $tenant_id})
            WHERE e1 <> t1 AND t1 <> t2 AND e1 <> t2
            RETURN 2 AS hops,
                   e1.entity_id AS e1_id, e1.canonical_name AS e1_name, e1.entity_type AS e1_type,
                   f1.fact_id AS f1_id, f1.relation_type AS f1_rel,
                   t1.entity_id AS t1_id, t1.canonical_name AS t1_name, t1.entity_type AS t1_type,
                   f2.fact_id AS f2_id, f2.relation_type AS f2_rel,
                   t2.entity_id AS t2_id, t2.canonical_name AS t2_name, t2.entity_type AS t2_type
            """

        with self.conn.session() as session:
            for r in session.run(cypher, {"tenant_id": tenant_id, "start_id": start_entity_id}):
                step = [
                    {"id": r["e1_id"], "type": r["e1_type"], "name": r["e1_name"], "labels": ["Entity"]},
                    {"id": r["f1_id"], "type": r["f1_rel"], "name": r["f1_rel"], "labels": ["RelationFact"]},
                    {"id": r["t1_id"], "type": r["t1_type"], "name": r["t1_name"], "labels": ["Entity"]},
                ]
                if r.get("hops") == 2 and r.get("f2_id") and r.get("t2_id"):
                    step.extend([
                        {"id": r["f2_id"], "type": r["f2_rel"], "name": r["f2_rel"], "labels": ["RelationFact"]},
                        {"id": r["t2_id"], "type": r["t2_type"], "name": r["t2_name"], "labels": ["Entity"]},
                    ])
                    results.append(TraversalPath(path=step, hops=2))
                else:
                    results.append(TraversalPath(path=step, hops=1))

        results.sort(key=lambda tp: (tp.hops, [node["id"] for node in tp.path]))
        return results


class InMemoryGraphRepository(BaseGraphRepository):
    """Deterministic, pure-Python in-memory graph repository.

    Provides identical interfaces, constraints, and tenant-scoped query semantics
    without requiring an active Neo4j database service.
    """

    def __init__(self) -> None:
        self.entities: Dict[Tuple[str, str], Entity] = {}  # (tenant_id, entity_id) -> Entity
        self.documents: Dict[Tuple[str, str], Document] = {}  # (tenant_id, document_id) -> Document
        self.evidence: Dict[Tuple[str, str], Evidence] = {}  # (tenant_id, evidence_id) -> Evidence
        self.facts: Dict[Tuple[str, str], RelationFact] = {}  # (tenant_id, fact_id) -> RelationFact
        # (tenant_id, fact_id, link_type) -> list of evidence_ids
        self.fact_evidence_links: Dict[Tuple[str, str, EvidenceType], List[str]] = {}

    def init_schema_constraints(self) -> None:
        pass  # In-memory dictionary keys enforce uniqueness by construction

    def upsert_entity(self, entity: Entity) -> None:
        key = (entity.tenant_id, entity.entity_id)
        self.entities[key] = entity

    def upsert_document(self, document: Document) -> None:
        key = (document.tenant_id, document.document_id)
        self.documents[key] = document

    def upsert_evidence(self, evidence: Evidence) -> None:
        doc_key = (evidence.tenant_id, evidence.document_id)
        if doc_key not in self.documents:
            raise ValueError(
                f"Cannot create evidence {evidence.evidence_id}: Referenced source document {evidence.document_id} does not exist in tenant {evidence.tenant_id}"
            )
        key = (evidence.tenant_id, evidence.evidence_id)
        self.evidence[key] = evidence

    def upsert_relation_fact(self, fact: RelationFact) -> None:
        s_key = (fact.tenant_id, fact.subject_id)
        o_key = (fact.tenant_id, fact.object_id)
        if s_key not in self.entities:
            raise ValueError(f"Subject entity '{fact.subject_id}' does not exist in tenant '{fact.tenant_id}'")
        if o_key not in self.entities:
            raise ValueError(f"Object entity '{fact.object_id}' does not exist in tenant '{fact.tenant_id}'")
        key = (fact.tenant_id, fact.fact_id)
        self.facts[key] = fact

    def link_evidence_to_fact(
        self,
        evidence_id: str,
        fact_id: str,
        link_type: EvidenceType,
        tenant_id: str,
    ) -> None:
        ev_key = (tenant_id, evidence_id)
        fact_key = (tenant_id, fact_id)
        if ev_key not in self.evidence:
            raise ValueError(f"Evidence '{evidence_id}' does not exist in tenant '{tenant_id}'")
        if fact_key not in self.facts:
            raise ValueError(f"RelationFact '{fact_id}' does not exist in tenant '{tenant_id}'")

        key = (tenant_id, fact_id, link_type)
        if key not in self.fact_evidence_links:
            self.fact_evidence_links[key] = []
        if evidence_id not in self.fact_evidence_links[key]:
            self.fact_evidence_links[key].append(evidence_id)

    def get_entity(self, entity_id: str, tenant_id: str) -> Optional[Entity]:
        return self.entities.get((tenant_id, entity_id))

    def list_entities(
        self,
        tenant_id: str,
        entity_type: Optional[str] = None,
    ) -> List[Entity]:
        res = [
            e for (t, _), e in self.entities.items()
            if t == tenant_id and (entity_type is None or e.entity_type == entity_type)
        ]
        return sorted(res, key=lambda e: e.canonical_name)

    def get_document(self, document_id: str, tenant_id: str) -> Optional[Document]:
        document = self.documents.get((tenant_id, document_id))
        return document if document is not None and document.active else None

    def list_documents(self, tenant_id: str) -> List[Document]:
        return sorted((document for (scope, _), document in self.documents.items()
                       if scope == tenant_id and document.active),
                      key=lambda item: item.ingested_at, reverse=True)

    def deactivate_document(self, document_id: str, tenant_id: str) -> bool:
        document = self.documents.get((tenant_id, document_id))
        if document is None:
            return False
        self.documents[(tenant_id, document_id)] = document.model_copy(update={"active": False})
        for key, evidence in tuple(self.evidence.items()):
            if key[0] == tenant_id and evidence.document_id == document_id:
                self.evidence[key] = evidence.model_copy(update={"active": False})
        return True

    def get_evidence_record(self, evidence_id: str, tenant_id: str) -> Optional[ProvenanceRecord]:
        evidence = self.evidence.get((tenant_id, evidence_id))
        if evidence is None or not evidence.active:
            return None
        document = self.documents.get((tenant_id, evidence.document_id))
        if document is None or not document.active:
            return None
        return ProvenanceRecord(
            evidence_id=evidence.evidence_id, chunk_ref=evidence.chunk_ref,
            content=evidence.content, extraction_method=evidence.extraction_method,
            extraction_confidence=evidence.extraction_confidence,
            observed_at=evidence.observed_at, document_id=document.document_id,
            document_title=document.title, source_uri=document.source_uri,
            source_type=document.source_type, classification=document.classification,
            content_hash=document.content_hash,
            source_group=evidence.source_group or evidence.evidence_id,
            document_version=document.version,
        )

    def get_relation_fact(self, fact_id: str, tenant_id: str) -> Optional[RelationFact]:
        fact = self.facts.get((tenant_id, fact_id))
        return fact if fact is not None and fact.active and fact.review_status == "APPROVED" else None

    def find_facts(
        self,
        tenant_id: str,
        subject_id: Optional[str] = None,
        relation_type: Optional[str] = None,
        object_id: Optional[str] = None,
    ) -> List[RelationFact]:
        results = []
        for (t, _), f in self.facts.items():
            if t != tenant_id:
                continue
            if not f.active or f.review_status != "APPROVED":
                continue
            if subject_id and f.subject_id != subject_id:
                continue
            if relation_type and f.relation_type != relation_type:
                continue
            if object_id and f.object_id != object_id:
                continue
            results.append(f)
        return sorted(results, key=lambda f: f.observed_at)

    def get_fact_evidence(
        self,
        fact_id: str,
        tenant_id: str,
    ) -> Tuple[List[ProvenanceRecord], List[ProvenanceRecord]]:
        supporting = []
        contradicting = []

        sup_ids = self.fact_evidence_links.get((tenant_id, fact_id, EvidenceType.SUPPORTS), [])
        for eid in sup_ids:
            ev = self.evidence.get((tenant_id, eid))
            if ev and ev.active and ev.review_status == "APPROVED":
                doc = self.documents.get((tenant_id, ev.document_id))
                if doc and doc.active:
                    supporting.append(
                        ProvenanceRecord(
                            evidence_id=ev.evidence_id,
                            chunk_ref=ev.chunk_ref,
                            content=ev.content,
                            extraction_method=ev.extraction_method,
                            extraction_confidence=ev.extraction_confidence,
                            observed_at=ev.observed_at,
                            document_id=doc.document_id,
                            document_title=doc.title,
                            source_uri=doc.source_uri,
                            source_type=doc.source_type,
                            classification=doc.classification,
                            content_hash=doc.content_hash,
                            source_group=ev.source_group or ev.evidence_id,
                            document_version=doc.version,
                        )
                    )

        con_ids = self.fact_evidence_links.get((tenant_id, fact_id, EvidenceType.CONTRADICTS), [])
        for eid in con_ids:
            ev = self.evidence.get((tenant_id, eid))
            if ev and ev.active and ev.review_status == "APPROVED":
                doc = self.documents.get((tenant_id, ev.document_id))
                if doc and doc.active:
                    contradicting.append(
                        ProvenanceRecord(
                            evidence_id=ev.evidence_id,
                            chunk_ref=ev.chunk_ref,
                            content=ev.content,
                            extraction_method=ev.extraction_method,
                            extraction_confidence=ev.extraction_confidence,
                            observed_at=ev.observed_at,
                            document_id=doc.document_id,
                            document_title=doc.title,
                            source_uri=doc.source_uri,
                            source_type=doc.source_type,
                            classification=doc.classification,
                            content_hash=doc.content_hash,
                            source_group=ev.source_group or ev.evidence_id,
                            document_version=doc.version,
                        )
                    )

        return supporting, contradicting

    def get_provenance_chain(self, fact_id: str, tenant_id: str) -> Optional[ProvenanceChain]:
        fact = self.get_relation_fact(fact_id, tenant_id)
        if not fact:
            return None
        subject = self.get_entity(fact.subject_id, tenant_id)
        object_entity = self.get_entity(fact.object_id, tenant_id)
        supporting, contradicting = self.get_fact_evidence(fact_id, tenant_id)
        return ProvenanceChain(
            fact=fact,
            subject=subject,
            object=object_entity,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
        )

    def get_multi_hop_relationships(
        self,
        start_entity_id: str,
        tenant_id: str,
        max_hops: int = 2,
    ) -> List[TraversalPath]:
        hops = max(1, min(max_hops, 2))
        paths: List[TraversalPath] = []
        start_entity = self.get_entity(start_entity_id, tenant_id)
        if not start_entity:
            return paths

        # 1-hop facts: (start) -> f1 -> target1
        direct_facts = self.find_facts(tenant_id, subject_id=start_entity_id)
        for f1 in direct_facts:
            target1 = self.get_entity(f1.object_id, tenant_id)
            if target1 and target1.entity_id != start_entity_id:
                step1 = [
                    {"id": start_entity.entity_id, "type": start_entity.entity_type, "name": start_entity.canonical_name, "labels": ["Entity"]},
                    {"id": f1.fact_id, "type": f1.relation_type, "name": f1.relation_type, "labels": ["RelationFact"]},
                    {"id": target1.entity_id, "type": target1.entity_type, "name": target1.canonical_name, "labels": ["Entity"]},
                ]
                paths.append(TraversalPath(path=step1, hops=1))

                if hops >= 2:
                    second_facts = self.find_facts(tenant_id, subject_id=target1.entity_id)
                    for f2 in second_facts:
                        target2 = self.get_entity(f2.object_id, tenant_id)
                        if target2 and target2.entity_id != start_entity_id and target2.entity_id != target1.entity_id:
                            step2 = step1 + [
                                {"id": f2.fact_id, "type": f2.relation_type, "name": f2.relation_type, "labels": ["RelationFact"]},
                                {"id": target2.entity_id, "type": target2.entity_type, "name": target2.canonical_name, "labels": ["Entity"]},
                            ]
                            paths.append(TraversalPath(path=step2, hops=2))

        paths.sort(key=lambda tp: (tp.hops, [node["id"] for node in tp.path]))
        return paths
