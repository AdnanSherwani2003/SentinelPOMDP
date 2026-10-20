# SentinelPOMDP — Implementation 6.1: episode integration and comparison

This patch connects the standalone `MultiStepPlanner` to the existing **synthetic** episode runner and evaluation pipeline. It preserves `run_episode(env)` and `run_balanced_evaluation(...)` as the original policy when no planner is supplied.

**It does not introduce Neo4j, source evidence, or a provenance verifier.** The security-domain names in the existing simulator are benchmark fixtures, not the purpose of the product.

## Integration interfaces

- `build_investigation_planner(horizon=1|2, gamma=0.95)` in `integration.py` converts the existing enum keys into the planner's domain-neutral string keys.
- The observation table is **exactly** the repository's `OBSERVATION_MODEL`, reused without probability tuning.
- `PlanningConfig` has a new `information_gain_weight` parameter, defaulting to zero to preserve the original standalone Implementation 6 behavior. The adapter enables it using the existing `RewardConfig.information_gain_weight`.
- Each action's immediate utility becomes `information_gain_weight × expected_information_gain − weighted action cost`. The terminal answer and abstain utilities and `min_answer_confidence` use the existing `RewardConfig` fields.
- New planning policy uses `gamma=0.95` (the original Implementation 6 default); the legacy one-step decision policy has no future-value discount. Therefore results between **legacy** and **horizon 1/2** are comparisons of policies with related but not fully identical objectives. Horizon 1 vs 2 differs only in depth.
- The agent's decision code sees only the current belief and observed-action history. It never uses the hidden truth for action selection. The episode harness uses the hidden truth only to sample observations and score final decisions.
- The runner reserves a terminal decision step when a multi-step planner is supplied: a horizon-2 policy can replan after **each actual observation**; hypothetical branches are never appended to the actual episode.

## Reproduce from the integrated repository

This is a historical milestone description. Its source changes are already
integrated; no patch ZIP or overwrite operation is needed for a new checkout.

```powershell
# From the repository root; preserve any unrelated working-tree edits.
uv sync --frozen --group dev
uv run pytest -q
uv run python scripts/compare_planners.py --episodes-per-state 200 --base-seed 1000

```

## Actual results from the uploaded snapshot

All **53 tests passed** on Python 3.13 (49 existing + 4 new tests).

Balanced 1,000-episode synthetic benchmark, seed 1000, 200 per state:

| Policy | Coverage | Selective accuracy | Wrong / all episodes | Abstention | Evidence actions/episode | Brier |
|---|---:|---:|---:|---:|---:|---:|
| Existing policy | 20.90% | 78.47% | 4.50% | 79.10% | 3.58 | 0.5573 |
| Horizon 1 | 17.30% | 89.02% | 1.90% | 82.70% | 3.05 | 0.5471 |
| Horizon 2 | 17.30% | 89.02% | 1.90% | 82.70% | 3.02 | 0.5420 |

**Crucial limitation:** All three policies got **zero correct answers for every non-benign state**. Horizon 2 did not improve answer accuracy over horizon 1 on this benchmark. Differences in evidence actions and Brier score alone do not prove multi-step planning is beneficial on real-world tasks.

This is a measurement of the existing synthetic simulator, not external knowledge graph evidence, enterprise records, or production performance. In particular, `support_predicate` is optional and not configured with document-level provenance verification; the `ANSWER` policy is based on probability, not yet verified claim support.

## Recommended next steps

1. Preserve the benchmark as a versioned baseline before changing likelihoods or rewards.
2. Add per-state and per-hypothesis coverage, selective accuracy, confusion matrices, and targeted failure-case traces to the comparison harness.
3. Build a small domain-neutral synthetic evidence benchmark with both source-supported and deliberately unsupported cases.
4. Implement evidence-source verification **separately from posterior confidence**; gate final answers on verified support.
5. Move to Implementation 7 (graph + provenance) only after the integration is committed and the evaluation limitations are recorded.

### Scope of patch

Updated:
- `src/sentinel_pomdp/multistep.py`
- `src/sentinel_pomdp/episode.py`
- `src/sentinel_pomdp/evaluation.py`

Added:
- `src/sentinel_pomdp/integration.py`
- `tests/test_integration_multistep.py`
- `scripts/compare_planners.py`
- `docs/implementation_6_1_integration.md`
- `docs/implementation_6_1_benchmark.txt`
