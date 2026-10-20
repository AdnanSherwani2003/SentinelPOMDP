# Operations runbook

## Configuration

Supported deployment settings:

```text
SENTINEL_OPERATIONS_BACKEND=postgres
SENTINEL_OPERATIONS_DATABASE_URL=<injected PostgreSQL URL>
SENTINEL_CHECKPOINT_MODE=postgres
SENTINEL_API_WORKERS=1
```

The URL and passwords belong in environment injection or a secret manager, never
Git. Candidate mode rejects SQLite, memory checkpoints, missing database URLs, and
more than one API process. PostgreSQL supports multiple independent worker
processes; the Compose file starts two. SQLite is for one local worker only.

## Starting and verifying

```powershell
docker compose --env-file .\infra\deployment.env `
  -f .\infra\deployment.compose.yaml config --quiet
docker compose --env-file .\infra\deployment.env `
  -f .\infra\deployment.compose.yaml up --build
uv run pytest -q -rs
```

Use `/health/live` for process liveness and `/health/ready` for required databases
and configuration. Authorized operators use `/api/v1/operations/health` and
`/api/v1/operations/summary`. A stale worker does not make the API process vanish;
it appears as `stale-or-not-started`.

## Alert assumptions

The API exposes indicators but does not run a continuous alert dispatcher. A local
operator should alert when any of these persists across two checks:

- oldest queued age over 300 seconds;
- any expired lease;
- reconciliation backlog above zero;
- worker heartbeat older than 60 seconds;
- failure rate above 5% after at least 20 terminal jobs;
- operational DB, Neo4j, or document storage unavailable.

Tune these assumptions for the workload and evidence review SLA.

## Recovery decisions

- `RETRY_WAIT`: an explicitly replay-safe handler will retry within its bound.
- `NEEDS_RECONCILIATION`: inspect the downstream graph/document result and journal;
  never change it to queued without confirming the effect.
- `CANCEL_REQUESTED`: wait for a safe boundary. It is not yet cancelled.
- `FAILED`: terminal. Correct the cause and submit a new request/key if appropriate.

For graph-success/metadata-failure, deterministic investigation resumes from its
checkpoint. Ingestion/Olist handlers rerun only their existing idempotent services.
Unknown non-idempotent steps are quarantined in `NEEDS_RECONCILIATION`.

## Known limitations

- Local API-key authentication, the request rate limiter, and the legacy security
  audit remain process-local; therefore multiple API processes are fail-closed.
- Only document ingestion, registered deterministic investigations, and authorized
  Olist batches have deployment worker handlers. Generic evaluation jobs are
  recorded but fail with `HANDLER_NOT_CONFIGURED` unless an operator installs a
  reviewed handler.
- Cancellation is cooperative and cannot interrupt an atomic database commit.
- Neo4j Community backup requires downtime; online enterprise backup was not tested.
- Metrics are pull-based summaries, not a continuous paging system.
- PostgreSQL operations and LangGraph checkpoints share one database in the local
  deployment; separate managed stores were not tested.
- No Groq/OpenAI call is made by the worker. External-provider evaluations remain opt-in.
