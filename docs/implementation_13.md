# Implementation 13: deployment and final evaluation

## What was added

- A locked, multi-stage, non-root application image in `Dockerfile`.
- A local-only deployment candidate in `infra/deployment.compose.yaml` with private Neo4j networking, health checks, restart policy, resource limits and named volumes.
- Typed startup checks for deployment mode, backend/provider selection, API/Neo4j credentials, external-provider consent, planning/tool/budget/time/rate limits, logging and checkpoint mode.
- A deterministic five-policy benchmark with balanced paired seeds, per-episode CSV, aggregate JSON, Brier score, log loss, calibration error, entropy reduction, costs, utility and a paired bootstrap interval.
- Evidence/language boundary cases and bounded local API/concurrency measurements.
- Failure tests for missing credentials, no database fallback and honest HTTP timeout semantics.
- Least-privilege CI with offline tests, disposable Neo4j, package/image builds, secret-shaped scanning and a lightweight benchmark artifact.

## Concepts in plain language

Deployment packages the same program and dependencies so another machine starts the same service. Docker supplies an isolated filesystem and process; Compose wires the API to Neo4j. Reproducibility records dependency versions, seeds and configuration so a result can be rerun.

CI/CD means automated checks on every change. This repository adds CI (verification), not CD (automatic deployment). It never publishes an image or calls a paid model.

A baseline is a simpler policy used to test whether complexity helps. The benchmark compares immediate abstention, fixed action order, greedy information gain, one-step expected utility and horizon-2 POMDP planning on identical simulated episodes. Realized utility is the terminal reward or penalty minus investigation cost. Selective accuracy is accuracy only among answered cases; abstention rate shows how often the system declines.

Brier score and log loss compare predicted probabilities with simulated outcomes; lower is better. Expected calibration error groups confidence into bins and compares confidence with observed correctness. A confidence interval describes sampling uncertainty in a measured policy difference. These are simulator-calibration measurements, not evidence of real-world calibration.

An ablation removes or replaces one component while holding the rest constant. Fixed versus planner-selected retrieval isolates action selection. Immediate versus planned policies isolates investigation. The evidence-gate-off comparison remains an offline research concept only; it is never exposed as an application setting.

Latency percentiles summarize a distribution: median is the middle request, P95 is a value below which roughly 95% of samples fell. Small local TestClient samples do not predict production throughput.

Reliability tests deliberately break dependencies or exceed limits. They verify safe errors, not perpetual availability. Production readiness asks whether the whole operational system—not just its core algorithm—can be trusted and supported.

## Reproduction (PowerShell)

```powershell
# From the repository root.
uv sync --frozen
$env:RUN_LIVE_GROQ_TESTS = "0"
$env:RUN_LIVE_LLM_TESTS = "0"
uv run pytest -q -rs
uv run python scripts/evaluate_final.py --episodes-per-state 200 --seed 13000
uv run python scripts/check_secrets.py
uv build
docker build -t sentinel-pomdp:implementation-13 .
```

Live Neo4j uses credentials already configured by the operator:

```powershell
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "<existing-private-password>"
uv run pytest -q -v -rs tests/test_security_live.py tests/test_api_live.py
uv run python scripts/evaluate_api.py --backend neo4j --samples 10 --output reports/live_neo4j_api.json
```

Do not paste secrets into command history on shared machines; prefer the operating-system secret facility or a private environment injector.

## Restart and timeout behavior

Neo4j volume data survives a Compose restart. In-memory API credentials, traces, audit events, metrics, idempotency entries, rate counters and checkpoints do not. The API returns 504 when its wait limit expires, but a synchronous Python worker may continue and could still incur provider/database work. Retrying such a request can duplicate cost. Enforceable cooperative cancellation and durable idempotency remain future work.

## Future roadmap

1. Calibrate likelihoods and thresholds on held-out, labeled domain data with correlation/missingness models.
2. Add managed identity, key rotation, secrets, TLS and durable tenant-aware audit storage.
3. Add durable checkpoints/idempotency and cooperative cancellation/provider deadlines.
4. Build authenticated ingestion, schema mapping, source authenticity checks and data-quality monitoring.
5. Add distributed rate limiting, metrics/traces export, alerts, backups and tested recovery.
6. Run real-provider evaluation only under an approved privacy/cost plan; diagnose explanation fallback without weakening grounding.
7. Conduct staged pilot validation, red-team testing and independent security review with mandatory human approval.
