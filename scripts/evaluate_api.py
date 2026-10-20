"""Reproducible local parity and overhead sample for Implementation 12."""
from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path
from statistics import median
from time import perf_counter

from fastapi.testclient import TestClient

from sentinel_pomdp.api.app import create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.intelligence import DeterministicFakeLLM, InvestigationIntelligenceService


def timed(callable_):
    started = perf_counter()
    value = callable_()
    return value, (perf_counter() - started) * 1000


def _stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {"min": min(values), "median": median(values),
            "p95": ordered[min(len(ordered) - 1, int((len(ordered) - 1) * .95))],
            "max": max(values)}


def main(samples: int = 10, backend: str = "memory", output: Path | None = None) -> dict:
    credential = secrets.token_urlsafe(32)
    app = create_app(AppSettings(api_key=credential, backend=backend,
                                 rate_limit_per_minute=max(30, samples * 3)))
    deps = app.state.dependencies
    repository = deps.service.intelligence.repository
    direct_service = InvestigationIntelligenceService(repository, DeterministicFakeLLM())
    question = "Was Supplier A's shipment late?"
    direct_times: list[float] = []
    protected_times: list[float] = []
    api_times: list[float] = []
    direct = protected = api = None
    with TestClient(app) as client:
        # Warm the Python graph, driver pool, deterministic workflow, and ASGI path.
        direct_service.investigate(question, "tenant_alpha")
        deps.service.investigate(
            credential, question, correlation_id="evaluation-protected-warmup")
        client.post("/api/v1/investigations", headers={"Authorization": f"Bearer {credential}"},
                    json={"question": question})
        for index in range(samples):
            direct, elapsed = timed(lambda: direct_service.investigate(question, "tenant_alpha"))
            direct_times.append(elapsed)
            protected, elapsed = timed(lambda: deps.service.investigate(
                credential, question, correlation_id=f"evaluation-protected-{index}").response)
            protected_times.append(elapsed)
            api_response, elapsed = timed(lambda: client.post(
                "/api/v1/investigations",
                headers={"Authorization": f"Bearer {credential}"},
                json={"question": question}))
            api_times.append(elapsed)
            api = api_response.json()

    assert direct is not None and protected is not None and api is not None
    parity = (
        direct.scenario_id == protected.scenario_id == api["scenario_id"]
        and direct.decision == protected.decision == api["decision"]
        and direct.final_belief == protected.final_belief == api["posterior"]
        and direct.supporting_evidence_ids == protected.supporting_evidence_ids
        == api["supporting_evidence_ids"]
        and direct.investigation["total_cost"] == protected.investigation["total_cost"]
        == api["investigation_cost"]
    )
    direct_median = median(direct_times)
    protected_median = median(protected_times)
    api_median = median(api_times)
    print("PARITY:", parity)
    print("SAMPLES:", samples)
    print("MEDIAN_MS:", f"direct={direct_median:.3f}",
          f"protected={protected_median:.3f}", f"api={api_median:.3f}")
    print("OVERHEAD_MS:", f"security={protected_median - direct_median:.3f}",
          f"http_over_protected={api_median - protected_median:.3f}")
    print("AUTHORITATIVE_TIMINGS_MS:", api["timings"])
    result = {
        "backend": backend, "provider": "fake", "samples": samples,
        "warmup_requests_per_path": 1, "parity": parity,
        "direct_ms": _stats(direct_times), "protected_ms": _stats(protected_times),
        "api_ms": _stats(api_times),
        "median_overhead_ms": {
            "security": protected_median - direct_median,
            "http_over_protected": api_median - protected_median,
        },
        "authoritative_last_request_timings_ms": api["timings"],
        "limitations": ["Local TestClient benchmark; not a production network load test."],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--backend", choices=("memory", "neo4j"), default="memory")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    main(arguments.samples, arguments.backend, arguments.output)
