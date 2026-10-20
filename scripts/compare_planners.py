"""Compare policies on paired synthetic episodes across planning horizons.

Supports both baseline (legacy observation model & prior) and calibrated
(separable observation signatures & uniform evaluation prior) configurations.
Reports coverage, selective accuracy, overall correct rate, wrong-answer rate,
abstention rate, action costs, realized utility, Brier score, calibration error,
planning runtime, per-state breakdown, and confusion matrices.
"""
from __future__ import annotations

import argparse
import time

from sentinel_pomdp.belief import balanced_belief, initial_belief
from sentinel_pomdp.evaluation import (
    confusion_matrix,
    per_state_metrics,
    run_balanced_evaluation,
    summarize,
)
from sentinel_pomdp.integration import build_investigation_planner
from sentinel_pomdp.model import CALIBRATED_OBSERVATION_MODEL, OBSERVATION_MODEL


def evaluate_benchmark(
    benchmark_name: str,
    episodes_per_state: int,
    base_seed: int,
    max_steps: int,
    use_support_predicate: bool,
) -> None:
    is_calibrated = benchmark_name == "calibrated"
    obs_model = CALIBRATED_OBSERVATION_MODEL if is_calibrated else OBSERVATION_MODEL
    prior_fn = balanced_belief if is_calibrated else initial_belief
    prior_state = prior_fn()

    threshold = 0.80 if is_calibrated else None
    min_obs = 1 if is_calibrated else 0

    print("=" * 110)
    print(f"BENCHMARK CONFIGURATION: {benchmark_name.upper()}")
    print("=" * 110)
    if is_calibrated:
        print("Model: Calibrated observation model (v2_calibrated; identifiable state signatures)")
        print("Prior: Balanced uniform belief (matches balanced evaluation distribution)")
        print(f"Evidence support predicate: {'ENABLED' if use_support_predicate else 'OFF'}")
    else:
        print("Model: Baseline observation model (v1_synthetic; legacy uncalibrated likelihoods)")
        print("Prior: Legacy initial belief (asymmetric prior: benign=0.45, exfiltration=0.08)")
        print(f"Evidence support predicate: {'ENABLED' if use_support_predicate else 'OFF'}")

    print(f"States: balanced, episodes/state={episodes_per_state}, total episodes={episodes_per_state * 5}, base_seed={base_seed}")
    print()

    policies = [
        ("legacy", None),
        ("horizon_1", build_investigation_planner(
            horizon=1,
            model_version="calibrated" if is_calibrated else "baseline",
            use_support_predicate=use_support_predicate,
            min_observations=min_obs,
            answer_threshold=threshold,
        )),
        ("horizon_2", build_investigation_planner(
            horizon=2,
            model_version="calibrated" if is_calibrated else "baseline",
            use_support_predicate=use_support_predicate,
            min_observations=min_obs,
            answer_threshold=threshold,
        )),
        ("horizon_3", build_investigation_planner(
            horizon=3,
            model_version="calibrated" if is_calibrated else "baseline",
            use_support_predicate=use_support_predicate,
            min_observations=min_obs,
            answer_threshold=threshold,
        )),
    ]

    header = (
        f"{'policy':<12} {'coverage':>9} {'selective':>10} {'correct':>9} "
        f"{'wrong':>8} {'abstain':>8} {'actions':>8} {'cost':>7} "
        f"{'utility':>8} {'Brier':>7} {'ECE':>7} {'time(s)':>8}"
    )
    print(header)
    print("-" * len(header))

    results = []

    for name, planner in policies:
        t0 = time.perf_counter()
        records = run_balanced_evaluation(
            episodes_per_state=episodes_per_state,
            base_seed=base_seed,
            max_steps=max_steps,
            planner=planner,
            initial_belief_state=prior_state,
            observation_model=obs_model,
        )
        elapsed = time.perf_counter() - t0
        summary = summarize(records, runtime_seconds=elapsed)
        results.append((name, records, summary))

        mean_actions = sum(len(r.actions) for r in records) / len(records)
        print(
            f"{name:<12} {summary.coverage:>9.2%} {summary.selective_accuracy:>10.2%} "
            f"{summary.overall_correct_rate:>9.2%} {summary.wrong_answer_rate:>8.2%} "
            f"{summary.abstention_rate:>8.2%} {mean_actions:>8.2f} "
            f"{summary.average_cost:>7.3f} {summary.average_realized_utility:>8.3f} "
            f"{summary.brier_score:>7.4f} {summary.expected_calibration_error:>7.4f} "
            f"{summary.runtime_seconds:>8.2f}"
        )

    print()
    print("PER-STATE ACCURACY & COVERAGE:")
    for name, records, _ in results:
        print(f"  [{name}]")
        for stat in per_state_metrics(records):
            print(
                f"    {stat.state.value:<22} correct={stat.correct:>3}/{stat.total} "
                f"({stat.correct_rate:>6.2%}) | answered={stat.answered:>3} "
                f"| selective={stat.selective_accuracy:>6.2%}"
            )

    print()
    print("CONFUSION MATRICES:")
    for name, records, _ in results:
        print(f"  [{name}]")
        matrix = confusion_matrix(records)
        all_preds = ["benign", "credential_compromise", "malware_compromise", "lateral_movement", "data_exfiltration", "ABSTAIN"]
        short_names = {"benign": "benign", "credential_compromise": "cred", "malware_compromise": "malw", "lateral_movement": "latm", "data_exfiltration": "exfil", "ABSTAIN": "ABST"}
        pred_header = " ".join(f"{short_names[p]:>7}" for p in all_preds)
        print(f"    {'True State':<16} {pred_header}")
        for state, counts in matrix.items():
            row_str = " ".join(f"{counts.get(p, 0):>7}" for p in all_preds)
            print(f"    {short_names.get(state.value, state.value):<16} {row_str}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="SentinelPOMDP Policy Horizon Benchmark")
    parser.add_argument("--episodes-per-state", type=int, default=200)
    parser.add_argument("--base-seed", type=int, default=1000)
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument(
        "--benchmark",
        choices=["baseline", "calibrated", "both"],
        default="baseline",
        help="Benchmark configuration to evaluate: baseline, calibrated, or both (default: baseline)",
    )
    parser.add_argument(
        "--use-support-predicate",
        action="store_true",
        help="Enable affirmative evidence support predicate gating",
    )
    args = parser.parse_args()

    if args.episodes_per_state < 1 or args.max_steps < 1:
        parser.error("episodes-per-state and max-steps must be >= 1")

    print("SentinelPOMDP Multi-Step Autonomous Reasoning Benchmark")
    print("Illustrative synthetic benchmark; domain-neutral POMDP lookahead evaluation.\n")

    if args.benchmark in ("baseline", "both"):
        evaluate_benchmark(
            "baseline",
            episodes_per_state=args.episodes_per_state,
            base_seed=args.base_seed,
            max_steps=args.max_steps,
            use_support_predicate=args.use_support_predicate,
        )

    if args.benchmark in ("calibrated", "both"):
        evaluate_benchmark(
            "calibrated",
            episodes_per_state=args.episodes_per_state,
            base_seed=args.base_seed,
            max_steps=args.max_steps,
            use_support_predicate=True if not args.use_support_predicate else args.use_support_predicate,
        )


if __name__ == "__main__":
    main()
