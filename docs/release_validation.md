# Public release-candidate validation

Scope: a locally tested portfolio/research demonstration, not production
certification or an already published release. The confirmed copyright-holder
identifier for original project material is AdnanSherwani2003; authorization for
Git actions remains pending. The
[architecture](architecture.md), [quickstart](quickstart.md),
[attribution](data_sources_and_attribution.md) and
[limitations](limitations_and_future_work.md) describe the supported boundaries.

## Preserved Implementation 20 results

| Run | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Working-tree offline | 322 | 0 | 23 |
| Fresh source export without private archive | 320 | 0 | 25 |
| Disposable live Neo4j/PostgreSQL full suite | 343 | 0 | 2 |

These are historical I20 source-tree results, not installed-wheel tests. The two
live-run skips were explicitly disabled paid providers. Exact sanitized counts
and skip reasons are in [test_matrix.json](../reports/implementation20/test_matrix.json).
Preparation results below are separate; historical counts are not silently
replaced by newer runs.

Actual local browser checks covered authentication, shipment support, unsupported
causal attribution, conflicting and missing evidence, evidence details, synthetic
procurement matching, invalid-pack rejection and worker health/completion.
Two explicitly synthetic result screenshots are public:
[supported shipment](../reports/implementation20/browser_pomdp.png) and
[missing evidence](../reports/implementation20/browser_missing_evidence.png).
Original-row Olist screenshots and raw operational traces remain private. The
[research summary](research_data_summary.md) publishes only aggregate acceptance.

## Synthetic recovery rehearsal

New restore storage matched 57 graph nodes and 56 relationships, one job, three
audit rows and ten checkpoint rows. Seven document files matched SHA-256; one
review decision and an active domain version were restored. Manifest verification
passed before restoration. Writers were quiesced and Neo4j Community dumping was
offline; research volumes were not mounted or overwritten. This is a bounded
rehearsal, not measured production recovery objectives or HA certification.

## Packaging correction and release preparation

The checkpoint audit found SQL migrations missing from the old wheel and sdist.
An isolated installed-wheel startup reproduced FileNotFoundError even though
source-tree tests passed. The narrow correction explicitly includes both SQL
migrations in package data. New regressions inspect both artifacts, rebuild from
sdist, install in isolated environments and exercise database/API initialization
without editable-source fallback. PostgreSQL startup is tested only against an
explicitly disposable opt-in database; optional skips remain visible.

Tests executed 2026-10-20; preparation review completed 2026-10-21 (Asia/Calcutta):

| Check | Result |
|---|---|
| Working-tree offline suite | 326 passed, 0 failed, 25 skipped; 175.87 s |
| Exact proposed public-source export | 324 passed, 0 failed, 27 skipped; JUnit suite time 106.988 s |
| Packaging with new disposable PostgreSQL | 6 passed, 0 failed, 0 skipped; 108.62 s |
| Initial packaging without PostgreSQL opt-in | 4 passed, 2 skipped; 52.04 s |
| README and architecture Mermaid blocks | 8 parsed with pinned Mermaid 12.2.0 |
| Diagram dependency advisory check | 0 reported vulnerabilities at verification time |
| Independent clean diagram installation | npm ci from the lockfile; 8 blocks parsed without existing node_modules |

The offline suite skips 17 live Neo4j cases, 4 existing PostgreSQL cases, 2 new
installed PostgreSQL cases and 2 paid providers. No optional skip is counted as
successful live execution. Packaging tests installed both a direct wheel and a
wheel rebuilt from sdist into separate virtual environments, using locked cached
runtime dependencies and source-fallback denial. Both initialized SQLite and
PostgreSQL, persisted/reopened jobs, enforced idempotency/tenant boundaries, and
served the synthetic API. The PostgreSQL container was newly created only for
these checks, then stopped and retained. Existing databases/volumes were not used.

The public-source export intentionally omitted the private archive, so its two
additional skips are archive-dependent cases. It used the existing locked Python
dependency environment while asserting imports came from the exported source;
the packaging regressions separately created genuinely isolated installations.
JUnit suite time is not the same as total command wall time. Local Node verification
used 24.14.0; configured remote CI uses Node 22 and has not been executed.

The initial Mermaid 11 pin had a low-severity transitive KaTeX advisory; the
development-only tool was upgraded to pinned Mermaid 12.2.0 before acceptance.
The remaining jsdom transitive deprecation warning is not a reported vulnerability.
No public push, remote CI run, production deployment, paid inference or predictive
model activation is implied by local verification.

## Confirmed copyright identifier and packaged notice (2026-10-21)

The owner confirmed **AdnanSherwani2003** as the preferred GitHub copyright-holder
identifier for original project material. The scoped [NOTICE](../NOTICE) is now
included in wheels, source distributions and wheels rebuilt from source
distributions. The official Apache-2.0 LICENSE remains byte-for-byte unchanged.
Neither the project notice nor the code license claims third-party code or Olist
data. See [attribution](data_sources_and_attribution.md).

The updated packaging suite passed **5 tests, 0 failed, 2 skipped in 153.82 s**.
Its two PostgreSQL cases required explicit opt-in. An attempted separate disposable
PostgreSQL rerun could not start because Docker's Linux engine was unavailable;
no new database was created. The earlier six-case live packaging result above is
historical, not a success claim for this notice update. The current artifacts
still passed resource, notice/license byte checks, isolated SQLite/API startup,
reopen, idempotency and tenant-denial tests. All eight diagrams parsed again and
the point-in-time npm advisory check reported zero vulnerabilities.

A new source export and genuinely fresh locked dependency environment then passed
the full suite: **325 passed, 0 failed, 27 skipped in 187.85 s** (pytest time;
dependency installation is additional). It installed 70 locked packages and
included NOTICE and the diagram-tool manifests without the private archive or
credentials. Its 27 skips are the live-store, private-archive and paid-provider
cases, including the two optional installed-PostgreSQL cases. Raw logs remain
private. No existing historical verification report was overwritten.
