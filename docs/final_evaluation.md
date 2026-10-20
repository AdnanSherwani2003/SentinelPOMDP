# Final evaluation report

## Executive summary

SentinelPOMDP demonstrably performs bounded, deterministic investigations over registered synthetic scenarios, retains contradictory evidence, validates provenance, enforces tenant scope, and abstains when claim-specific support is missing. It is not a validated general-purpose business decision system. All quantitative decision/calibration results below use synthetic models whose likelihoods were designed in code, not estimated from real operations.

Implementation 13 status is **partially complete**: the application package, image, offline benchmark, local container health, live Neo4j security/API path, and regression tests were verified. Live Groq was **not tested** because `RUN_LIVE_GROQ_TESTS` was not explicitly enabled, even though a credential was present. Production operation remains out of scope.

## Methodology

The final simulator benchmark used version `implementation-13-v1`, seed `13000`, 200 episodes for each of five hidden security states, and identical state/seed pairs for every policy. Each policy therefore ran 1,000 episodes. Ground truth was provided to the simulator and scoring harness only, never to the policy. The calibrated synthetic observation model and a balanced prior were used; this dataset is declared final-evaluation-only rather than a tuning set.

Policies were immediate terminal decision, fixed action order, greedy one-step information gain, one-step expected utility, and horizon-2 POMDP planning. The graph evaluation separately used the five supplier-delay demonstrations and deterministic fake language provider. API samples were warmed and local; they are not production network measurements.

Machine-readable aggregates are in `reports/final_benchmark.json`, per-episode data in `reports/final_benchmark.csv`, and the live graph API sample in `reports/live_neo4j_api.json`.

The pre-change offline baseline was 207 passed and 15 skipped. The final offline run was **217 passed, 15 skipped, 0 failed**; skips were 13 live-Neo4j tests and two opt-in paid-provider tests. With the existing Neo4j container credential supplied transiently, the final full run was **230 passed, 2 skipped, 0 failed**; only OpenAI and Groq paid-provider tests skipped. The focused security/API live gate was 2 passed. New Implementation 13 tests were 10 passed.

## Decision quality, cost and calibration

| Policy | Answer / abstain | Correct / wrong | Selective accuracy | Overall correct | Mean actions | Mean cost | Mean utility | Brier | Log loss | ECE | Runtime |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Immediate | 0 / 1,000 | 0 / 0 | 0.0% | 0.0% | 0.000 | 0.0000 | -0.2500 | 0.8000 | 1.6094 | 0.0000 | 0.032 s |
| Fixed order | 679 / 321 | 593 / 86 | 87.33% | 59.3% | 2.905 | 0.4129 | -0.3301 | 0.3241 | 0.6367 | 0.0203 | 0.127 s |
| Greedy information gain | 723 / 277 | 603 / 120 | 83.40% | 60.3% | 2.600 | 0.3676 | -0.4339 | 0.3666 | 0.7357 | 0.0344 | 0.613 s |
| Expected utility, H1 | 571 / 429 | 516 / 55 | 90.37% | 51.6% | 3.379 | 0.4648 | -0.3310 | 0.3257 | 0.6157 | 0.0349 | 1.372 s |
| POMDP, H2 | 598 / 402 | 540 / 58 | 90.30% | 54.0% | 3.274 | 0.4496 | -0.3001 | 0.3245 | 0.6131 | 0.0362 | 7.140 s |

Selective accuracy is accuracy among answered episodes. An abstention is safe but not a correct answer, which is why immediate abstention has zero task completion. Wrong-answer rates over all episodes were 8.6% fixed, 12.0% greedy, 5.5% H1 and 5.8% H2. The benchmark does not contain an independent label for when abstention is normatively required, so “appropriate” versus “inappropriate” abstention cannot be estimated without circularly adopting the policy’s own threshold.

Brier score and log loss assess the whole probability distribution; lower is better. ECE compares binned confidence with observed top-class accuracy. Immediate ECE is zero only because a balanced 20% prior happened to match balanced top-label frequency; that does not make the policy useful. These are simulator-calibration results and say nothing about real supplier frequencies.

Mean entropy reduction was 0 immediate, 1.3868 bits fixed, 1.3215 greedy, 1.4535 H1 and 1.4548 H2. Reducing entropy did not guarantee evidence sufficient for a claim.

## Planning value and ablations

Horizon 2 improved realized utility over horizon 1 by `0.03089` per paired episode; a seeded 1,000-resample paired bootstrap interval was `[0.00439, 0.05586]`. It answered 27 more episodes and produced 24 more correct answers, with three more wrong answers, 0.105 fewer actions and 0.0151 lower mean cost. It required 7.140 seconds versus 1.372 seconds—about 5.2 times the benchmark runtime.

This does not show universal superiority. Under the configured reward, universal immediate abstention had utility -0.2500, better than H2 at -0.3001, but no useful answers. The fixed baseline had nearly the same utility as H1 and ran much faster. In the three-case static graph comparison, fixed, H1 and H2 all produced one supported answer, two abstentions, cost 0.24 and utility 4.76; extra lookahead changed no result. In the multi-step graph scenario, H1 abstained without a tool call while H2 used two calls and still abstained. A separate illustrative model did show a horizon-dependent first-action shift.

