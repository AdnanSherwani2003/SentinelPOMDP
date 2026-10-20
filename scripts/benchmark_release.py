"""Bounded local measurements; no production-capacity or improvement claims."""
from __future__ import annotations
import json
from pathlib import Path
import platform
import secrets
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from fastapi.testclient import TestClient
from sentinel_pomdp.api.app import create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.domains import DomainPackService, procurement_demo_pack, seed_synthetic_procurement
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.ingestion.storage import LocalDocumentStore
from sentinel_pomdp.investigation.scenario import build_scenario_planner, supplier_shipment_delay_scenario
from sentinel_pomdp.operations import SQLiteOperationRepository, DurableWorker, NewOperationJob, OperationType


def measure(call, n=50):
    times = []
    for _ in range(n):
        start = perf_counter(); call(); times.append((perf_counter() - start) * 1000)
    ordered = sorted(times)
    return {"samples": n, "median_ms": median(times), "p95_ms": ordered[int(.95 * (n - 1))]}


def main():
    with TemporaryDirectory(prefix="sentinel-i20-benchmark-") as temporary:
        root = Path(temporary)
        graph = InMemoryGraphRepository()
        seed_synthetic_procurement(graph, "benchmark")
        pack_service = DomainPackService(LocalDocumentStore(root / "packs"), graph)
        pack = procurement_demo_pack("benchmark")
        planner = build_scenario_planner(supplier_shipment_delay_scenario())
        belief = {"shipment_delayed": .55, "shipment_on_time": .45}
        result = {"environment": {"platform": platform.platform(), "python": platform.python_version()},
            "concurrency": 1, "fixture": "bounded synthetic in-memory graph; local SQLite",
            "graph_lookup": measure(lambda: graph.get_entity("PO-2001", "benchmark")),
            "bayesian_update": measure(lambda: planner.posterior(belief, "inspect_supplier_a_delivery", "EVIDENCE_SUPPORTED")),
            "planner": measure(lambda: planner.decide(belief)),
            "domain_validation": measure(lambda: pack_service.validate("benchmark", pack)),
            "duplicate_reconciliation": measure(lambda: seed_synthetic_procurement(graph, "benchmark"))}
        operations = SQLiteOperationRepository(root / "ops.db")
        index = iter(range(50))
        result["durable_job_creation"] = measure(lambda: operations.create_job(NewOperationJob(
            tenant_id="benchmark", principal_id="benchmark", operation_type=OperationType.EVALUATION,
            correlation_id=str(next(index)), payload={}, replay_safe=True)))
        worker = DurableWorker(operations, {OperationType.EVALUATION: lambda context, payload: payload})
        start = perf_counter()
        for _ in range(50): assert worker.run_once()
        result["worker_jobs_per_second"] = 50 / (perf_counter() - start)
        operations.close()
        key = secrets.token_urlsafe(32)
        start = perf_counter()
        app = create_app(AppSettings(api_key=key, rate_limit_per_minute=100,
            document_store_path=str(root / "api-docs"), operations_database_path=str(root / "api.db")))
        with TestClient(app) as client:
            result["api_startup_ms_single_sample"] = (perf_counter() - start) * 1000
            def investigate():
                response = client.post("/api/v1/investigations", headers={"Authorization": "Bearer " + key},
                    json={"question": "Was Supplier A's shipment late?"})
                assert response.status_code == 200
                assert response.json()["decision"] == "ANSWER"
            result["api_investigation"] = measure(investigate, 20)
    path = Path("reports/implementation20/performance.json")
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
