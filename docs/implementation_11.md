# Implementation 11 — security, privacy, authentication, and authorization

## Architecture and status

Implementation 11 wraps Implementation 10 with a protected application facade. Priors, likelihoods, Bellman planning, evidence gates, graph query shapes, and grounding rules are unchanged.

```text
credential -> authenticator -> trusted principal -> permission + tenant checks
           -> request/rate limits -> external-provider policy
           -> Implementation 10 -> LangGraph/POMDP -> tenant-scoped graph tools
           -> citation scope check -> bounded audit -> authorized response
```

`InvestigationIntelligenceService` remains a trusted internal API. External transports should call `ProtectedInvestigationService`. A future FastAPI layer can adapt HTTP authentication to the same `Authenticator` protocol without putting framework concerns in the core.

## Principal, authentication, and credentials

**What?** A principal is the identity trusted after authentication. Authentication answers “who is calling?”

**Why?** A tenant named in a question is only untrusted text.

**How?** `LocalAPIKeyAuthenticator.issue()` creates an opaque 256-bit key, stores only a salted SHA-256 verifier, and returns the secret once. Verification performs constant-time comparisons. Keys support expiry, revocation, and replacement. Missing/invalid/expired/revoked credentials and disabled principals fail closed. Credential-free development auth requires explicit `enabled=True` construction.

**Connection and proof.** It runs before Implementation 10 and changes no POMDP code. Security tests cover all listed credential states and explicit development mode.

## Authorization, least privilege, and tenants

**What?** Authorization answers “what may this principal do?” Least privilege grants only necessary permissions.

**Why?** Identity alone must not grant investigation, evidence, provenance, trace, resume, audit, or admin access.

**How?** Permissions are `investigation:execute`, `evidence:read`, `provenance:read`, `trace:read`, `workflow:resume`, `audit:read`, and `admin`. Default is deny. Only `principal.tenant_id` reaches Implementation 10. A requested tenant is an equality assertion, never an override. Protected document, provenance, trace, and resume reads repeat authorization. Missing and wrong-scope resources share a generic error to prevent existence probing.

**Connection and proof.** Existing parameterized tenant-scoped graph queries and typed tools remain the data layer. Tests use both synthetic tenants, forged IDs, missing permissions, and trace ownership.

## Privacy and data minimization

**What?** Provider policy decides whether the question and minimized structured context may leave the process.

**Why?** Groq/OpenAI are external processors, and a question can itself be sensitive.

**How?** External processing defaults to disabled and uses an explicit provider allow-list. Denial happens before any model call. Allowed Implementation 10 prompts contain the question and scenario catalog, then a minimal outcome/reference summary—not raw documents, credentials, connection strings, or unrelated evidence. Citations are re-resolved in the authenticated tenant before release.

**Connection and proof.** OpenAI, Groq, and deterministic fake remain. Strict grounding/fallback is unchanged. A recording client proves blocked calls are zero and raw synthetic document bodies are absent from allowed payloads.

## Prompt injection and zero trust

Questions, source records, and model output never become authority. The LLM has no tool interface. Registry validation constrains interpretation. Tenant, permissions, horizon, budget, and limits come from deterministic code. LangGraph/POMDP chooses actions and beliefs. Grounding rejects changed decisions, probabilities, references, and unsupported prose, then falls back. Tests attempt tenant overrides, arbitrary Cypher, forced probability/ANSWER, and secret disclosure and compare exact mathematical outcomes.

## Limits and safe retry

The service bounds question length, planning horizon, tool calls, and the existing POMDP budget, plus a principal-scoped local requests/minute limit. Existing schemas cap traversal depth/results; providers cap output, timeout, and retries. Correlation IDs bind to a SHA-256 request fingerprint and principal. Exact retries return the earlier result without provider/tool calls; changed reuse is denied. Completed trace resume returns the same stored response without costs or Bayesian updates. These process-local controls need distributed replacements for multi-worker deployment.

## Auditing and checkpoints

Security audit events describe who attempted an operation and its allow/deny/error result; investigation traces describe mathematical actions and evidence. Audit fields are event/correlation IDs, UTC time, operation, outcome, stable reason, principal/tenant, and optional trace ID. Questions, credentials, evidence bodies, prompts, and provider responses are excluded. The sink is bounded and de-duplicates IDs. External share decisions are separately recorded.

