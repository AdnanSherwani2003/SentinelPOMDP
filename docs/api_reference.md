# SentinelPOMDP local API reference

The API uses JSON under `/api/v1`. Protected routes require `Authorization: Bearer <SENTINEL_API_KEY>`. Credentials must not be placed in URLs, logs, or browser storage.

This table describes the original synchronous investigation surface. Current
durable jobs and domain governance are documented in operations_runbook.md and
domain_pack_schema.md. Both `POST /api/v1/domains` and the legacy
`POST /api/v1/company-data/domain-packs` accept only DRAFT/VALIDATED packs.
Neither upload can assign reviewer metadata or replace an already reviewed
version. Approval and activation require the protected lifecycle endpoints.

| Method | Route | Authentication | Purpose |
|---|---|---|---|
| GET | `/health/live` | Public | Process liveness; does not claim database readiness |
| GET | `/health/ready` | Public | Generic readiness for configured auth/provider/backend |
| GET | `/api/v1/session` | Required | Safe principal, tenant, and permission summary |
| POST | `/api/v1/investigations` | `investigation:execute`, `evidence:read`, `provenance:read` | Run the sole authoritative protected investigation path |
| GET | `/api/v1/investigations/{id}` | `trace:read`, same principal and tenant | Retrieve a retained completed result |
| GET | `/api/v1/investigations/{id}/trace` | `trace:read`, same principal and tenant | Retrieve sanitized mathematical steps and workflow phases |
| GET | `/api/v1/evidence/{id}` | `evidence:read`, authenticated tenant | Retrieve evidence and source metadata |
| GET | `/api/v1/provenance/{fact_id}` | `provenance:read`, authenticated tenant | Retrieve a verified fact provenance chain |
| GET | `/api/v1/metrics/summary` | `investigation:execute` | Tenant-only process-local counters and timings |
| GET | `/api/v1/audit` | `audit:read` | Tenant-filtered security audit records |

The investigation request accepts only `question` and an optional bounded `planning_horizon` (`0..2`). Tenant, prior, likelihoods, probabilities, graph actions, arbitrary Cypher, tool count, and budget cannot be supplied by clients.

Successful ANSWER and completed ABSTAIN results return HTTP 200. `status` distinguishes `ANSWER`, `ABSTAIN`, `BUDGET_EXHAUSTED`, `CLARIFICATION_REQUIRED`, and `UNSUPPORTED_REQUEST`.

Errors use:

```json
{
  "code": "ACCESS_DENIED",
  "message": "Resource unavailable or access denied",
  "correlation_id": "server-generated UUID"
}
```

| HTTP | Representative code |
|---|---|
| 401 | `AUTHENTICATION_FAILED` |
| 403 | `ACCESS_DENIED`, `EXTERNAL_PROCESSING_DENIED` |
| 422 | `INVALID_REQUEST` |
| 429 | `RESOURCE_LIMIT_EXCEEDED` |
| 502 | `PROVIDER_FAILURE` |
| 503 | `NOT_READY`, `DATABASE_UNAVAILABLE`, `SECURITY_DENIED` |
| 504 | `INVESTIGATION_TIMEOUT` |
| 500 | `INTERNAL_ERROR` |

Every response receives `X-Correlation-ID`, `Cache-Control: no-store`, a restrictive Content Security Policy, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: no-referrer`. CORS is not enabled.
