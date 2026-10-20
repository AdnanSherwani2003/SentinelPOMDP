"""Natural-language -> validated scenario -> LangGraph -> grounded explanation demo."""
from __future__ import annotations

import argparse
import sys

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository, Neo4jGraphRepository
from sentinel_pomdp.intelligence import (
    DeterministicFakeLLM, GroqResponsesClient, InvestigationIntelligenceService,
    LLMClientError, OpenAIResponsesClient,
)

DEFAULT_QUESTIONS = [
    "Was Supplier A's shipment late?", "Did Supplier A cause the production delay?",
    "Did Supplier B deliver on time?", "Is Component A QA certified?",
    "Screen which source has a delay signal",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Constrained SentinelPOMDP LLM adapter demo")
    parser.add_argument("--backend", choices=("in-memory", "neo4j"), default="in-memory")
    parser.add_argument("--provider", choices=("fake", "openai", "groq"), default="fake")
    parser.add_argument("--question", help="One question; omit to run the five-scenario demo")
    parser.add_argument("--tenant", default="tenant_alpha")
    args = parser.parse_args()
    manager = None
    try:
        if args.backend == "neo4j":
            manager = Neo4jConnectionManager()
            if not manager.ping():
                print(f"ERROR: live Neo4j unavailable at {manager.config.uri}; no fallback used.", file=sys.stderr)
                return 2
            repository = Neo4jGraphRepository(manager)
            repository.init_schema_constraints()
        else:
            repository = InMemoryGraphRepository()
        report = KnowledgeGraphIngestionPipeline(repository).ingest_dataset(generate_supplier_delay_dataset())
        if not report.is_success:
            print(report.summary(), file=sys.stderr)
            return 1
        clients = {
            "fake": DeterministicFakeLLM,
            "openai": OpenAIResponsesClient,
            "groq": GroqResponsesClient,
        }
        try:
            client = clients[args.provider]()
        except LLMClientError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        service = InvestigationIntelligenceService(repository, client)
        print(f"backend={args.backend} provider={client.provider} (fake means deterministic rules, not an LLM)")
        for question in [args.question] if args.question else DEFAULT_QUESTIONS:
            result = service.investigate(question, args.tenant, max_tool_calls=4)
            print("\nQUESTION:", question)
            print("SCENARIO:", result.scenario_id, "CLAIM:", result.claim_type)
            print("DECISION:", result.decision, "HYPOTHESIS:", result.selected_hypothesis)
            print("BELIEF:", result.final_belief)
            print("FACTS:", result.fact_ids)
            print("SUPPORT:", result.supporting_evidence_ids)
            print("CONTRADICTIONS:", result.contradicting_evidence_ids)
            print("DOCUMENTS:", result.document_ids)
            print("EXPLANATION:", result.explanation)
            print("FALLBACK:", result.explanation_fallback_used, "TRACE:", result.trace_id)
            print("LLM USAGE:", [usage.model_dump() for usage in result.llm_usage])
        return 0
    finally:
        if manager:
            manager.close()


if __name__ == "__main__":
    raise SystemExit(main())