The evidence-gate-off ablation is not a deployable option. Existing unit tests establish that a high posterior without support and contradictory benign evidence are vetoed. Removing that gate could increase coverage by redefining unsafe answers as allowed, so such output is not presented to users.

## Evidence, provenance and language boundary

| Case | Mapping | Outcome | Grounding result |
|---|---|---|---|
| Supplier A shipment late | `supplier_a_shipment_delay` | ANSWER | `VERIFIED_SUPPORTED`, two documents and two supporting records |
| Supplier A caused entire delay | `supplier_delay_causal_attribution` | ABSTAIN | `IRRELEVANT_SUPPORT`; lateness is not causal proof |
| Supplier B on time | `supplier_b_conflicting_delivery` | ABSTAIN | `CONFLICTED`; support and contradiction retained |
| Component A certified | `component_certification_missing` | ABSTAIN | `INSUFFICIENT`; absence is not proof of non-certification |
| Multi-source screening | `multi_investigation_screening` | ABSTAIN | `INSUFFICIENT` after bounded investigation |
| Stock-price question | none | UNSUPPORTED | No workflow or graph action |
| “What happened?” | none | CLARIFICATION_REQUIRED | No workflow or graph action |

All five registered cases used the deterministic fake provider, passed grounding validation, and used no explanation fallback. This verifies deterministic trust boundaries, not real-model language quality. The legacy `fact_sup_a_caused_delay` ID was inspected: its relation is the narrow factual `EXPERIENCED_DELAY` between supplier and shipment. The ID remains for compatibility and now carries a precise presentation label; causal attribution uses separate facts.

Live Groq: **NOT TESTED**. Attempted requests: 0; successful interpretations: 0; token usage/cost/latency: unavailable. The environment did not have the explicit `RUN_LIVE_GROQ_TESTS=1` authorization, so no paid call was made. Previous fallback observations are not generalized here.

## API performance

The warmed live-Neo4j/fake-provider sample contained 10 requests per path and preserved exact decision/belief/evidence/cost parity. API latency was median 76.50 ms, P95 90.32 ms, minimum 73.68 ms and maximum 106.05 ms. Median direct service time was 55.45 ms; protected service was 70.83 ms. Estimated median security overhead was 15.38 ms and HTTP/TestClient overhead 5.67 ms. The final request attributed 0.35 ms to planning, 19.47 ms to graph work, 0.31 ms to fake-model work and 68.46 ms to the protected request.

The separate in-memory/fake bounded-concurrency run used 12 sequential and 8 concurrent requests at concurrency 4. All 20 succeeded. Sequential median/P95 were 161.55/202.21 ms while tracing Python allocations; concurrent median/P95 were 634.35/670.48 ms and observed throughput was 6.07 requests/s. Peak traced Python allocation was 2,233,332 bytes. `tracemalloc`, TestClient, tiny samples and a development laptop make these diagnostic numbers, not capacity claims.

## Reliability and security

Verified behavior includes invalid/missing auth rejection, permissions, principal-derived tenant scope, cross-tenant graph/trace denial, privacy allowlisting, malformed requests, rate/budget/tool/horizon limits, duplicate correlation handling inside one process, operational database errors without belief updates, invalid structured output fallback, explanation-grounding fallback, conflicting/missing evidence, and live Neo4j protected API access.

The reliability suite explicitly verifies that a dead Neo4j endpoint returns `NOT_READY` and does not fall back to synthetic memory data. It also demonstrates that HTTP timeout is not cooperative cancellation: the response becomes 504 while its synchronous worker can continue. Retrying could duplicate downstream cost. Process restart loses authentication records, traces, idempotency entries, rate counters, metrics, audits and in-memory checkpoints.

Browser controls include no persistent key storage, same-origin assets, text-safe DOM rendering, CSP, `nosniff`, no-referrer and no-store headers. Deployment uses a non-root user, localhost API binding and no host Neo4j port. Missing controls include TLS termination, hosted identity/rotation, managed secrets, durable encrypted checkpoints/audits/idempotency, distributed rate limiting, monitoring/alerts, backup/recovery, multi-worker coordination and independent security assessment.

## Business readiness and data assumptions

Real onboarding requires authenticated source ingestion, entity resolution, domain hypotheses, claim definitions, typed tools, provenance rules, labeled data for likelihood calibration, cost/threshold elicitation, permissions, retention and human-review policy. Evidence hashes detect changes but not truth or authorship. Current models do not establish source independence, correlation, authenticity or the meaning of missingness empirically. The system cannot ingest arbitrary documents and automatically produce a validated POMDP.

## Conclusion

The system is a credible research prototype, working local demonstration, and controlled pilot candidate for trusted evaluation with human review. It is not ready for real production decisions. Its strongest demonstrated properties are explicit uncertainty, bounded mathematical planning, safe abstention, evidence provenance, claim specificity and deterministic authority boundaries. Its biggest gaps are empirical validation, operational identity/state/cancellation infrastructure, data onboarding, monitoring/recovery and independent assurance.