Completed traces bind to principal and tenant. `trace:read` and `workflow:resume` are independent permissions. IDs cannot change ownership, and replay does not repeat execution. LangGraph `InMemorySaver` is process-local and non-durable. Durable deployment requires encryption, tenant-aware keys, server-generated IDs, access control on every read/write, retention/deletion, and distributed idempotency.

## Secrets and local infrastructure

- Provider secrets remain in `GROQ_API_KEY`/`OPENAI_API_KEY`; Neo4j uses `NEO4J_*`.
- `.env` files are ignored; `.env.example` has placeholders only.
- `SecurityConfiguration` defaults closed and validates provider policy/credential presence without revealing values.
- Never put credentials in prompts, state, checkpoints, errors, or audit records.
- Compose HTTP/Bolt ports are localhost-only and startup requires explicit `NEO4J_AUTH`. Set unique matching `NEO4J_AUTH` and `NEO4J_PASSWORD`. Remote Neo4j requires TLS/certificate verification.

## Reproduce (PowerShell)

```powershell
# From the repository root.
$env:RUN_LIVE_GROQ_TESTS = '0'
$env:RUN_LIVE_LLM_TESTS = '0'
uv run pytest -q
uv run python scripts/demo_security.py

# Optional local Neo4j with a user-chosen password.
$env:NEO4J_AUTH = 'neo4j/<unique-local-password>'
$env:NEO4J_PASSWORD = '<same-unique-password>'
docker compose -f infra/compose.yaml up -d
uv run pytest -q tests/test_security_live.py

# Paid Groq remains separately opt-in.
$env:RUN_LIVE_GROQ_TESTS = '1'
$env:SENTINEL_EXTERNAL_LLM_ENABLED = '1'
$env:SENTINEL_ALLOWED_LLM_PROVIDERS = 'groq'
uv run pytest -q -m live_groq
```

## Implementation 12 readiness and limitations

Principal/authenticator contracts, stable errors, permissions, privacy policy, limits, facade, and audit records are framework-independent. FastAPI must map safe errors, suppress credential-bearing access logs, configure trusted proxies/CORS, and use this same service.

Not provided: distributed rate/idempotency storage, durable encrypted checkpoint/audit storage, hosted identity/MFA, automated rotation, network perimeter, production TLS, data-residency workflow, or independent assessment. The known Groq explanation fallback remains a model-quality limitation; grounding is intentionally not weakened.

## Verification recorded 2026-10-17

| Check | Actual result |
|---|---|
| Pre-change checkout baseline | 157 passed, 13 skipped |
| New focused security suite | 23 passed |
| Complete offline regression | 180 passed, 14 skipped in 23.04s |
| In-memory six-case demo | Authorized ANSWER; cross-tenant and permission denied before model; injected Supplier B claim remained ABSTAIN/CONFLICTED; external call blocked with 0 calls; zero-budget ABSTAIN |
| Mathematical parity | Same scenario, actions, observations, posterior, decision, evidence references, and cost in direct/protected paths |
| Retry/resume | Same trace returned with no repeated model calls, tools, charges, or Bayesian updates |
| Local deterministic timing | Median direct 13.112 ms; protected 12.855 ms; delta -0.257 ms over 10 samples (noise-dominated, not a production benchmark) |
| Credential-shaped token scan | No Groq/OpenAI/GitHub/AWS credential-shaped matches |
| Compose validation | Passed with an explicit placeholder `NEO4J_AUTH`; ports remain localhost-only |
| Live Neo4j security | Skipped: Docker Desktop Linux daemon unavailable on this host |
| Paid Groq/OpenAI | Not run: opt-in flags deliberately disabled |

The current checkout does not reproduce the attachment's historical 169-test baseline; its actual pre-change baseline was 157/13. The 180/14 result is therefore reported without relabeling skipped tests as passes. Status is **PARTIALLY COMPLETE** until the new live Neo4j security test runs successfully against an available service. Core in-memory implementation and regressions are green.
