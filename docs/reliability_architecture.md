# Reliability architecture

## What changed

Implementation 18 adds a small database-backed control plane beside the existing
Neo4j evidence plane. PostgreSQL is the supported deployment backend; SQLite is a
durable, serialized local/test backend and advertises `multi_worker_supported=false`.
The POMDP probabilities, actions, evidence gate, graph query allow-list, review
lifecycle, and tenant keys are unchanged.

```text
FastAPI --authorized enqueue/read/cancel--> operation_jobs (PostgreSQL)
                                                  |
                                      SKIP LOCKED + lease/fence
                                                  v
                                      bounded worker process
                                         |              |
                                  staged documents   LangGraph checkpoints
                                         |              |
                               existing review service  deterministic POMDP
                                         \              /
                                               Neo4j
```

## Major components

### Durable job and migration tables

**What:** Versioned PostgreSQL/SQLite tables for jobs, step journals, audit events,
worker heartbeats, and workflow checkpoint metadata.

**Why:** Python memory vanishes on restart. A durable state machine keeps the
identity, tenant, request fingerprint, attempt count, and final result available.

**How:** A transaction creates each job. Idempotency is unique within
tenant + principal + operation type. PostgreSQL uses `INSERT ... ON CONFLICT` and
`FOR UPDATE SKIP LOCKED`; SQLite uses `BEGIN IMMEDIATE` and is limited to one
worker. The migration is repeatable and records schema version 1.

**Failure prevented:** Lost jobs, duplicate submissions, and two workers executing
one active job.

### Leases, fencing, retry, and reconciliation

**What:** A claim has an expiry and monotonically increasing fencing token.

**Why:** A worker can pause or die after another worker has recovered its job.

**How:** Every progress/final write must match job ID, worker ID, and fencing token.
Expired replay-safe jobs return to `RETRY_WAIT` within their retry bound. Ambiguous
side effects move to `NEEDS_RECONCILIATION`; they are never blindly repeated.

**Failure prevented:** A stale worker overwriting a newer result, infinite retries,
and false success after an unknown downstream outcome.

### Idempotent ingestion journal

**What:** Upload bytes are atomically staged outside the job payload. The job keeps
an opaque tenant-scoped upload ID and checksum. The handler calls the existing
Implementation 14 ingestion/review service.

**Why:** Raw documents and credentials do not belong in queue rows, while a crash
must not lose accepted bytes.

**How:** The journal records step input fingerprints. Document ingestion is marked
resumable because the existing content-hash duplicate check is idempotent. It only
creates review candidates; it does not approve or publish them. Olist batches use
the existing authorized reviewer workflow and idempotent importer.

**Failure prevented:** Duplicate documents/candidates, lost provenance, invented
review approvals, and changed input during recovery.

### Durable deterministic investigation

**What:** PostgreSQL-backed LangGraph checkpoints for explicit registered scenario
IDs. The job worker does not call an LLM or grant model-controlled tools.

**Why:** A completed graph checkpoint can exist before the operation result is
written. Re-running Bayesian observations would be mathematically wrong.

**How:** Resume validates tenant, scenario ID, and model version before invoking the
next graph node. A completed checkpoint is returned unchanged. Checkpoint state
omits evidence text and keeps trusted IDs plus deterministic state. The worker uses
the job ID as thread ID.

**Failure prevented:** Cross-tenant resume, resuming under another model, and
applying the same observation twice.

### Cooperative cancellation

**What:** `CANCEL_REQUESTED` is distinct from `CANCELLED`.

**Why:** Python cannot safely kill arbitrary code at an HTTP timeout.

**How:** Queued work cancels immediately. Running handlers check at safe boundaries;
only then does the worker record `CANCELLED`. Loss of a cancelling worker becomes
`NEEDS_RECONCILIATION`.

**Failure prevented:** Reporting cancellation while an atomic downstream action may
still be running.

### Security and observability

Job submit/read/cancel/summary permissions are independent and operation-specific
permissions are checked again at enqueue. Tenant scope is taken only from the
authenticated principal. Payload keys that resemble credentials are rejected.
Operational audits are metadata-only relational rows; they are durable but are not
cryptographically tamper-proof. Candidate mode fails closed unless PostgreSQL and
PostgreSQL checkpoints are configured. Multiple API processes remain disabled
because authentication and rate limiting are still process-local.

`/api/v1/operations/summary` reports state counts, retry count, failure rate, mean
terminal latency, oldest queue age, expired leases, reconciliation backlog, and
fresh workers. `/api/v1/operations/health` separately reports the operational DB,
Neo4j, writable document store, worker heartbeat, queue, and configuration.

## Scientific boundary

Reliability changes when and how deterministic work resumes, not the mathematical
model. No priors, likelihoods, thresholds, action costs, action selection, evidence
gate, Olist temporal cutoff, or model approval status is changed. Historical lookup
remains distinct from prospective prediction.
