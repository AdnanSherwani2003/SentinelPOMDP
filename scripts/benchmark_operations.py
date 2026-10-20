"""Small repeatable durability-overhead benchmark; not a product throughput claim."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from statistics import mean, median, quantiles
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

from sentinel_pomdp.operations import (
    DurableWorker, NewOperationJob, OperationType,
    PostgresOperationRepository, SQLiteOperationRepository,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("sqlite", "postgres"), default="sqlite")
    parser.add_argument("--jobs", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 10_000:
        raise SystemExit("--jobs must be between 1 and 10000")
    temporary = TemporaryDirectory() if args.backend == "sqlite" else None
    if args.backend == "postgres":
        url = os.getenv("SENTINEL_TEST_OPERATIONS_DATABASE_URL")
        if not url or "sentinel_test" not in url:
            raise SystemExit("postgres benchmark requires the disposable sentinel_test URL")
        repository = PostgresOperationRepository(url)
    else:
        repository = SQLiteOperationRepository(Path(temporary.name) / "operations.db")
    tenant = f"benchmark-{uuid4()}"; enqueue_times = []
    for index in range(args.jobs):
        started = perf_counter()
        repository.create_job(NewOperationJob(
            tenant_id=tenant, principal_id="benchmark", operation_type=OperationType.EVALUATION,
            correlation_id=str(uuid4()), payload={"index": index},
            idempotency_key=f"job-{index}", replay_safe=True))
        enqueue_times.append((perf_counter() - started) * 1000)
    worker = DurableWorker(repository, {OperationType.EVALUATION: lambda _context, payload: payload})
    started = perf_counter(); completed = 0
    while completed < args.jobs and worker.run_once():
        completed += 1
    processing_seconds = perf_counter() - started
    percentiles = quantiles(enqueue_times, n=20) if len(enqueue_times) >= 20 else enqueue_times
    print({
        "backend": args.backend, "jobs": args.jobs, "completed": completed,
        "enqueue_mean_ms": round(mean(enqueue_times), 3),
        "enqueue_median_ms": round(median(enqueue_times), 3),
        "enqueue_p95_ms": round(percentiles[-1], 3),
        "worker_jobs_per_second": round(completed / processing_seconds, 2),
    })
    repository.close()
    if temporary is not None: temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
