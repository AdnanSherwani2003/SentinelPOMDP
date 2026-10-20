# SentinelPOMDP prototype threat model

## Scope and claim

This model covers the framework-independent protected service in Implementation 11. It verifies deterministic controls against defined synthetic attacks. It is not a production certification, penetration test, hosted-identity review, or network audit. Python code with unrestricted in-process repository access remains trusted internal code and can bypass the facade.

## Assets and trust boundaries

Assets are tenant evidence, facts, documents, provenance, investigation histories, belief states, checkpoints/traces, provider and database credentials, LLM requests/outputs, and audit records.

The caller is untrusted. Authentication converts an opaque credential into a trusted principal. Authorization binds that principal to one tenant and fixed permissions. Questions, documents, and all LLM output remain untrusted data. The graph repository and deterministic POMDP engine are trusted internals. Groq/OpenAI are external data processors; Neo4j is a separate storage boundary.

## Threats, controls, and residual risk

| Threat | Impact | Implemented control | Verification | Residual risk |
|---|---|---|---|---|
| Impersonation/stolen key | Unauthorized access | 256-bit opaque keys, salted verifier, constant-time comparison, expiry/revocation/replacement | Authentication tests | Process-local store; no MFA/hosted identity |
| Forged tenant | Cross-tenant disclosure | Tenant only from principal; mismatched requested tenant denied before LLM | Spoof/cross-tenant tests | Trusted internal Python may use legacy interfaces |
| Missing permission | Unauthorized operations | Explicit default-deny permissions at facade | Permission matrix | Repositories are internal, not capability-secured |
| Prompt injection | Policy/math manipulation | No model tools; registered scenarios; trusted tenant; deterministic planner/grounding | Injection/parity tests | Model prose may be poor and fall back |
| Malicious document | Tool/secret execution | Documents are inert; raw content excluded from provider prompts | Existing malicious-memo and privacy tests | Upstream ingestion moderation is out of scope |
| Provider oversharing | Confidentiality loss | External calls default deny; provider allow-list; minimized structured context | Blocked-call/payload tests | The question itself may be sensitive |
| Fabricated citation/forced answer | Incorrect conclusion | Citation allow-list, grounding validation, deterministic fallback, post-response scope check | Grounding/security tests | Real Groq prose currently uses fallback |
| Resource abuse | Availability/cost | Input/horizon/tool/budget bounds, existing graph bounds, provider limits, local rate limit | Limit/tool tests | Rate limit is not distributed |
| Retry/replay | Duplicate charge/update | Correlation fingerprint cache; principal-bound completed replay | Retry/resume tests | Cache is process-local and bounded |
| Trace guessing | History disclosure | Trace bound to principal+tenant; identical errors for missing/wrong scope | Trace tests | `InMemorySaver` is not durable/encrypted |
| Logs/errors leak secrets | Credential compromise | Metadata-only bounded audit; stable safe errors | Redaction tests | Exception causes visible to trusted in-process code |
| Database failure | False Bayesian evidence | Operational errors are not claim observations; facade fails safely | Existing failure tests | No exhaustive chaos test |
| Remote Neo4j exposure | Database compromise | Compose ports bind to localhost; credential configuration is required; parameterized tenant queries | Inspection/live tests | Local Bolt without TLS is unsafe off-host |

## Audit retention

`BoundedAuditLog` retains at most 1,000 events by default in memory and evicts the oldest. Events contain IDs, UTC time, operation, outcome, reason code, principal/tenant IDs, and optionally a trace ID. They exclude credentials, complete questions, raw evidence, prompts, provider responses, and connection strings. Data disappears at process exit. Production needs append-only centralized storage, access controls, retention/deletion rules, clock integrity, and tamper resistance.

## Assumptions and untested areas

- The host and dependencies are trusted and patched.
- TLS, firewalling, a secret manager, automated rotation, external penetration tests, distributed throttling/idempotency, SIEM, durable encrypted checkpoints, data-residency review, and hosted identity are not implemented.
- Local Compose binds `127.0.0.1` and requires an explicit `NEO4J_AUTH`; any remote deployment still requires network and TLS review.
- Unit tests demonstrate the defined cases, not absence of every vulnerability.
