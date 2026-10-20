"""Deterministic evaluation of intent accuracy, grounding, parity, and overhead."""
from statistics import mean
from time import perf_counter

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.intelligence import DeterministicFakeLLM, InvestigationIntelligenceService
from sentinel_pomdp.investigation import (
    build_scenario_planner, conflicting_delivery_scenario, missing_evidence_scenario,
    multi_investigation_scenario, supplier_delay_scenario, supplier_shipment_delay_scenario,
)
from sentinel_pomdp.orchestration import run_langgraph_investigation

CASES = [
    ("Was Supplier A's shipment late?", "supplier_a_shipment_delay", "sup_a", "SHIPMENT_TIMELINESS"),
    ("Did the shipment from supplier A arrive late?", "supplier_a_shipment_delay", "sup_a", "SHIPMENT_TIMELINESS"),
    ("Did Supplier A cause the production delay?", "supplier_delay_causal_attribution", "sup_a", "CAUSAL_ATTRIBUTION"),
    ("Is supplier A responsible for causing this delay?", "supplier_delay_causal_attribution", "sup_a", "CAUSAL_ATTRIBUTION"),
    ("Did Supplier B deliver on time?", "supplier_b_conflicting_delivery", "sup_b", "DELIVERY_TIMELINESS"),
    ("Is Component A QA certified?", "component_certification_missing", "comp_a", "CERTIFICATION_STATUS"),
    ("Screen which source has a delay signal", "multi_investigation_screening", "inc_delay_001", "DELAY_SIGNAL_SCREENING"),
]

FACTORIES = {
    "supplier_a_shipment_delay": supplier_shipment_delay_scenario,
    "supplier_delay_causal_attribution": supplier_delay_scenario,
    "supplier_b_conflicting_delivery": conflicting_delivery_scenario,
    "component_certification_missing": missing_evidence_scenario,
    "multi_investigation_screening": multi_investigation_scenario,
}


def main() -> None:
    repo = InMemoryGraphRepository()
    KnowledgeGraphIngestionPipeline(repo).ingest_dataset(generate_supplier_delay_dataset())
    service = InvestigationIntelligenceService(repo, DeterministicFakeLLM())
    rows = []
    for question, expected_scenario, expected_subject, expected_claim in CASES:
        scenario = FACTORIES[expected_scenario]()
        direct = run_langgraph_investigation(repo, scenario, build_scenario_planner(scenario),
                                             "tenant_alpha", max_tool_calls=4)
        started = perf_counter()
        result = service.investigate(question, "tenant_alpha", max_tool_calls=4)
        authoritative = result.investigation
        cited = set(result.supporting_evidence_ids + result.contradicting_evidence_ids)
        rows.append({
            "question": question, "intent_correct": result.scenario_id == expected_scenario,
            "entity_correct": result.subject_id == expected_subject,
            "claim_correct": result.claim_type and result.claim_type.value == expected_claim,
            "decision_parity": result.decision == direct.decision,
            "probability_fidelity": result.final_belief == direct.final_belief,
            "citation_validity": cited == set(authoritative["evidence_verdict"]["evidence_ids"]),
            "hallucinated_references": len(cited - set(authoritative["evidence_verdict"]["evidence_ids"])),
            "contradiction_disclosed": (not result.contradicting_evidence_ids or
                                        "contradict" in result.explanation.lower()),
            "abstention_fidelity": direct.decision != "ABSTAIN" or result.decision == "ABSTAIN",
            "grounded": result.grounding_valid is True,
            "fallback": result.explanation_fallback_used,
            "runtime_ms": (perf_counter() - started) * 1000,
            "tokens": sum(x.total_tokens or 0 for x in result.llm_usage),
            "estimated_cost_usd": sum(x.estimated_cost_usd or 0 for x in result.llm_usage),
        })
    print("provider=deterministic-fake (offline rules, not real LLM quality)")
    print(f"cases={len(rows)} intent_accuracy={mean(r['intent_correct'] for r in rows):.3f} "
          f"entity_accuracy={mean(r['entity_correct'] for r in rows):.3f} "
          f"claim_accuracy={mean(r['claim_correct'] for r in rows):.3f} "
          f"decision_parity={mean(r['decision_parity'] for r in rows):.3f} "
          f"probability_fidelity={mean(r['probability_fidelity'] for r in rows):.3f} "
          f"citation_validity={mean(r['citation_validity'] for r in rows):.3f} "
          f"contradiction_disclosure={mean(r['contradiction_disclosed'] for r in rows):.3f} "
          f"abstention_fidelity={mean(r['abstention_fidelity'] for r in rows):.3f} "
          f"grounding_validity={mean(r['grounded'] for r in rows):.3f} "
          f"fallback_rate={mean(r['fallback'] for r in rows):.3f} "
          f"mean_runtime_ms={mean(r['runtime_ms'] for r in rows):.3f} "
          f"hallucinated_references={sum(r['hallucinated_references'] for r in rows)} "
          f"tokens={sum(r['tokens'] for r in rows)} "
          f"estimated_cost_usd={sum(r['estimated_cost_usd'] for r in rows):.6f}")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
