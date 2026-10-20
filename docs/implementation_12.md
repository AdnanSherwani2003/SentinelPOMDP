# Implementation 12 — FastAPI, web interface, and observability

## Architecture

```text
same-origin browser UI
  -> Bearer API key (page memory only)
  -> FastAPI validation and safe error mapping
  -> Implementation 11 ProtectedInvestigationService
  -> Implementation 10 interpretation/grounding
  -> Implementation 9 LangGraph
  -> Implementations 1–8 planner, Bayesian update, graph tools, evidence gate
  -> sanitized API response and visual timeline
```

There is one POST investigation route and one authoritative reasoning implementation. FastAPI never calculates a posterior, chooses an action, constructs Cypher, changes a budget, or bypasses the evidence gate.

## Backend and frontend

The **backend** is Python code that validates HTTP requests, authenticates the caller, invokes the protected service in a worker thread, maps safe errors, and serializes Pydantic response models. Dependency injection means tests can supply an in-memory repository, fake LLM, readiness checker, and metrics store without global live connections.

The **frontend** is same-origin HTML/CSS/JavaScript with no Node build. It holds the API key in one JavaScript variable, clears the password input immediately after authentication, never calls `localStorage`/`sessionStorage`, and removes the variable on “Clear key.” Local HTTP is development-only; remote use requires TLS.

The page includes connection/provider/session status, example questions, accessible validation/loading states, distinct ANSWER/ABSTAIN/error treatment, initial-to-final belief bars, evidence categories that do not rely on color alone, authorized evidence details, an investigation timeline, and expandable timings/trace identifiers. All server content is inserted with `textContent`, not untrusted HTML.

## HTTP flow using the shipment example

1. The browser sends `POST /api/v1/investigations` with its transient Bearer key and question.
2. FastAPI validates the body and creates a server-side correlation UUID.
3. The Implementation 11 authenticator resolves the trusted principal and tenant; permissions/privacy/limits are checked.
4. Implementation 10 maps the text to a registered scenario.
5. LangGraph asks the existing POMDP planner for an action, the typed graph tool retrieves tenant-scoped evidence, and the existing Bayesian update changes `shipment_delayed` from `.55` to `.88691`.
6. The evidence gate approves the factual answer; grounding validates the explanation.
7. FastAPI projects existing fields into the public schema and the UI draws them. It does not recompute `.88691`.

## Authentication, authorization, and privacy

`SENTINEL_API_KEY` is registered as a salted verifier at startup and is not retained by the authenticator. Missing, invalid, expired, and revoked credentials return 401. Evidence/provenance/trace/audit routes call their corresponding protected service methods. A principal cannot pass a tenant field through any public request.

External providers require all of: selecting `groq` or `openai`, configuring the correct provider credential, enabling `SENTINEL_EXTERNAL_LLM_ENABLED=1`, and allow-listing the provider. Otherwise readiness or the protected privacy policy fails closed. The default is the deterministic fake and needs no paid call. The UI displays provider/model and whether deterministic explanation fallback occurred.

## Observability

- Structured JSON application logs contain correlation ID, method, route, HTTP status, and duration. Bodies, questions, authorization headers, evidence content, and model output are excluded.
- Tenant-scoped in-process metrics count outcomes, fallbacks, tool calls, mathematical investigation cost, and request/planner/graph/model time. Mathematical cost is labeled as utility-cost units, never currency.
- Trace responses project existing investigation steps and LangGraph phases. Internal state and raw tool/provider payloads are not exposed.
- Metrics, traces, retained investigations, API-key verifiers, and audits are process-local and disappear on restart.

## Health and failure behavior

Liveness only means the API process is running. Readiness verifies startup configuration and the selected backend. Explicit Neo4j mode never falls back to memory. Authentication failures are 401, access/privacy denials 403, validation 422, throttling 429, provider failures 502, database/not-ready failures 503, and API timeout 504. A legitimate evidence-gated ABSTAIN is HTTP 200.

The request timeout bounds the client wait, but Python cannot forcibly stop an already-running synchronous provider thread. Provider and database timeouts remain the deeper execution bounds, and the correlation reservation prevents an immediate duplicate execution.

## Local startup on Windows

Default offline in-memory/fake mode:

```powershell
# From the repository root.
$env:SENTINEL_API_KEY = '<your 32+ character high-entropy local key>'
$env:SENTINEL_BACKEND = 'memory'
$env:SENTINEL_LLM_PROVIDER = 'fake'
$env:RUN_LIVE_GROQ_TESTS = '0'
$env:RUN_LIVE_LLM_TESTS = '0'
uv run uvicorn sentinel_pomdp.api.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, enter the same key, and press “Use key.” Do not use `--host 0.0.0.0` without a reviewed TLS-capable boundary.

Explicit Neo4j mode:

```powershell
$env:NEO4J_URI = 'bolt://localhost:7687'
$env:NEO4J_USER = 'neo4j'
$env:NEO4J_PASSWORD = '<configured database password>'
$env:SENTINEL_BACKEND = 'neo4j'
uv run uvicorn sentinel_pomdp.api.app:app --host 127.0.0.1 --port 8000
```

Groq additionally requires `GROQ_API_KEY`, `SENTINEL_LLM_PROVIDER=groq`, `SENTINEL_EXTERNAL_LLM_ENABLED=1`, and `SENTINEL_ALLOWED_LLM_PROVIDERS=groq`. This makes paid/external inference explicit.

## Production limitations and Implementation 13

This remains a local prototype: one configured identity per process, no TLS termination, no hosted identity/MFA, no CSRF-protected cookie session (Bearer key is transient instead), no distributed rate limiter/idempotency, no durable result/metrics/audit/checkpoint store, no multi-worker coordination, and no penetration/load/accessibility audit. Implementation 13 should address deployment configuration, secure session/identity integration, durable tenant-aware storage, distributed controls, TLS/reverse-proxy hardening, monitoring export, broader browser accessibility testing, and performance/security benchmarks.

## Verification recorded 2026-10-17

| Check | Actual result |
|---|---|
| Pre-change Implementation 11 baseline | 180 passed, 14 skipped in 16.05s |
| New offline API/UI contract tests | 27 passed |
| Complete suite | 207 passed, 15 skipped in 19.70s |
| Live Neo4j API | Skipped because configured Neo4j was unavailable in this process |
| Paid Groq/OpenAI | Skipped intentionally; opt-in flags were disabled |
| In-memory HTTP demo | 200 web page; ANSWER/VERIFIED_SUPPORTED; three correct ABSTAIN cases; cross-tenant evidence 403 |
| Real browser workflow | Authentication, question submission, 88.7% posterior chart, timeline, evidence modal, and key clearing visibly verified |
| CLI/protected/API parity | True for scenario, action/observation trace, posterior, decision, citations, and mathematical cost |
| 10-sample local medians | Direct 29.429 ms; protected 29.416 ms; HTTP 34.108 ms; HTTP overhead about 4.693 ms |
| One authoritative API trace sample | Planner 0.432 ms; graph 0.108 ms; fake-model 0.082 ms; protected request 29.824 ms |

The timing sample uses the deterministic fake and in-memory graph on one local run. The small negative direct-to-protected delta is measurement noise, not a claim that security improves performance.

Status is **PARTIALLY COMPLETE** because the complete in-memory application and real browser path work, while the new live Neo4j API test could not run without configured database connectivity. No skipped test is reported as passed.
