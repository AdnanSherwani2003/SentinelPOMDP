"""Execute real planner -> graph -> Bayes cycles through LangGraph."""
from __future__ import annotations

import argparse
import sys

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository, Neo4jGraphRepository
from sentinel_pomdp.investigation import (
    build_scenario_planner, conflicting_delivery_scenario, missing_evidence_scenario,
    multi_investigation_scenario, supplier_delay_scenario, supplier_shipment_delay_scenario,
)
from sentinel_pomdp.investigation.trace import format_investigation_trace
from sentinel_pomdp.orchestration import run_langgraph_investigation
from sentinel_pomdp.orchestration.trace import format_workflow_trace


def main() -> int:
    parser = argparse.ArgumentParser(description="SentinelPOMDP LangGraph demonstration")
    parser.add_argument("--backend", choices=("in-memory", "neo4j"), default="in-memory")
    parser.add_argument("--horizon", type=int, choices=(1, 2), default=2)
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
    scenarios = [supplier_shipment_delay_scenario(), supplier_delay_scenario(),
                 conflicting_delivery_scenario(), missing_evidence_scenario(),
                 multi_investigation_scenario()]
    for scenario in scenarios:
        print("\n" + "=" * 88)
        print(f"SCENARIO: {scenario.scenario_id} - {scenario.name}")
        print(f"INITIAL BELIEF: {scenario.prior}")
        outcome = run_langgraph_investigation(
            repository, scenario, build_scenario_planner(scenario, args.horizon),
            "tenant_alpha", max_tool_calls=4, budget=1.0,
        )
        print("\nLANGGRAPH NODE TRACE")
        print(format_workflow_trace(outcome))
        print("\nINVESTIGATION RESULT")
        print(format_investigation_trace(outcome))
    if manager:
        manager.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
