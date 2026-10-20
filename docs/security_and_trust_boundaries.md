# Security and trust boundaries

The supported profile is one API process on localhost. Salted opaque credential
verifiers, expiry/revocation, tenant-derived authorization and endpoint permissions
are tested locally. Authentication records and rate counters remain process-local;
restarts re-provision the configured demo key. This is not a distributed identity
service. The supplied launcher fixes one worker, Compose fixes one API worker, and
WEB_CONCURRENCY/SENTINEL_API_WORKERS values above one fail validation. Do not launch
extra API replicas or override the supported launcher with multiple worker flags.

The final audit corrected a legacy domain upload bypass. Neither upload endpoint
can now accept APPROVED/ACTIVE models, fabricated reviewer metadata, or a draft
overwriting a reviewed version. Review/activation remain separate authenticated
actions. A domain file cannot run Python, shell, expressions or arbitrary Cypher.
Registered adapters must declare their full required tool bundle.

Document uploads have size/type/uncompressed bounds and safe storage identifiers.
Sources retain hashes, exact locations, review status and tenant scope. Withdrawn
evidence, missing support and conflicting current versions fail closed. Multiple
copies in one source group do not create independent support. Synthetic fixture
helpers are controlled engineering setup, not enterprise evidence approval.

An LLM is an untrusted interpretation/explanation helper. It cannot select tools,
edit probabilities, bypass source gates, grant tenant access or activate models.
External inference needs explicit enablement, provider allowlist and credentials.
Default tests and the demo use fake inference. No paid call was made during I20.

Operational payload validation rejects credential-like fields. Job and checkpoint
access checks bind tenant/scenario/model version. Audit records contain metadata;
they are not a cryptographically immutable ledger. Synchronous traces may contain
authorized evidence and require access control; durable operation records and
LangGraph checkpoints have a distinct persistence lifecycle.

Before releasing a probabilistic ANSWER, including a cached checkpoint result,
the workflow revalidates its original source references. Withdrawn/changed/unavailable
support forces ABSTAIN / REVALIDATION_REQUIRED without another probability update,
investigation call, or action charge. The stored historical trace remains distinguishable
from this current safety decision. Every fact in a claim's required set must be supported.

The release audit scans working files, reports and reachable Git blobs for key
patterns and configured secret values, emitting paths only. This is a bounded
heuristic, not a guarantee that no secret has ever existed. Local ignored demo
credential files are expected; do not stage or publish them. API keys, raw evidence,
database dumps and browser profile stores are excluded from release materials.

Remaining controls for any public/company deployment include shared identity and
throttling, TLS, deployment-specific key storage, real-data validation, monitoring,
retention/restore policies and independent security review. SentinelPOMDP is an
investigation research project; these controls do not make it a cybersecurity product.
