# Production-readiness matrix

Historical Implementation 13 readiness snapshot retained for context. Several gaps
below were subsequently implemented in I14–I19. Current release status and remaining
deployment restrictions are in [public validation](release_validation.md) and
[limitations](limitations_and_future_work.md); do not interpret the old matrix as current capability.

Statuses mean exactly: `IMPLEMENTED_AND_TESTED`, `IMPLEMENTED_NOT_FULLY_VERIFIED`, `PROTOTYPE_ONLY`, `NOT_IMPLEMENTED`, or `BLOCKED`.

| Capability | Status | Evidence / gap |
|---|---|---|
| Mathematical reasoning | IMPLEMENTED_AND_TESTED | Exact update, utility and Bellman tests pass; synthetic only. |
| Scenario configuration | PROTOTYPE_ONLY | Five manually registered supplier scenarios. |
| Empirical likelihood calibration | NOT_IMPLEMENTED | Likelihoods are hand-designed; no labeled business data. |
| General evidence ingestion | PROTOTYPE_ONLY | Typed synthetic ingestion exists; arbitrary document ETL/validation does not. |
| Neo4j graph retrieval | IMPLEMENTED_AND_TESTED | Live local graph/security/API tests passed. |
| Evidence provenance | IMPLEMENTED_AND_TESTED | Claim-specific document/evidence validation and conflict retention tested. |
| Tenant isolation | IMPLEMENTED_AND_TESTED | Direct, trace, evidence and live graph denial paths tested. |
| Authentication | PROTOTYPE_ONLY | Salted opaque local API-key records; no hosted identity or durable lifecycle. |
| Authorization | IMPLEMENTED_AND_TESTED | Principal-derived tenant and default-deny permissions. |
| External-provider privacy | IMPLEMENTED_AND_TESTED | Explicit enable plus allowlist; provider calls fail closed. |
| API reliability | IMPLEMENTED_NOT_FULLY_VERIFIED | Error contracts and bounded local concurrency tested; no long-duration soak. |
| Browser UI | IMPLEMENTED_AND_TESTED | Same-origin workflow and safe text rendering tested locally. |
| Checkpoint persistence | PROTOTYPE_ONLY | Process-local `InMemorySaver`. |
| Audit persistence | PROTOTYPE_ONLY | Bounded process-local metadata log. |
| Backup and recovery | NOT_IMPLEMENTED | Neo4j volume exists; no tested backup/restore procedure. |
| Rate limiting | PROTOTYPE_ONLY | Thread-safe process-local limiter; not distributed. |
| Idempotency | PROTOTYPE_ONLY | Correlation-scoped in-process replay; HTTP has no durable client idempotency key. |
| Model quality | IMPLEMENTED_NOT_FULLY_VERIFIED | Fake-provider boundaries tested; live Groq not authorized in this run. |
| Observability | PROTOTYPE_ONLY | Structured request logs and process-local tenant metrics; no exporter/alerts. |
| TLS/network security | NOT_IMPLEMENTED | Compose binds API to localhost; external TLS termination is required. |
| Operational deployment | IMPLEMENTED_NOT_FULLY_VERIFIED | Image and Compose validate/build; controlled local candidate only. |
| Monitoring and alerting | NOT_IMPLEMENTED | No external metrics backend or alert rules. |
| Load testing | PROTOTYPE_ONLY | Small local bounded-concurrency test only. |
| Independent security assessment | NOT_IMPLEMENTED | No third-party review or penetration test. |
| Human approval for high-stakes use | NOT_IMPLEMENTED | No approval workflow; outputs must not drive high-stakes action. |

## Classification

- Research prototype: **yes**.
- Local demonstration application: **yes**.
- Controlled pilot candidate: **yes, for trusted evaluation with human review**.
- Ready for real production use: **no**.

The principal blockers are real-data validation, empirical likelihood calibration, hosted identity and secret management, durable/distributed state, cancellation semantics, TLS, monitoring, backup/recovery, operational runbooks, and independent security review.

## Enterprise onboarding gap

A company would need to supply source systems and authorized records, an entity/relationship map, tenant and identity assignments, domain hypotheses, claim-specific evidence definitions, candidate investigation actions, labeled outcomes for likelihood calibration, decision costs, thresholds, review policy and retention rules. Engineers would then need to build authenticated ingestion, validate provenance and source integrity, estimate correlated/missing evidence behavior, register typed tools/scenarios, test tenant boundaries, and evaluate on a held-out labeled set. None of that is automatic document-to-POMDP generation today.
