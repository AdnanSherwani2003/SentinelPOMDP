# Scientific evaluation summary

This document consolidates preserved artifacts; it does not relabel historical runs
as new experiments. Real-world POMDP investigation superiority remains **NOT
EVALUABLE** from Olist, which lacks outcomes for unperformed investigation actions.
See [data sources and attribution](data_sources_and_attribution.md): Olist is
separately CC BY-NC-SA 4.0 licensed; raw rows and model weights are not distributed.

## Synthetic policy experiment (Implementation 13)

Source: reports/final_benchmark.json, synthetic_benchmark. Seed 13000, 200 episodes
per state, five states, 1,000 episodes per policy. Labels score results after each
episode and are not policy inputs. Assumptions are the configured simulator,
observation likelihoods, action costs and reward function.

| Policy | Coverage | Selective accuracy | Mean utility | Runtime seconds |
|---|---:|---:|---:|---:|
| Immediate abstention | 0 | N/A | -0.250000 | 0.0323 |
| Fixed order | .679 | .87334 | -.330125 | .1271 |
| Greedy information gain | .723 | .83402 | -.433873 | .6129 |
| Expected utility h1 | .571 | .90368 | -.331003 | 1.3720 |
| POMDP h2 | .598 | .90301 | -.300110 | 7.1399 |

Immediate abstention had the best average utility under these rewards. The paired
h2-minus-h1 utility difference was .0308925, bootstrap 95% interval
[.004385, .0558575], 1,000 resamples. That comparison does not reverse the abstention
finding. The historical artifact encodes selective accuracy as zero when no answers
exist; N/A is the meaningful presentation. Simulator unsupported-answer counters do
not establish real graph grounding; those checks have separate integration tests.

## Calibration framework (Implementation 15)

The synthetic representative pilot supports independent label-review metadata,
chronological group splits, Dirichlet smoothing, count-based priors/likelihoods,
validation threshold selection and held-out calibration diagnostics. The retained
test set has 12 cases; investigated policies all have coverage .5, selective
accuracy 5/6 and Brier .281952. Its one-action logs cannot identify differences among
investigation policies. Independent-review metadata in a synthetic fixture is not
independent real-company labeling. Small subgroups are marked INSUFFICIENT_DATA.

## Real historical Olist (Implementations 16/17)

Historical date comparison is a factual lookup with reviewed CSV-row provenance.
The archive has 99,441 orders. Prediction-eligible: 96,221; absent delivery dates:
2,965. The mutually exclusive additional exclusions are 249 invalid date orderings
and 6 non-delivered final statuses: 96,221 + 2,965 + 249 + 6 = 99,441. Thus the
additional difference of 255 is fully accounted for. The temporal availability
rules are preserved in the Olist implementation reports. Outcome labels, final status, post-delivery
reviews and future seller outcomes are excluded before the decision-time cutoff.

Verified against reports/olist/implementation17/baseline_comparison.json:

| Candidate / snapshot | Cases | Brier | Log loss |
|---|---:|---:|---:|
| Prior only / purchase | 19,245 | .0339440329 | .1542928678 |
| Logistic / purchase | 19,245 | .0338937973 | .1537642863 |
| Logistic / carrier handoff | 19,244 | .0319493883 | .1380701126 |

Purchase-time improvement is very small. Handoff uses later information and a
slightly different eligible population; it is not a controlled autonomous action
gain. These candidates remain unapproved/inactive. Purchase logistic Brier bootstrap
95% interval is [.0319435, .0360203]; handoff [.0302391, .0341078]. Historical
predictive evaluation is not production validation or a causal estimate.

| Claim | Evidence level |
|---|---|
| Bayesian normalization, information gain, Bellman decisions | Mathematics implemented and deterministic tests |
| Policy utility comparisons | Synthetic simulator only |
| Calibration estimation and held-out replay | Synthetic representative logs |
| Olist delivery dates and provenance | Real reviewed historical records |
| Olist logistic candidates | Chronological historical holdout; not activated |
| Procurement matching | Synthetic engineering fixtures |
| Real-world one-step/multi-step investigation advantage | NOT EVALUABLE |
| Company deployment benefit or production accuracy | NOT VALIDATED |

I20 separately ran a small reproducibility smoke experiment into
reports/implementation20/synthetic_smoke. It preserves the historical artifacts and
is not used to tune assumptions or replace their measurements.
