"""Safe graph tools implemented solely through the repository contract."""
from __future__ import annotations

from time import perf_counter

from sentinel_pomdp.graph.ingestion import ALLOWED_RELATION_TYPES
from sentinel_pomdp.graph.provenance import validate_evidence_chain
from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.graph.schemas import FactProvenanceStatus

from .schemas import (
    GraphInvestigationRequest,
    GraphInvestigationResult,
    InvestigationAction,
    ToolStatus,
)


class GraphInvestigationTools:
    """A small read-only allowlist; no query-language input is accepted."""

    def __init__(self, repository: BaseGraphRepository, *, costs: dict[InvestigationAction, float] | None = None) -> None:
        self.repository = repository
        self.costs = costs or {
            InvestigationAction.FACT_EVIDENCE: 0.08,
            InvestigationAction.ENTITY_RELATIONSHIPS: 0.12,
            InvestigationAction.COMPETING_CLAIMS: 0.15,
        }

    def execute(self, request: GraphInvestigationRequest, *, authorized_tenant_id: str) -> GraphInvestigationResult:
        started = perf_counter()
        base = dict(action_name=request.action_name, target_id=request.target_id,
                    cost=self.costs[request.action_name])
        if request.tenant_id != authorized_tenant_id:
            return GraphInvestigationResult(**base, status=ToolStatus.UNAUTHORIZED,
                                             error="request tenant is outside the authorized session scope",
                                             latency_ms=(perf_counter() - started) * 1000)
        unknown = set(request.allowed_relation_types) - ALLOWED_RELATION_TYPES
        if unknown:
            return GraphInvestigationResult(**base, status=ToolStatus.INVALID_REQUEST,
                                             error=f"unsupported relation types: {sorted(unknown)}",
                                             latency_ms=(perf_counter() - started) * 1000)
        try:
            if request.action_name == InvestigationAction.FACT_EVIDENCE:
                result = self._fact_evidence(request, base)
            elif request.action_name == InvestigationAction.ENTITY_RELATIONSHIPS:
                result = self._entity_relationships(request, base)
            else:
                result = self._competing_claims(request, base)
        except Exception:  # repository/driver failures are operational, never negative evidence
            result = GraphInvestigationResult(**base, status=ToolStatus.DATABASE_UNAVAILABLE,
                                                error="database operation failed")
        result.latency_ms = (perf_counter() - started) * 1000
        return result

    def _fact_evidence(self, request: GraphInvestigationRequest, base: dict) -> GraphInvestigationResult:
        validation = validate_evidence_chain(self.repository, request.target_id, request.tenant_id)
        if validation.chain is None:
            return GraphInvestigationResult(**base, status=ToolStatus.MISSING_RECORD)
        chain = validation.chain
        status = ToolStatus.EVIDENCE_FOUND
        if validation.hash_mismatches:
            status = ToolStatus.PROVENANCE_FAILURE
        elif validation.status == FactProvenanceStatus.CONFLICTED:
            status = ToolStatus.CONFLICTING_EVIDENCE
        elif validation.status == FactProvenanceStatus.UNEVIDENCED:
            status = ToolStatus.NO_EVIDENCE
        return GraphInvestigationResult(
            **base, status=status, facts=[chain.fact],
            supporting_evidence=chain.supporting_evidence,
            contradicting_evidence=chain.contradicting_evidence,
            provenance_verified=validation.all_documents_verified,
            hash_mismatches=validation.hash_mismatches,
        )

    def _entity_relationships(self, request: GraphInvestigationRequest, base: dict) -> GraphInvestigationResult:
        if self.repository.get_entity(request.target_id, request.tenant_id) is None:
            return GraphInvestigationResult(**base, status=ToolStatus.MISSING_RECORD)
        paths = self.repository.get_multi_hop_relationships(
            request.target_id, request.tenant_id, request.max_depth
        )
        if request.allowed_relation_types:
            paths = [p for p in paths if all(
                node.get("type") in request.allowed_relation_types
                for node in p.path if "RelationFact" in node.get("labels", [])
            )]
        paths = paths[:request.max_results]
        fact_ids = sorted({node["id"] for p in paths for node in p.path
                           if "RelationFact" in node.get("labels", [])})
        facts = [f for fid in fact_ids if (f := self.repository.get_relation_fact(fid, request.tenant_id))]
        return GraphInvestigationResult(**base, status=(ToolStatus.EVIDENCE_FOUND if paths else ToolStatus.NO_EVIDENCE),
                                         facts=facts, paths=paths, provenance_verified=bool(paths))

    def _competing_claims(self, request: GraphInvestigationRequest, base: dict) -> GraphInvestigationResult:
        if self.repository.get_entity(request.target_id, request.tenant_id) is None:
            return GraphInvestigationResult(**base, status=ToolStatus.MISSING_RECORD)
        facts = self.repository.find_facts(request.tenant_id, subject_id=request.target_id)
        if request.allowed_relation_types:
            facts = [f for f in facts if f.relation_type in request.allowed_relation_types]
        facts = facts[:request.max_results]
        supporting, contradicting, verified, mismatches = [], [], True, []
        for fact in facts:
            check = validate_evidence_chain(self.repository, fact.fact_id, request.tenant_id)
            if check.chain:
                supporting.extend(check.chain.supporting_evidence)
                contradicting.extend(check.chain.contradicting_evidence)
            verified = verified and check.all_documents_verified
            mismatches.extend(check.hash_mismatches)
        if mismatches:
            status = ToolStatus.PROVENANCE_FAILURE
        elif supporting and contradicting:
            status = ToolStatus.CONFLICTING_EVIDENCE
        elif supporting or contradicting:
            status = ToolStatus.EVIDENCE_FOUND
        else:
            status = ToolStatus.NO_EVIDENCE
        return GraphInvestigationResult(**base, status=status, facts=facts,
                                         supporting_evidence=supporting,
                                         contradicting_evidence=contradicting,
                                         provenance_verified=verified and bool(facts),
                                         hash_mismatches=mismatches)
