"""Conservative adapter from retrieved evidence to registered POMDP observations."""
from __future__ import annotations

from .schemas import EvidenceObservation, GraphInvestigationResult, ObservationToken, ToolStatus


class UnsafeToolResult(ValueError):
    """Raised when an operational outcome must not enter Bayes' theorem."""


def adapt_result(
    planner_action: str,
    result: GraphInvestigationResult,
    *,
    seen_evidence_ids: set[str],
    seen_document_ids: set[str],
) -> EvidenceObservation:
    operational = {
        ToolStatus.UNAUTHORIZED, ToolStatus.DATABASE_UNAVAILABLE, ToolStatus.INVALID_REQUEST,
    }
    if result.status in operational:
        raise UnsafeToolResult(result.error or result.status.value)

    evidence_ids = result.evidence_ids
    document_ids = result.document_ids
    duplicate = bool(set(evidence_ids) & seen_evidence_ids or set(document_ids) & seen_document_ids)
    if duplicate:
        token = ObservationToken.DUPLICATE
    elif result.status == ToolStatus.PROVENANCE_FAILURE:
        token = ObservationToken.HASH_MISMATCH
    elif result.status in {ToolStatus.MISSING_RECORD, ToolStatus.NO_EVIDENCE}:
        token = ObservationToken.NOT_FOUND
    elif result.supporting_evidence and result.contradicting_evidence:
        token = ObservationToken.CONFLICTED
    elif result.contradicting_evidence:
        token = ObservationToken.CONTRADICTED
    elif result.supporting_evidence or result.paths:
        token = ObservationToken.SUPPORTED
    else:
        token = ObservationToken.NOT_FOUND

    return EvidenceObservation(
        action_name=planner_action,
        observation_token=token,
        source_fact_ids=sorted({f.fact_id for f in result.facts}),
        source_evidence_ids=evidence_ids,
        source_document_ids=document_ids,
        source_signal_groups=sorted({
            evidence.source_group or evidence.evidence_id
            for evidence in result.supporting_evidence + result.contradicting_evidence
        }),
        evidence_status=result.status,
        provenance_verified=result.provenance_verified,
        is_duplicate=duplicate,
    )
