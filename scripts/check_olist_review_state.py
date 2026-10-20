"""Read-only post-reconciliation count check for the Olist research tenant."""
from __future__ import annotations

import argparse
import json

from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.ingestion.storage import LocalDocumentStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="tenant_olist_research")
    parser.add_argument("--store", default="data/company_documents")
    args = parser.parse_args()
    store = LocalDocumentStore(args.store)
    candidates = store.list_candidates(args.tenant)
    documents = store.list_documents(args.tenant)
    manager = Neo4jConnectionManager()
    try:
        with manager.session() as session:
            nodes = {record["kind"]: record["count"] for record in session.run(
                "MATCH (n {tenant_id: $tenant}) RETURN head(labels(n)) AS kind, count(n) AS count",
                tenant=args.tenant)}
            relationships = session.run(
                "MATCH (a {tenant_id: $tenant})-[r]->(b {tenant_id: $tenant}) RETURN count(r) AS count",
                tenant=args.tenant).single()["count"]
    finally:
        manager.close()
    print(json.dumps({
        "tenant_id": args.tenant,
        "review_candidates": len(candidates),
        "approved_candidates": sum(item.status.value == "APPROVED" for item in candidates),
        "reviewers": sorted({item.reviewed_by for item in candidates if item.reviewed_by}),
        "source_references": len(documents),
        "unique_reviewed_graph_facts": len({item.graph_fact_id for item in candidates if item.graph_fact_id}),
        "graph_nodes": nodes,
        "graph_relationships": relationships,
    }, indent=2))


if __name__ == "__main__":
    main()
