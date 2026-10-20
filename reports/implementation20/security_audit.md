# Final security audit

Scope: code/route review, negative tests, actual local HTTP/browser requests,
disposable live Neo4j/PostgreSQL tests, source/report/history scan and deployment
inspection. This is an engineering audit, not independent security certification.

Confirmed defects corrected:

1. Legacy domain upload accepted ACTIVE packs without the approval permission.
   Both upload routes now accept drafts/validated drafts only and share validation.
2. Uploaded drafts could replace reviewed lifecycle metadata. Reviewed versions
   cannot be overwritten through either upload route; reviewer fields are assigned
   by authenticated lifecycle actions.
3. Known concurrency environment settings could conflict with process-local API
   security assumptions. The launcher fixes one API worker and settings incorporate
   WEB_CONCURRENCY as well as SENTINEL_API_WORKERS. Arbitrary external multi-replica
   launch commands remain outside the supported profile.
4. A completed checkpoint could release an ANSWER after a source was withdrawn
   while its job was unfinished. The final return/resume gate rechecks original
   source references; failures yield ABSTAIN / REVALIDATION_REQUIRED. No posterior
   update, tool action or action cost is repeated.
5. A multi-fact evidence policy could accept partial fact coverage. Every declared
   required fact is now required.

The exploit regressions were first observed failing before correction. Current
security counts and all skips are machine-derived in test_matrix.json.

Verified existing boundaries: opaque key validation, expiry/revocation tests,
principal-derived tenant, permission checks, protected evidence/source details,
job ownership/cancellation, model review, checkpoint scope, upload limits/path
validation, source withdrawal/supersession, contradiction retention, source-group
deduplication, and LLM grounding fallback. The actual demo's other-tenant evidence
request returned HTTP 403 ACCESS_DENIED. Missing HTTP authentication returned 401.

No model-controlled tools, executable domain fields, unrestricted Cypher, or model
parameter/authorization controls were added. Provider flags remained disabled.
No paid API call was made. Local secret values were not printed in verification
results, screenshots, audit reports or Git history scan output.

The initial secret scanner's reports/history gap is covered by audit_release.py;
its bounded pattern and configured-value limitations are stated. Ignore rules and
the proposed manifest exclude local credentials, source documents, raw archives,
SQLite sidecars and backups. Tracked generated files still need an approved index
cleanup; the milestone intentionally does not stage or untrack them automatically.

Remaining restrictions: process-local authentication/throttling/synchronous traces,
single API process, local filesystem metadata concurrency limits, no public TLS
profile, no independent penetration test, no production HA or continuous external
alert delivery. Backup media contains evidence and needs appropriate access control.
These are visible portfolio/controlled-demo limits rather than hidden certification.
