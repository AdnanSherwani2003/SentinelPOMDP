# Public portfolio validation

Scope: the published Implementation 20 portfolio/research system, not production
certification. The confirmed copyright-holder identifier for original project
material is AdnanSherwani2003. The
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
[supported shipment](../reports/implementation20/browser_pomdp.jpg) and
[missing evidence](../reports/implementation20/browser_missing_evidence.jpg).
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
used 24.14.0; remote CI uses Node 22. These preparation results predate the first
published workflow run described below.

The initial Mermaid 11 pin had a low-severity transitive KaTeX advisory; the
development-only tool was upgraded to pinned Mermaid 12.2.0 before acceptance.
The remaining jsdom transitive deprecation warning is not a reported vulnerability.
These historical local results do not imply production deployment, paid inference,
predictive model activation, or a successful remote CI run.

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

## Published checkpoint and cold-cache CI correction

Implementation 20 was fast-forwarded to public `main` at `7c9e246` on 2026-10-21.
The [first GitHub Actions run](https://github.com/AdnanSherwani2003/SentinelPOMDP/actions/runs/39496782338)
reported **323 passed, 25 skipped, 4 fixture setup errors**, not a green build.
Dependency installation, diagrams and static checks passed; later live/container
steps were skipped after the offline regression failed.

All four errors came from the direct-wheel and sdist-rebuilt-wheel installation
fixture's offline dependency resolution. Locked sync alone did not prepare the
cache used by that installation path. A separate fresh-cache reproduction failed
on already-locked `annotated-doc==0.0.5`; explicitly seeding the exported locked
runtime requirements made the same offline installation succeed. No new direct
dependency, mathematical change or weakened evidence gate was needed.

The focused correction adds an explicit hash-checked runtime-cache bootstrap and
a required, network-opted-in cold-cache CI regression. Subsequent artifact builds
and isolated installations retain networking disabled. See the
[developer commands](developer_guide.md). Any subsequent remote workflow result
is separate from local verification; the first run above remains a failure.

Local correction verification on 2026-10-21:

| Check | Passed | Failed / errors | Skipped |
|---|---:|---:|---:|
| Windows full suite with new disposable Neo4j/PostgreSQL and cold-cache opt-in | 354 | 0 / 0 | 2 |
| Fresh Linux source export, prepared cache, full offline suite | 328 | 0 / 0 | 28 |
| Windows clean-install script with a new cache and archive-free export | 328 | 0 / 0 | 28 |
| Dedicated Linux empty-cache regression | 1 | 0 / 0 | 0 |
| Dedicated Windows empty-cache regression | 1 | 0 / 0 | 0 |

The full suites collect 356 cases, four more than the original baseline: one
end-to-end cold-cache regression and three bootstrap/workflow boundary tests.
The Windows run skips only disabled paid providers. The archive-free Linux run
also skips unavailable live stores and two archive-dependent cases; its
network-opted-in cold-cache case ran separately rather than during the offline
phase. Runs overlap and must not be added as unique test counts. The cache tests
install both direct and sdist-rebuilt wheels with networking disabled and verify
SQLite/API startup without source fallback. The full live run also passes both
installed PostgreSQL cases. A separate direct offline install from the actual
`.tar.gz` source distribution also passed the resource, SQLite and API probes.
No research database or original volume was targeted.

All eight diagrams parse and both screenshots retain their original JPEG bytes
under accurate `.jpg` names. No dependency declaration or lockfile changed.
These are local Windows and disposable Linux-container results, not a new
GitHub Actions success. Check [Actions](https://github.com/AdnanSherwani2003/SentinelPOMDP/actions)
for the actual remote conclusion after an owner-approved correction push.
