"""Generate the reproducible Implementation 13 evaluation artifacts."""
from __future__ import annotations

import argparse
import csv
import json
import secrets
import statistics
import sys
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient

from sentinel_pomdp.api import create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.final_evaluation import run_final_synthetic_benchmark
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.intelligence import DeterministicFakeLLM, InvestigationIntelligenceService


QUESTIONS = (
    ("shipment_lateness", "Was Supplier A's shipment late?"),
    ("causal_attribution", "Did Supplier A cause the entire production delay?"),
    ("conflicting_delivery", "Did Supplier B deliver on time?"),
    ("missing_certification", "Is Component A certified?"),
    ("multi_investigation", "Screen which source has a production delay signal."),
    ("unsupported", "What will next quarter's stock price be?"),
    ("ambiguous", "What happened?"),
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def evidence_evaluation() -> list[dict]:
    repository = InMemoryGraphRepository()
    report = KnowledgeGraphIngestionPipeline(repository).ingest_dataset(
        generate_supplier_delay_dataset())
    if not report.is_success:
        raise RuntimeError("synthetic graph initialization failed")
    service = InvestigationIntelligenceService(repository, DeterministicFakeLLM())
    rows = []
    for name, question in QUESTIONS:
        started = perf_counter()
        response = service.investigate(question, "tenant_alpha")
        rows.append({
            "case": name, "question": question, "status": response.status.value,
            "scenario_id": response.scenario_id, "claim_type": (
                response.claim_type.value if response.claim_type else None),
            "decision": response.decision, "selected_hypothesis": response.selected_hypothesis,
            "provenance_status": response.provenance_status,
            "grounding_valid": response.grounding_valid,
            "fallback": response.explanation_fallback_used,
            "fact_ids": response.fact_ids,
            "supporting_evidence_ids": response.supporting_evidence_ids,
            "contradicting_evidence_ids": response.contradicting_evidence_ids,
            "document_ids": response.document_ids,
            "latency_ms": (perf_counter() - started) * 1000,
        })
    return rows


def api_evaluation(samples: int = 12, concurrency: int = 4) -> dict:
    key = secrets.token_urlsafe(32)
    settings = AppSettings(api_key=key, rate_limit_per_minute=1000)
    app = create_app(settings)
    headers = {"Authorization": f"Bearer {key}"}
    question = {"question": "Was Supplier A's shipment late?"}
    latencies: list[float] = []
    statuses: list[int] = []
    tracemalloc.start()
    with TestClient(app) as client:
        client.get("/health/ready")
        client.post("/api/v1/investigations", headers=headers, json=question)
        for _ in range(samples):
            started = perf_counter()
            response = client.post("/api/v1/investigations", headers=headers, json=question)
            latencies.append((perf_counter() - started) * 1000)
            statuses.append(response.status_code)

        def request_once(_index: int) -> tuple[int, float]:
            started = perf_counter()
            response = client.post("/api/v1/investigations", headers=headers, json=question)
            return response.status_code, (perf_counter() - started) * 1000

        started = perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            concurrent_rows = list(executor.map(request_once, range(concurrency * 2)))
        concurrent_seconds = perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    concurrent_statuses = [row[0] for row in concurrent_rows]
    concurrent_latencies = [row[1] for row in concurrent_rows]
    return {
        "mode": "in_memory_fake_provider", "warmup_requests": 1,
        "sequential_samples": samples, "sequential_successes": statuses.count(200),
        "latency_ms": {
            "min": min(latencies), "median": statistics.median(latencies),
            "p95": percentile(latencies, .95), "max": max(latencies),
        },
        "bounded_concurrency": concurrency,
        "concurrent_samples": len(concurrent_rows),
        "concurrent_successes": concurrent_statuses.count(200),
        "concurrent_error_count": sum(code != 200 for code in concurrent_statuses),
        "concurrent_latency_ms": {
            "median": statistics.median(concurrent_latencies),
            "p95": percentile(concurrent_latencies, .95),
        },
        "throughput_requests_per_second": len(concurrent_rows) / concurrent_seconds,
        "python_tracemalloc_peak_bytes": peak,
        "limitations": [
            "Local TestClient measurements are not network or production load tests.",
            "tracemalloc measures traced Python allocations, not total process RSS.",
            "Process-local state and rate limits are not coordinated across workers.",
        ],
    }


def write_records(path: Path, records_by_policy: dict) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "policy", "episode", "true_state", "predicted_state", "decision", "correct",
            "confidence", "steps", "actions", "observations", "cost", "realized_utility",
        ])
        writer.writeheader()
        for policy, records in records_by_policy.items():
            for index, record in enumerate(records):
                writer.writerow({
                    "policy": policy, "episode": index,
                    "true_state": record.true_state.value,
                    "predicted_state": record.predicted_state.value if record.predicted_state else "",
                    "decision": record.terminated_by.value, "correct": record.correct,
                    "confidence": record.final_confidence, "steps": record.steps,
                    "actions": "|".join(record.actions),
                    "observations": "|".join(record.observations),
                    "cost": record.total_cost, "realized_utility": record.realized_utility,
                })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes-per-state", type=int, default=200)
    parser.add_argument("--seed", type=int, default=13_000)
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    if args.episodes_per_state < 1:
        parser.error("--episodes-per-state must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    synthetic, records = run_final_synthetic_benchmark(
        episodes_per_state=args.episodes_per_state, seed=args.seed)
    result = {
        "schema_version": 1,
        "configuration": {
            "episodes_per_state": args.episodes_per_state, "seed": args.seed,
            "provider": "deterministic-fake", "backend": "memory",
            "secrets_included": False,
        },
        "synthetic_benchmark": synthetic,
        "evidence_and_language_boundary": evidence_evaluation(),
        "api_performance": api_evaluation(),
        "live_groq": {"status": "NOT_TESTED", "reason": "paid calls are a separate explicit opt-in"},
        "live_neo4j": {"status": "NOT_RUN_BY_THIS_OFFLINE_BENCHMARK",
                        "reason": "live integration is verified by marked pytest tests"},
    }
    json_path = args.output_dir / "final_benchmark.json"
    csv_path = args.output_dir / "final_benchmark.csv"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    write_records(csv_path, records)
    print(f"SentinelPOMDP final benchmark: {synthetic['total_episodes_per_policy']} episodes/policy")
    for row in synthetic["policies"]:
        print(
            f"{row['policy']:<24} answer={row['answer_rate']:.1%} "
            f"selective={row['selective_accuracy']:.1%} utility={row['average_realized_utility']:.4f} "
            f"brier={row['brier_score']:.4f} runtime={row['runtime_seconds']:.3f}s")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
