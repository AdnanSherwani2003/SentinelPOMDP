# Implementation 18 — enterprise reliability

Status: **COMPLETE for the documented operational scope**, with unsupported and
unverified capabilities listed below.

Implemented and verified:

- versioned SQLite and PostgreSQL operational schemas;
- durable jobs, tenant/principal idempotency, leases, fencing, bounded retry/backoff;
- multi-worker PostgreSQL claims and concurrent idempotent submission;
- metadata-only persistent operational audit;
- atomically staged and resumable document ingestion using the existing review service;
- authorized, idempotent Olist batch handler (not executed against persistent Olist data);
- PostgreSQL LangGraph checkpoints bound to tenant, scenario, model version, and job ID;
- deterministic investigation recovery without repeated Bayesian evidence;
- cooperative cancellation and explicit reconciliation state;
- authenticated job API, component health, monitoring summary, and Operations UI;
- PostgreSQL/API/worker/Neo4j deployment configuration;
- checksum backup tooling and disposable PostgreSQL/Neo4j/document restore rehearsal;
- failure-injection tests for restart, crash, conflict, downstream uncertainty,
  cancellation, stale fencing, cross-tenant access, audit persistence, and retries.

Not supported:

- multi-process FastAPI while authentication/rate limiting remain local;
- automatic retry of ambiguous non-idempotent downstream effects;
- model-controlled tools, arbitrary scenarios, or arbitrary Cypher;
- automatic approval, model activation, public deployment, or paid-provider calls.

Not verified:

- online Neo4j Enterprise backup;
- production-scale load, high availability, and continuous external alert delivery.

The existing Olist research tenant was checked after the suite and remained exactly
602 entities, 545 facts, 215 evidence records, 2 documents, 1,850 relationships,
and 545 approved review records. No import was run.
