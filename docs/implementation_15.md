# Implementation 15: pilot validation and calibration

## Status

- Evaluation-framework implementation: **COMPLETE** for the bounded framework scope.
- Real-world organizational validation: **PENDING**.

No authorized independently labeled company dataset exists in this repository. The included `synthetic-v1` shipment fixture is representative test data, not a measured company history.

## Implemented pipeline

1. Strict versioned cases, observations, independent labels, and authorization metadata.
2. Independent review, disagreement, adjudication, and unknown labels.
3. Chronological group holdouts with leakage checks.
4. Extraction/provenance and source-independence metrics.
5. Training-only smoothed priors and categorical likelihoods with counts and intervals.
6. Validation threshold selection and held-out Brier, log-loss, reliability, coverage, selective accuracy, false-answer, and unsupported-answer metrics.
7. Logged-observation replay that refuses to fabricate missing counterfactuals.
8. Reward sensitivity and paired utility comparisons against immediate abstention.
9. Versioned provisional domain packs and protected approval/rejection/rollback.
10. Privacy-safe JSON, CSV, SVG, and model artifacts.

## Representative fixture results

The deterministic run used 60 synthetic cases: 36 train, 12 validation, and 12 test. Training contained 18 delayed and 18 on-time labels. Validation selected threshold `0.80` under the demonstration rule that false-answer rate must be at most 0.10.

On 12 held-out synthetic cases, the logged investigation replay produced:

- answer coverage: 0.50;
- selective accuracy: 0.8333 (5/6 answers);
- false-answer rate: 0.0833 (1/12);
- unsupported-answer rate: 0;
- multiclass Brier score: 0.2820;
- log loss: 0.4571;
- ECE: 0.0431.

These values validate calculations and workflow only. Twelve synthetic test cases cannot establish operational reliability.

## Why abstention can still win

Under the historical-style assumptions of reward `1`, incorrect-answer penalty `7`, abstention cost `0.25`, and action cost `0.08`, logged investigation minus immediate abstention had mean utility difference `-0.1217`; the paired bootstrap interval was `[-1.4550, 0.7533]`. The interval is wide and crosses zero.

Sensitivity analysis does not tune rewards to make investigation win. Investigation was better under some assumptions—for example, lower error penalty `2`—and worse when errors were expensive and abstention cheap. Thus the useful policy depends on defensible business costs. The one-action logged fixture makes all investigation policy variants identical; it cannot identify a horizon-2 advantage. No real-world POMDP gain is claimed.

## Reproduction

```powershell
$env:RUN_LIVE_GROQ_TESTS = "0"
$env:RUN_LIVE_LLM_TESTS = "0"
uv run python scripts/evaluate_pilot.py --output-dir reports/pilot_evaluation
uv run pytest -q
```

Use `scripts/validate_pilot_dataset.py` before calibrating an authorized JSON dataset. Review the intake requirements in `pilot_dataset_specification.md`.
