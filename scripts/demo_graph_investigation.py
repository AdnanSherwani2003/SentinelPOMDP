"""Implementation 8 graph-backed POMDP demonstration."""
from __future__ import annotations

import argparse
import sys

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository, Neo4jGraphRepository
from sentinel_pomdp.investigation import (
    build_scenario_planner, conflicting_delivery_scenario, missing_evidence_scenario,
    run_graph_investigation, supplier_delay_scenario,
)
from sentinel_pomdp.investigation.evaluation import evaluate_policies
from sentinel_pomdp.investigation.trace import format_investigation_trace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("in-memory", "neo4j"), default="in-memory")
    args = parser.parse_args()
    manager = None
    if args.backend == "neo4j":
        manager = Neo4jConnectionManager()
        if not manager.ping():
            print(f"ERROR: live Neo4j unavailable at {manager.config.uri}; no fallback was used.", file=sys.stderr)
            return 2
        repository = Neo4jGraphRepository(manager)
        repository.init_schema_constraints()
    else:
        repository = InMemoryGraphRepository()
    report = KnowledgeGraphIngestionPipeline(repository).ingest_dataset(generate_supplier_delay_dataset())
    if not report.is_success:
        print(report.summary(), file=sys.stderr)
        return 1
    print(f"BACKEND: {args.backend}\n{report.summary()}")
    for scenario in (supplier_delay_scenario(), conflicting_delivery_scenario(), missing_evidence_scenario()):
        print("\n" + "=" * 78)
        print(f"SCENARIO: {scenario.name}")
        print(f"INITIAL BELIEF: {scenario.prior}")
        outcome = run_graph_investigation(repository, scenario, build_scenario_planner(scenario, 2),
                                          "tenant_alpha", max_steps=4, budget=1.0)
        print(format_investigation_trace(outcome))
    print("\nPOLICY COMPARISON (three deterministic scenarios; not a statistical benchmark)")
    for row in evaluate_policies(repository):
        print(row)
    if manager:
        manager.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
