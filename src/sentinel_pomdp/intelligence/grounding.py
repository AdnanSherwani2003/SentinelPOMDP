"""Deterministic evidence classification, draft validation, and safe fallback prose."""
from __future__ import annotations

from dataclasses import dataclass

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.investigation.schemas import InvestigationOutcome

from .schemas import GroundedExplanationDraft


@dataclass(frozen=True)
class EvidenceReferences:
    supporting_ids: tuple[str, ...]
    contradicting_ids: tuple[str, ...]
    document_ids: tuple[str, ...]


def collect_evidence_references(repository: BaseGraphRepository, outcome: InvestigationOutcome,
                                tenant_id: str) -> EvidenceReferences:
    supporting: set[str] = set()
    contradicting: set[str] = set()
    documents: set[str] = set()
    allowed = set(outcome.evidence_verdict.evidence_ids)
    for fact_id in outcome.evidence_verdict.fact_ids:
        support, contradict = repository.get_fact_evidence(fact_id, tenant_id)
        for record in support:
            if record.evidence_id in allowed:
                supporting.add(record.evidence_id)
                documents.add(record.document_id)
        for record in contradict:
            if record.evidence_id in allowed:
                contradicting.add(record.evidence_id)
                documents.add(record.document_id)
    # Never expand beyond the evidence gate's final allow-list.
    documents.intersection_update(outcome.evidence_verdict.document_ids)
    return EvidenceReferences(tuple(sorted(supporting)), tuple(sorted(contradicting)),
                              tuple(sorted(documents)))


def explanation_payload(outcome: InvestigationOutcome, refs: EvidenceReferences) -> dict:
    limitation = outcome.termination_reason if outcome.decision == "ABSTAIN" else None
    return {
        "decision": outcome.decision,
        "selected_hypothesis": outcome.selected_hypothesis or "",
        "final_belief": [
            {"hypothesis": key, "probability": value}
            for key, value in sorted(outcome.final_belief.items())
        ],
        "summary": "Render a concise explanation from these fields.",
        "fact_ids": sorted(outcome.evidence_verdict.fact_ids),
        "supporting_evidence_ids": list(refs.supporting_ids),
        "contradicting_evidence_ids": list(refs.contradicting_ids),
        "document_ids": list(outcome.evidence_verdict.document_ids),
        "provenance_status": outcome.evidence_verdict.provenance_status,
        "limitation": limitation or "",
    }


def validate_explanation(draft: GroundedExplanationDraft, outcome: InvestigationOutcome,
                         refs: EvidenceReferences) -> list[str]:
    errors: list[str] = []
    if draft.decision != outcome.decision:
        errors.append("decision changed")
    if draft.selected_hypothesis != (outcome.selected_hypothesis or ""):
        errors.append("selected hypothesis changed")
    draft_belief = {entry.hypothesis: entry.probability for entry in draft.final_belief}
    if (len(draft_belief) != len(draft.final_belief)
            or set(draft_belief) != set(outcome.final_belief)
            or any(abs(draft_belief.get(k, -1) - v) > 1e-9
                   for k, v in outcome.final_belief.items())):
        errors.append("posterior changed")
    if draft.fact_ids != sorted(outcome.evidence_verdict.fact_ids):
        errors.append("fact reference omitted or fabricated")
    if draft.supporting_evidence_ids != list(refs.supporting_ids):
        errors.append("supporting evidence omitted or fabricated")
    if draft.contradicting_evidence_ids != list(refs.contradicting_ids):
        errors.append("contradicting evidence omitted or fabricated")
    if draft.document_ids != sorted(outcome.evidence_verdict.document_ids):
        errors.append("document citation omitted or fabricated")
    if draft.provenance_status != outcome.evidence_verdict.provenance_status:
        errors.append("provenance status changed")
    if outcome.decision == "ABSTAIN" and not draft.limitation:
        errors.append("abstention limitation omitted")
    if outcome.decision == "ANSWER" and draft.limitation:
        errors.append("unsupported limitation added")
    text = draft.summary.casefold()
    if outcome.decision == "ABSTAIN":
        if not text.startswith("abstain") or (draft.limitation or "").casefold() not in text:
            errors.append("abstention not clearly disclosed in prose")
        dangerous = ("answer:", "is verified", "is confirmed", "is proven", "caused the entire")
        if any(phrase in text for phrase in dangerous):
            errors.append("prose asserts an unsupported conclusion")
    elif not text.startswith("answer:") or (outcome.selected_hypothesis or "").casefold() not in text:
        errors.append("answer is not clearly tied to the selected hypothesis")
    if refs.contradicting_ids and "contradict" not in text:
        errors.append("contradiction omitted from prose")
    for reference in (*outcome.evidence_verdict.fact_ids, *refs.supporting_ids,
                      *refs.contradicting_ids, *outcome.evidence_verdict.document_ids):
        if reference.casefold() not in text:
            errors.append(f"prose omitted reference {reference}")
    return errors


def deterministic_explanation(outcome: InvestigationOutcome, refs: EvidenceReferences) -> GroundedExplanationDraft:
    posterior = ", ".join(f"{key}={value:.3f}" for key, value in sorted(outcome.final_belief.items()))
    support = ", ".join(refs.supporting_ids) or "none"
    contradict = ", ".join(refs.contradicting_ids) or "none"
    facts = ", ".join(sorted(outcome.evidence_verdict.fact_ids)) or "none"
    documents = ", ".join(sorted(outcome.evidence_verdict.document_ids)) or "none"
    if outcome.decision == "ANSWER":
        summary = (f"Answer: {outcome.selected_hypothesis}. Posterior: {posterior}. "
                   f"Facts: {facts}. Supporting evidence: {support}; contradicting evidence: {contradict}. "
                   f"Source documents: {documents}. Provenance: {outcome.evidence_verdict.provenance_status}.")
        limitation = None
    else:
        summary = (f"Abstained. Posterior: {posterior}. Facts: {facts}. Supporting evidence: {support}; "
                   f"contradicting evidence: {contradict}. Source documents: {documents}. "
                   f"Provenance: {outcome.evidence_verdict.provenance_status}. "
                   f"Limitation: {outcome.termination_reason}")
        limitation = outcome.termination_reason
    return GroundedExplanationDraft(
        decision=outcome.decision, selected_hypothesis=outcome.selected_hypothesis or "",
        final_belief=[{"hypothesis": key, "probability": value}
                      for key, value in sorted(outcome.final_belief.items())], summary=summary,
        fact_ids=sorted(outcome.evidence_verdict.fact_ids),
        supporting_evidence_ids=list(refs.supporting_ids),
        contradicting_evidence_ids=list(refs.contradicting_ids),
        document_ids=sorted(outcome.evidence_verdict.document_ids),
        provenance_status=outcome.evidence_verdict.provenance_status, limitation=limitation or "")
