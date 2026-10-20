"""Command-line demonstration of Knowledge Graph & Evidence Provenance.

Demonstrates:
1. Entity discovery and relationship querying
2. Multi-hop traversal (Supplier -> Component -> Product)
3. Traceable provenance chains:
   - Scenario A: Strong supporting evidence (corroborated by independent sources)
   - Scenario B: Contradictory evidence (supplier claim vs receiving dock inspection)
   - Scenario C: Missing evidence (unsupported claim / evidence gap)
   - Scenario D: Ambiguous evidence (competing plausible hypotheses)
4. Inert prompt-injection text handling (treated strictly as data)
5. Strict tenant isolation (tenant_alpha queries cannot retrieve tenant_beta records)

Usage:
    uv run python scripts/demo_graph.py [--in-memory]
"""
import argparse
import logging
import sys
from typing import Any, Dict

logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.provenance import (
    audit_tenant_provenance,
    format_provenance_trace,
    validate_evidence_chain,
)
from sentinel_pomdp.graph.repository import InMemoryGraphRepository, Neo4jGraphRepository
from sentinel_pomdp.graph.seed import seed_graph_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Demonstrate SentinelPOMDP Knowledge Graph & Evidence Provenance")
    parser.add_argument("--in-memory", action="store_true", help="Force in-memory repository backend")
    args = parser.parse_args()

    print("\n" + "#" * 78)
    print("  SENTINEL-POMDP — IMPLEMENTATION 7: KNOWLEDGE GRAPH & EVIDENCE PROVENANCE")
    print("#" * 78 + "\n")

    # Step 1: Initialize Repository
    if args.in_memory:
        print("[BACKEND] Forced in-memory mode: Using InMemoryGraphRepository.")
        repo = InMemoryGraphRepository()
    else:
        cm = Neo4jConnectionManager()
        if cm.ping():
            print(f"[BACKEND] Connected to live Neo4j service at {cm.config.uri}.")
            repo = Neo4jGraphRepository(cm)
        else:
            print(f"[BACKEND] Neo4j service at {cm.config.uri} is offline.")
            print("          Falling back to InMemoryGraphRepository (pure-Python reference implementation).")
            print("          Note: Set up Neo4j via 'docker compose -f infra/compose.yaml up -d' for live database.")
            repo = InMemoryGraphRepository()

    # Step 2: Seed Dataset
    dataset = generate_supplier_delay_dataset()
    report = seed_graph_database(repo, dataset)
    print(f"\n[DATASET SEEDING] {report.summary()}\n")

    tenant_a = "tenant_alpha"
    tenant_b = "tenant_beta"

    # =========================================================================
    # DEMO 1: ENTITY RETRIEVAL & DOMAIN MODEL
    # =========================================================================
    print("=" * 78)
    print("1. DOMAIN-ADAPTABLE ENTITY DISCOVERY (Tenant: tenant_alpha)")
    print("=" * 78)
    entities = repo.list_entities(tenant_id=tenant_a)
    print(f"Discovered {len(entities)} registered entities:")
    for e in entities:
        print(f"  * [{e.entity_type.upper():<18}] ID: {e.entity_id:<18} Name: {e.canonical_name}")

    # =========================================================================
    # DEMO 2: MULTI-HOP RELATIONSHIP TRAVERSAL
    # =========================================================================
    print("\n" + "=" * 78)
    print("2. MULTI-HOP GRAPH TRAVERSAL: Root = 'sup_a' (Supplier A)")
    print("=" * 78)
    paths = repo.get_multi_hop_relationships(start_entity_id="sup_a", tenant_id=tenant_a, max_hops=2)
    print(f"Discovered {len(paths)} structural paths originating from Supplier A:")
    for idx, p in enumerate(paths, 1):
        chain_str = " -> ".join([f"[{node['name']}]" for node in p["path"]])
        print(f"  Path {idx}: {chain_str}")

    # =========================================================================
    # DEMO 3: SCENARIO A — STRONG SUPPORTING EVIDENCE
    # =========================================================================
    print("\n" + "=" * 78)
    print("3. SCENARIO A: STRONG CORROBORATED EVIDENCE")
    print("   Hypothesis: 'Supplier A experienced a 5-day delivery delay on Shipment APX-101'")
    print("=" * 78)
    res_a = validate_evidence_chain(repo, fact_id="fact_sup_a_caused_delay", tenant_id=tenant_a)
    print(format_provenance_trace(res_a.chain))
    print(f"Reliability Verdict: {res_a.is_reliable} | Hash Mismatches: {len(res_a.hash_mismatches)}")

    # =========================================================================
    # DEMO 4: SCENARIO B — CONTRADICTORY EVIDENCE
    # =========================================================================
    print("\n" + "=" * 78)
    print("4. SCENARIO B: CONTRADICTORY EVIDENCE / DISCREPANCY DETECTED")
    print("   Claim: 'Supplier B delivered shipment BCN-202 on schedule'")
    print("=" * 78)
    res_b = validate_evidence_chain(repo, fact_id="fact_sup_b_delivered_ontime", tenant_id=tenant_a)
    print(format_provenance_trace(res_b.chain))
    print(f"Graph Status: {res_b.status.value}")
    print("Architectural Note: The graph layer reports conflicting evidence without jumping to conclusions.")
    print("                    Decision layer in future Milestone 8 will decide whether to investigate further or abstain.")

    # =========================================================================
    # DEMO 5: SCENARIO C — MISSING EVIDENCE (GAP DETECTION)
    # =========================================================================
    print("\n" + "=" * 78)
    print("5. SCENARIO C: MISSING EVIDENCE (UNSUPPORTED CLAIM)")
    print("   Claim: 'Component A has verified ISO-9001 QA certification'")
    print("=" * 78)
    res_c = validate_evidence_chain(repo, fact_id="fact_comp_a_qa_certified", tenant_id=tenant_a)
    print(format_provenance_trace(res_c.chain))
    print(f"Graph Status: {res_c.status.value}")
    print("Architectural Note: Unlike pure heuristics, our system explicitly marks unevidenced facts,")
    print("                    enabling mathematical abstention rather than hallucinated acceptance.")

    # =========================================================================
    # DEMO 6: SCENARIO D — AMBIGUOUS RIVAL HYPOTHESES
    # =========================================================================
    print("\n" + "=" * 78)
    print("6. SCENARIO D: AMBIGUOUS COMPETING HYPOTHESES")
    print("   Incident: 'Production Delay Incident INC-2026-04-18'")
    print("=" * 78)
    suspect_facts = repo.find_facts(
        tenant_id=tenant_a,
        subject_id="inc_delay_001",
        relation_type="ATTRIBUTED_SUSPECT",
    )
    print(f"Identified {len(suspect_facts)} competing attribution hypotheses:")
    for f in suspect_facts:
        target_entity = repo.get_entity(f.object_id, tenant_a)
        chain = repo.get_provenance_chain(f.fact_id, tenant_a)
        evidence_summary = chain.summary if chain else "No evidence chain"
        print(f"  * Suspect: {target_entity.canonical_name:<36} | Evidence: {evidence_summary}")

    # =========================================================================
    # DEMO 7: UNTRUSTED DATA & INERT PROMPT INJECTION
    # =========================================================================
    print("\n" + "=" * 78)
    print("7. UNTRUSTED DATA HANDLING & INERT INJECTION TEST")
    print("=" * 78)
    untrusted_doc = repo.get_document("doc_untrusted_note_006", tenant_a)
    if untrusted_doc:
        print(f"Document ID:     {untrusted_doc.document_id}")
        print(f"Classification:  {untrusted_doc.classification}")
        print(f"Content Hash:    {untrusted_doc.content_hash[:20]}...")
        print(f"Stored Content:  \"{untrusted_doc.raw_content}\"")
        print("Security Note:   Untrusted source text is stored as strictly inert string data.")
        print("                 It is never evaluated or executed as system instructions.")

    # =========================================================================
    # DEMO 8: STRICT MULTI-TENANT ISOLATION ENFORCEMENT
    # =========================================================================
    print("\n" + "=" * 78)
    print("8. STRICT MULTI-TENANT ISOLATION VERIFICATION")
    print("=" * 78)
    print(f"Querying tenant '{tenant_a}' for entities...")
    entities_a = repo.list_entities(tenant_id=tenant_a)
    print(f"  Found {len(entities_a)} entities in '{tenant_a}'.")

    print(f"Querying tenant '{tenant_b}' for entities...")
    entities_b = repo.list_entities(tenant_id=tenant_b)
    print(f"  Found {len(entities_b)} entities in '{tenant_b}':")
    for eb in entities_b:
        print(f"    - {eb.entity_id}: {eb.canonical_name}")

    print("\nAttempting Cross-Tenant Boundary Violations:")
    # Attempt to query tenant_beta entity using tenant_alpha scope
    leak_test_entity = repo.get_entity(entity_id="sup_gamma", tenant_id=tenant_a)
    print(f"  Querying 'sup_gamma' (Tenant B supplier) within Tenant A scope: Result = {leak_test_entity}")
    assert leak_test_entity is None, "SECURITY FAILURE: Cross-tenant entity leakage detected!"

    # Attempt to query tenant_beta document using tenant_alpha scope
    leak_test_doc = repo.get_document(document_id="doc_beta_cert_001", tenant_id=tenant_a)
    print(f"  Querying 'doc_beta_cert_001' (Tenant B document) within Tenant A scope: Result = {leak_test_doc}")
    assert leak_test_doc is None, "SECURITY FAILURE: Cross-tenant document leakage detected!"

    print("  [+] Multi-tenant boundary successfully enforced: Zero cross-tenant leakage!")

    # =========================================================================
    # DEMO 9: TENANT AUDIT SUMMARY
    # =========================================================================
    print("\n" + "=" * 78)
    print("9. TENANT PROVENANCE AUDIT SUMMARY")
    print("=" * 78)
    audit = audit_tenant_provenance(repo, tenant_id=tenant_a)
    print(f"Tenant:                        {audit['tenant_id']}")
    print(f"Total Facts:                   {audit['total_facts']}")
    print(f"Supported Facts:               {len(audit['supported_facts'])}")
    print(f"Conflicted Facts:              {len(audit['conflicted_facts'])}")
    print(f"Unevidenced Facts:             {len(audit['unevidenced_facts'])}")
    print(f"Abstention Candidates:         {len(audit['abstention_recommended_facts'])}")
    print("=" * 78)
    print("\n[+] Demonstration completed successfully.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
