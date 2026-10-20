# Implementation 6 — Multi-Step POMDP Planning (additive patch)

**Project identity:** an evidence-driven, mathematically controlled multi-step agent; the supplier-delay names in the demonstration are placeholders and do not lock the system to any domain.

## Scope of this patch

- Adds `src/sentinel_pomdp/multistep.py`: a **finite-horizon exact belief-space lookahead** module for a small, enumerated, *static* hidden-state POMDP.
- Adds `tests/test_multistep.py`: 13 focused tests covering actual multi-step decisions, Bayesian posteriors, probability validity, abstention, support veto, tool costs, impossible observations, repeat prevention, and deterministic ordering.
- Adds `scripts/demo_multistep.py`: an entirely synthetic three-hypothesis demonstration.
- Does **not** overwrite the existing `decision.py`, `reward.py`, `planner.py`, `episode.py`, or `evaluation.py`.

## The mathematical difference

The one-step policy computes the immediate value of an investigation and then terminates. The multi-step policy uses

\[
V_h(b,H)=\max\bigg\{U_{\rm stop}(b,H),\max_{a\in A\setminus H}
\left[-c(a)+\gamma\sum_o P(o\mid b,a)V_{h-1}(\tau(b,a,o),H\!+\!(a,o))\right]\bigg\}.
\]

- `b`: belief distribution over hypotheses
- `H`: actual or hypothetical sequence of observed action/outcome pairs
- `h`: remaining evidence actions in the planning horizon
- `c(a)`: explicitly configured operational/latency/privacy cost, already combined upstream
- `P(o|b,a)`: predictive probability of an observation
- `tau(b,a,o)`: Bayesian posterior after the observation
- `U_stop`: best currently eligible `ANSWER` or `ABSTAIN` utility

The agent **does not have access to the simulated hidden truth** when selecting actions. The algorithm enumerates hypothetical observations and uses their model probabilities rather than asking an LLM to choose tools.

The reward is based on expected terminal answer accuracy and investigation cost. It deliberately does *not* add entropy-information gain to terminal accuracy utility, because that could count the same benefit twice. Information gain can still be computed as a diagnostic and compared with the earlier greedy information-gain baseline.

## Constraints and modeling assumptions

1. The latent hypothesis remains unchanged while collecting evidence (identity transition model). A general changing-state POMDP requires a later extension of the belief update.
2. The likelihood tables are synthetic in the demo. Calibrate and validate real tables separately; probabilities do not make invented evidence reliable.
3. Tool outcomes are conditionally independent given the latent state **across different tools**. Repeating the same tool is prohibited to avoid double-counting identical observations.
4. Lookahead is finite. The number of possible action/outcome histories grows rapidly with depth. Start with depths 1, 2, and 3, then measure time.
5. An `answer_threshold` is **not equivalent** to evidence provenance verification. The optional `support_predicate` can enforce a deterministic abstract evidence rule over observed outcome labels; a later graph evidence verifier must check actual source records independently before response synthesis.
6. An answer can be rejected when its expected utility is lower than abstention even if its probability exceeds the threshold.
7. Do not change the old model's probability tables, reward coefficients, or existing evaluation benchmark before recording its baseline.

## Installation (Windows PowerShell)

This historical module is already integrated. From the repository root, use the
locked dependencies; no patch archive or new branch is required to run it:

```powershell
uv sync --frozen --group dev
```

Run the new tests:

```powershell
uv run pytest -q tests/test_multistep.py
```

Run the demonstration:

```powershell
uv run python scripts/demo_multistep.py
```

Run the complete project test suite:

```powershell
uv run pytest -v
```

**Reference result for this additive module:** 13 tests passed when run in a temporary Python environment with pytest 9.0.2. That does *not* establish that the entire GitHub repository passes, because the current repository source tree could not be fetched for compatibility testing.

## Output from the example

The example has three synthetic hypotheses and three independent evidence actions. Under the configured horizon, outcome model, utilities, and costs:

- horizon 1: `INVESTIGATE production_schedule`, expected utility approximately `1.2929`
- horizon 2: `INVESTIGATE delivery_records`, expected utility approximately `1.3660`

Changing the first action across planning horizons demonstrates nontrivial lookahead. This is **not** an empirical performance improvement on your existing benchmark, and the horizon-1 policy here is not necessarily the current repository's greedy entropy-information-gain policy.

## Integration into the existing project — after examining actual source

1. Open `model.py`, `actions.py`, `observations.py` to identify the real state, action and outcome enums, and `P(o|s,a)` likelihoods.
2. Make a small adapter from those enums and tables to `MultiStepPlanner(states, observation_model, action_costs, config)`; **reuse** the existing reward parameters after confirming their semantics. Do not silently change them.
3. Compare `decision.py` stop/abstain logic with `PlanningConfig` terminal utility and threshold. Reconcile those policies **before** inserting the planner into `episode.py`, so the two policies cannot disagree.
4. In `episode.py`, request a new plan from the current belief and previous action/observation history at every step. If `INVESTIGATE`, execute the chosen tool; update belief with the existing Bayesian routine; append real evidence; then replan. For `ANSWER` or `ABSTAIN`, terminate. Keep the hidden state inaccessible to policy inputs.
5. Place a separate provenance verifier between the decision and final synthesis. A high belief probability is not itself sufficient source support.
6. Keep the previous greedy implementation as the **baseline**; run the same seeds, scenarios, reward settings, observation tables, and evaluation metrics for greedy vs horizon 2 vs horizon 3.
7. Report selective accuracy, coverage, wrong-answer rate, calibration, abstention accuracy, average evidence actions, cumulative action cost, and planning latency. If multi-step lookahead is slower or worse, report it rather than claim improvement.

## Acceptance checklist

- [x] Actual finite-horizon Bellman recursion with branches for future observations.
- [x] Investigate, answer, and abstain are available as explicit decisions.
- [x] Bayesian posteriors and impossible-observation safeguards.
- [x] Deterministic action ordering; never repeat a tool in one episode.
- [x] 13 focused local tests and a reproducible toy demo.
- [ ] Confirm adapter compatibility against your full GitHub source tree.
- [ ] Preserve and inspect the Implementation 5 benchmark baseline.
- [ ] Integrate the planner into the actual episode runner.
- [ ] Compare against the existing greedy policy on the same 1,000-episode test set.
- [ ] Add real evidence provenance validation before final answer synthesis.

The implementation becomes **integrated** only when those remaining checks are complete.
