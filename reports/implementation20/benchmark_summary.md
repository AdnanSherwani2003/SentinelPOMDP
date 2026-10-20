# Bounded performance measurements

Environment: Windows 11 build 26200, Python 3.13.15, Intel i5-13420H with 12 logical
processors, 25,442,508,800 physical bytes reported. Docker runtime uses Linux Python
3.13.16, Neo4j 5.26 Community and PostgreSQL 17. These are local observations, not
minimum hardware requirements or production capacity guarantees.

Final microbenchmark: scripts/benchmark_release.py, concurrency one, 50 samples per
micro-operation and 20 API requests, disposable memory graph and SQLite. Values are
milliseconds. Exact results are in performance.json.

| Operation | Median | p95 |
|---|---:|---:|
| Memory graph lookup | .000300 | .000500 |
| Bayesian posterior update | .006600 | .012200 |
| Bounded planner | .076400 | .317200 |
| Domain validation | .028850 | .077000 |
| Idempotent fixture reconciliation | .064000 | .070900 |
| SQLite durable job creation | 2.968150 | 3.285200 |
| ASGI factual shipment investigation | 14.092000 | 16.216300 |

Single-sample application construction/ASGI startup: 102.065 ms. Fifty trivial
SQLite worker jobs: 54.13 jobs/s. This is a bounded journal/worker measurement, not
a business workflow or distributed throughput benchmark. Memory lookup is close to
clock resolution and is not a network database measurement.

Warmed live Neo4j lookup over the Docker internal connection: 50 reads of an existing
synthetic fact, median 5.55227 ms, p95 8.11603 ms. The fact result was checked each
time. Database/driver warmup was excluded.

Observed container resident usage during the controlled demo: API 134.1 MiB,
one worker 126.2 MiB, PostgreSQL 75.18 MiB, Neo4j 720.5 MiB. These are point samples
from docker stats, not peak/soak measurements. The profile has two workers and
configured memory limits; measured usage does not establish minimum host RAM.

Historical Olist scale measurements are preserved: 100 orders in 16.65 seconds,
1,000 in 153.49 seconds. They were not repeated against persistent research data
and are not compared as though machine/configuration/workload were controlled.
No new full-scale import throughput or production reconciliation capacity claim is
made. Core mathematical assumptions were not tuned to improve these measurements.
