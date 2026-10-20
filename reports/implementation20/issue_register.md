# Implementation 20 issue register

Historical audit register; Implementation 20 was subsequently published on
2026-10-21. See [current validation](../../docs/release_validation.md) for the
first remote CI failure and the focused cold-cache correction.

| ID | Severity | Component / evidence | Risk | Correction / verification | Disposition |
|---|---|---|---|---|---|
| I20-01 | Critical | Legacy POST company-data/domain-packs checks APPROVED but not ACTIVE; author can supply lifecycle state | Unauthorized activation/approval | Draft-only uploads on both routes; negative API regression | FIXED; exploit regressions and full live suite pass |
| I20-02 | High | pytest is an optional extra, while documented uv sync and CI do not request it | Fresh setup cannot reliably run tests | Locked dev dependency group; isolated installation/test | FIXED; fresh install 320 passed / 25 skipped |
| I20-03 | High | check_secrets excludes reports and does not inspect Git history | Incomplete release secret audit | Redacted history/report scan; explicit staging exclusions | ADDRESSED; bounded scan, not a universal secret guarantee |
| I20-04 | Medium | Tracked pyc and egg-info; most later milestones untracked | Incomplete or contaminated release | Owner-approved checkpoint includes source and removes generated paths from the index while preserving local files | RESOLVED at HEAD; old generated history retained by owner decision |
| I20-05 | Medium | No LICENSE file | Public release licensing unresolved | Owner selected Apache-2.0; LICENSE and package metadata added | RESOLVED; wheel includes LICENSE |
| I20-06 | Medium | architecture_final and production_readiness describe pre-I18 persistence | Misleading capability claims | Current architecture/readiness cross-references; preserve historical reports | ADDRESSED in current guides |
| I20-07 | Medium | Ignore rules omit SQLite WAL/SHM and private-deployment.env | Local artifacts could be staged | Extend ignore/container exclusions, inspect tracked paths | FIXED; owner-approved index-only generated cleanup completed |
| I20-08 | Medium | API authentication, rate limits and synchronous traces remain process-local | Unsafe multi-instance deployment claim | Retain single API process, validate configuration, document independent workers | CONSTRAINED and tested; not a distributed security implementation |
| I20-09 | Low | README and generated PKG-INFO trailing blank lines | Whitespace check failure | Refine README; normalize only final blank lines in generated metadata | FIXED; final whitespace check |
| I20-10 | Medium | Three I18 external synthetic artifacts and I19 ignored demo stores retained | Release hygiene / accidental inclusion | Verify existence and exclude; no deletion authorized | VERIFIED and excluded; retained recoverably |
| I20-11 | High | Docker worker inherits API HTTP healthcheck; controlled Compose --wait cannot succeed | Documented full-stack startup fails | Disable inapplicable worker HTTP check; use durable heartbeats; rerun actual stack | FIXED; full stack startup and worker job pass |
| I20-12 | High | Legacy belief helpers accepted negative/NaN/infinite values | Invalid posterior/entropy from malformed model inputs | Add finite/nonnegative/normalized input checks; retain valid mathematics and legacy grid zero-weight fallback; mathematical regression | FIXED; valid-input regression and reference Bayes pass |
| I20-13 | Critical | Completed workflow checkpoint returned to unfinished job without current source validation | Withdrawn evidence could release a stale supported answer | Revalidate original answer references on return/resume, abstain without another Bayesian update | FIXED; memory and reopened PostgreSQL checkpoint tests pass |
| I20-14 | High | EvidencePolicy checked existence of relevant facts but not the full required set | Partial support could satisfy a multi-fact claim | Require the declared fact set; focused policy regression | FIXED; focused and full live suite pass |

The owner separately approved the reviewed local checkpoint and a non-force push
to public main. That approval does not authorize tags, GitHub Releases, deployment,
restoration into existing data or paid-provider calls. Portfolio readiness and
production readiness remain separate outcomes.
