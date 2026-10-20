"""Repeatable local Implementation 14 acceptance pilot (no external inference)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from time import perf_counter

from sentinel_pomdp.domains import DomainAction, DomainPack, DomainPackService, DomainPackStatus
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.ingestion import DatasetConfiguration, EnterpriseDataService, LocalDocumentStore, ReviewAction
from sentinel_pomdp.intelligence import DeterministicFakeLLM, InvestigationIntelligenceService


def probability_rows():
    return {
        "delayed": {"EVIDENCE_SUPPORTED": .90, "EVIDENCE_CONFLICTED": .02,
                    "EVIDENCE_CONTRADICTED": .02, "EVIDENCE_NOT_FOUND": .04,
                    "DUPLICATE_INFORMATION": .01, "SOURCE_HASH_MISMATCH": .01},
        "on_time": {"EVIDENCE_SUPPORTED": .10, "EVIDENCE_CONFLICTED": .05,
                    "EVIDENCE_CONTRADICTED": .60, "EVIDENCE_NOT_FOUND": .23,
                    "DUPLICATE_INFORMATION": .01, "SOURCE_HASH_MISMATCH": .01},
    }


def main() -> None:
    repository = InMemoryGraphRepository()
    with tempfile.TemporaryDirectory(prefix="sentinel-i14-") as folder:
        store = LocalDocumentStore(Path(folder))
        ingestion = EnterpriseDataService(store, repository)
        ingestion.configure_dataset("pilot", DatasetConfiguration(
            dataset_id="delivery", name="Delivery records",
            field_mapping={"purchase_order": "po", "expected_date": "expected",
                           "actual_date": "actual"}))
        started = perf_counter()
        ingestion.upload("pilot", dataset_id="delivery", filename="expected.csv",
                         content=b"po,expected,actual\nPO-PILOT-14,2026-10-01,\n")
        ingestion.upload("pilot", dataset_id="delivery", filename="actual.csv",
                         content=b"po,expected,actual\nPO-PILOT-14,,2026-10-04\n")
        candidate = store.list_candidates("pilot")[0]
        approved = ingestion.review(
            "pilot", candidate.candidate_id, ReviewAction.APPROVE, "pilot-reviewer")
        ingestion_ms = (perf_counter() - started) * 1000
        packs = DomainPackService(store, repository)
        packs.save("pilot", DomainPack(
            domain_id="delivery", name="Delivery delay", claim_type="shipment_timeliness",
            hypotheses=["delayed", "on_time"], prior={"delayed": .55, "on_time": .45},
            actions=[DomainAction(action_id="inspect", cost=.08,
                                  relation_hypotheses={"EXPERIENCED_DELAY": "delayed"})],
            observation_model={"inspect": probability_rows()}, answer_threshold=.70,
            minimum_independent_sources=2, status=DomainPackStatus.APPROVED,
            model_version="pilot-review-v1", calibration_note="Acceptance pilot only.",
            approved_by="pilot-reviewer"))
        started = perf_counter()
        scenario = packs.build_scenario("pilot", "delivery", "Was PO-PILOT-14 delayed?")
        response = InvestigationIntelligenceService(
            repository, DeterministicFakeLLM()).investigate_scenario(
                "Was PO-PILOT-14 delayed?", "pilot", scenario)
        reasoning_ms = (perf_counter() - started) * 1000
        print(json.dumps({
            "decision": response.decision,
            "selected_hypothesis": response.selected_hypothesis,
            "posterior": response.final_belief,
            "documents": len(response.document_ids),
            "supporting_evidence": len(response.supporting_evidence_ids),
            "fact_id": approved.graph_fact_id,
            "model_version": response.investigation["metadata"]["domain_model_version"],
            "ingestion_review_ms": round(ingestion_ms, 3),
            "reasoning_ms": round(reasoning_ms, 3),
            "external_llm_calls": 0,
        }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
