"""Reproducible final benchmark utilities built on the existing simulator.

Ground truth is supplied only to the environment and scoring code. Policies see
the belief, action/observation model, and observation history, never true state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import log2
from random import Random
from statistics import mean
from time import perf_counter
from typing import Iterable

from sentinel_pomdp.belief import balanced_belief
from sentinel_pomdp.evaluation import (
    EvaluationRecord, calibration_bins, multiclass_log_loss,
    run_balanced_evaluation, summarize,
)
from sentinel_pomdp.integration import build_investigation_planner
from sentinel_pomdp.model import CALIBRATED_OBSERVATION_MODEL
from sentinel_pomdp.multistep import MultiStepPlanner, PlanDecision
from sentinel_pomdp.states import SecurityState


BENCHMARK_VERSION = "implementation-13-v1"
DEFAULT_SEED = 13_000


def _entropy(probabilities: Iterable[float]) -> float:
    return -sum(value * log2(value) for value in probabilities if value > 0)


class _PolicyAdapter:
    def __init__(self, base: MultiStepPlanner) -> None:
        self.base = base
        self.states = base.states
        self.actions = base.actions
        self.config = base.config

    def posterior(self, *args, **kwargs):
        return self.base.posterior(*args, **kwargs)


class ImmediateDecisionPolicy(_PolicyAdapter):
    def decide(self, belief, history=(), horizon=None):
        return self.base.decide(belief, history=history, horizon=0)


class FixedOrderPolicy(_PolicyAdapter):
    def __init__(self, base: MultiStepPlanner, sequence: tuple[str, ...]) -> None:
        super().__init__(base)
        self.sequence = sequence

    def decide(self, belief, history=(), horizon=None):
        terminal = self.base.decide(belief, history=history, horizon=0)
        if terminal.kind == "ANSWER":
            return terminal
        used = {action for action, _ in history}
        for action in self.sequence:
            if action not in used:
                return PlanDecision("INVESTIGATE", action, None, 0.0, tuple())
        return terminal


class GreedyInformationGainPolicy(_PolicyAdapter):
    def _information_gain(self, belief: dict[str, float], action: str) -> float:
        prior_entropy = _entropy(belief.values())
        posterior_entropy = 0.0
        for observation in self.base.outcomes[action]:
            probability = self.base.outcome_probability(belief, action, observation)
            if probability > 0:
                posterior_entropy += probability * _entropy(
                    self.base.posterior(belief, action, observation).values())
        return prior_entropy - posterior_entropy

    def decide(self, belief, history=(), horizon=None):
        terminal = self.base.decide(belief, history=history, horizon=0)
        if terminal.kind == "ANSWER":
            return terminal
        used = {action for action, _ in history}
        remaining = [action for action in self.actions if action not in used]
        if not remaining:
            return terminal
        scores = tuple(sorted(
            ((action, self._information_gain(belief, action)) for action in remaining),
            key=lambda item: (-item[1], item[0]),
        ))
        return PlanDecision("INVESTIGATE", scores[0][0], None, scores[0][1], scores)


@dataclass(frozen=True)
class PolicyResult:
    policy: str
    total: int
    answered: int
    abstained: int
    correct: int
    incorrect: int
    answer_rate: float
    abstention_rate: float
    selective_accuracy: float
    overall_correct_rate: float
    false_confident_rate: float
    unsupported_answer_rate: float
    average_actions: float
    average_cost: float
    cost_per_correct_answer: float | None
    average_realized_utility: float
    brier_score: float
    log_loss: float
    expected_calibration_error: float
    average_entropy_reduction: float
    runtime_seconds: float


def _summarize_policy(name: str, records: list[EvaluationRecord], elapsed: float) -> PolicyResult:
    summary = summarize(records, runtime_seconds=elapsed)
    initial_entropy = _entropy(balanced_belief().values())
    entropy_reduction = mean(
        initial_entropy - _entropy(record.final_belief.values()) for record in records)
    return PolicyResult(
        policy=name, total=len(records), answered=summary.answered,
        abstained=summary.abstained, correct=summary.correct_answers,
        incorrect=summary.wrong_answers, answer_rate=summary.coverage,
        abstention_rate=summary.abstention_rate,
        selective_accuracy=summary.selective_accuracy,
        overall_correct_rate=summary.overall_correct_rate,
        false_confident_rate=summary.wrong_answer_rate,
        unsupported_answer_rate=0.0,  # simulator has no graph provenance contract
        average_actions=mean(len(record.actions) for record in records),
        average_cost=summary.average_cost,
        cost_per_correct_answer=(sum(r.total_cost for r in records) / summary.correct_answers
                                 if summary.correct_answers else None),
        average_realized_utility=summary.average_realized_utility,
        brier_score=summary.brier_score,
        log_loss=multiclass_log_loss(records),
        expected_calibration_error=summary.expected_calibration_error,
        average_entropy_reduction=entropy_reduction,
        runtime_seconds=elapsed,
    )


def bootstrap_paired_mean_difference(
    left: list[float], right: list[float], *, seed: int, samples: int = 1_000,
) -> dict[str, float]:
    """Percentile interval for mean(left-right), resampling paired episodes."""
    if not left or len(left) != len(right):
        raise ValueError("paired samples must be non-empty and equal length")
    random = Random(seed)
    differences = [a - b for a, b in zip(left, right)]
    estimates = sorted(mean(differences[random.randrange(len(differences))]
                            for _ in differences) for _ in range(samples))
    return {
        "mean_difference": mean(differences),
        "ci95_low": estimates[int(samples * .025)],
        "ci95_high": estimates[min(samples - 1, int(samples * .975))],
        "bootstrap_samples": samples,
    }


def run_final_synthetic_benchmark(
    *, episodes_per_state: int = 200, seed: int = DEFAULT_SEED,
) -> tuple[dict, dict[str, list[EvaluationRecord]]]:
    """Run five policies on identical balanced state/seed pairs."""
    def planner(horizon: int = 2) -> MultiStepPlanner:
        return build_investigation_planner(
            horizon=horizon, model_version="calibrated", use_support_predicate=True,
            min_observations=1, answer_threshold=.80)

    policies = {
        "immediate": ImmediateDecisionPolicy(planner()),
        "fixed_order": FixedOrderPolicy(planner(), tuple(sorted(planner().actions))),
        "greedy_information_gain": GreedyInformationGainPolicy(planner()),
        "expected_utility_h1": planner(1),
        "pomdp_h2": planner(2),
    }
    records_by_policy: dict[str, list[EvaluationRecord]] = {}
    results = []
    for name, policy in policies.items():
        started = perf_counter()
        records = run_balanced_evaluation(
            episodes_per_state=episodes_per_state, base_seed=seed, max_steps=5,
            planner=policy, initial_belief_state=balanced_belief(),
            observation_model=CALIBRATED_OBSERVATION_MODEL,
        )
        elapsed = perf_counter() - started
        records_by_policy[name] = records
        results.append(asdict(_summarize_policy(name, records, elapsed)))

    h1 = records_by_policy["expected_utility_h1"]
    h2 = records_by_policy["pomdp_h2"]
    comparison = bootstrap_paired_mean_difference(
        [record.realized_utility for record in h2],
        [record.realized_utility for record in h1], seed=seed + 991)
    report = {
        "benchmark_version": BENCHMARK_VERSION,
        "seed": seed,
        "episodes_per_state": episodes_per_state,
        "total_episodes_per_policy": episodes_per_state * len(SecurityState),
        "state_distribution": {state.value: episodes_per_state for state in SecurityState},
        "dataset_role": "final_evaluation_not_used_for_tuning",
        "data_kind": "synthetic_calibrated_simulator",
        "ground_truth_policy_access": False,
        "policies": results,
        "h2_minus_h1_realized_utility": comparison,
        "calibration_bins": {
            name: [asdict(item) for item in calibration_bins(records)]
            for name, records in records_by_policy.items()
        },
        "limitations": [
            "Calibration is against the configured simulator, not real-world labels.",
            "Unsupported-answer rate is not defined by the simulator; graph evidence is evaluated separately.",
            "The five-state synthetic security benchmark is distinct from the supplier-delay demonstration.",
        ],
    }
    return report, records_by_policy
