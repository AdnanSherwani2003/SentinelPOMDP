"""Evidence gate kept separate from posterior confidence and planning."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import EvidenceObservation, EvidenceVerdict, ObservationToken


class EvidencePolicy(BaseModel):
    """Conservative domain policy: a hypothesis needs a specified supported fact."""

    required_fact_ids: dict[str, set[str]]
    required_evidence_ids: dict[str, set[str]] = Field(default_factory=dict)
    minimum_distinct_documents: int = Field(default=1, ge=1)
    minimum_independent_sources: int = Field(default=1, ge=1)

    def evaluate(self, hypothesis: str | None, observations: list[EvidenceObservation]) -> EvidenceVerdict:
        if not hypothesis:
            fact_ids = sorted({f for o in observations for f in o.source_fact_ids})
            evidence_ids = sorted({e for o in observations for e in o.source_evidence_ids})
            document_ids = sorted({d for o in observations for d in o.source_document_ids})
            unsafe = any(o.observation_token in {ObservationToken.CONFLICTED,
                         ObservationToken.CONTRADICTED, ObservationToken.HASH_MISMATCH}
                         for o in observations)
            status = "CONFLICTED" if unsafe else ("INSUFFICIENT" if observations else "NO_CANDIDATE")
            reason = ("No mathematical answer was selected; contradictory or invalid evidence is preserved."
                      if unsafe else "No mathematical answer candidate was selected.")
            return EvidenceVerdict(sufficient=False, fact_ids=fact_ids,
                                   evidence_ids=evidence_ids, document_ids=document_ids,
                                   provenance_status=status, reason=reason)
        required = self.required_fact_ids.get(hypothesis, set())
        required_evidence = self.required_evidence_ids.get(hypothesis, set())
        relevant = [o for o in observations if required.intersection(o.source_fact_ids)]
        fact_ids = sorted({f for o in relevant for f in o.source_fact_ids if f in required})
        evidence_ids = sorted({e for o in relevant for e in o.source_evidence_ids})
        document_ids = sorted({d for o in relevant for d in o.source_document_ids})
        source_groups = sorted({g for o in relevant for g in o.source_signal_groups})
        if not required:
            reason, status = "No evidence requirement is registered for this hypothesis.", "UNREGISTERED"
        elif not required.issubset(fact_ids):
            reason, status = "Not all registered required facts have verified support.", "INSUFFICIENT"
        elif any(o.observation_token in {ObservationToken.CONFLICTED, ObservationToken.CONTRADICTED,
                                         ObservationToken.HASH_MISMATCH} for o in relevant):
            reason, status = "Required evidence is contradicted, conflicting, or failed integrity validation.", "CONFLICTED"
        elif not relevant or not all(o.provenance_verified for o in relevant):
            reason, status = "Required traceable evidence was not retrieved and verified.", "INSUFFICIENT"
        elif not any(o.observation_token == ObservationToken.SUPPORTED for o in relevant):
            reason, status = "The required fact was not supported by retrieved evidence.", "INSUFFICIENT"
        elif required_evidence and not required_evidence.issubset(evidence_ids):
            reason, status = "The retrieved sources do not contain the claim-specific evidence required for this answer.", "IRRELEVANT_SUPPORT"
        elif len(document_ids) < self.minimum_distinct_documents:
            reason, status = "Too few distinct source documents satisfy the evidence policy.", "INSUFFICIENT"
        elif len(source_groups) < self.minimum_independent_sources:
            reason, status = "Too few independent source groups satisfy the evidence policy.", "INSUFFICIENT"
        else:
            return EvidenceVerdict(sufficient=True, hypothesis=hypothesis, fact_ids=fact_ids,
                                   evidence_ids=evidence_ids, document_ids=document_ids,
                                   independent_source_groups=source_groups,
                                   provenance_status="VERIFIED_SUPPORTED",
                                   reason="Mathematical confidence and traceable evidence requirements are satisfied.")
        return EvidenceVerdict(sufficient=False, hypothesis=hypothesis, fact_ids=fact_ids,
                               evidence_ids=evidence_ids, document_ids=document_ids,
                               independent_source_groups=source_groups,
                               provenance_status=status, reason=reason)
