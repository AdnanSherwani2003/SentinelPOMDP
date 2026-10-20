from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from random import Random

from .metrics import PilotPrediction


class RewardAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correct_answer_reward: float
    incorrect_answer_penalty: float
    abstention_cost: float
    operational_delay_cost_per_action: float = 0


class UtilityResult(BaseModel):
    policy: str
    cases: int
    average_realized_utility: float
    assumptions: RewardAssumptions


def realized_utility(predictions: list[PilotPrediction], labels: dict[str, str], *,
                     policy: str, assumptions: RewardAssumptions) -> UtilityResult:
    if not predictions:
        raise ValueError("predictions are required")
    values = []
    for item in predictions:
        if item.case_id not in labels:
            continue
        if item.decision == "ANSWER":
            utility = (assumptions.correct_answer_reward if item.predicted_label == labels[item.case_id]
                       else -assumptions.incorrect_answer_penalty)
        else:
            utility = -assumptions.abstention_cost
        utility -= item.investigation_cost
        utility -= assumptions.operational_delay_cost_per_action * len(item.actions_taken)
        values.append(utility)
    if not values:
        raise ValueError("no scored predictions")
    return UtilityResult(policy=policy, cases=len(values),
                         average_realized_utility=sum(values) / len(values),
                         assumptions=assumptions)


def _case_utility(item: PilotPrediction, label: str,
                  assumptions: RewardAssumptions) -> float:
    if item.decision == "ANSWER":
        value = (assumptions.correct_answer_reward if item.predicted_label == label
                 else -assumptions.incorrect_answer_penalty)
    else:
        value = -assumptions.abstention_cost
    return (value - item.investigation_cost
            - assumptions.operational_delay_cost_per_action * len(item.actions_taken))


def paired_utility_difference(left: list[PilotPrediction], right: list[PilotPrediction],
                              labels: dict[str, str], *, assumptions: RewardAssumptions,
                              seed: int, bootstrap_samples: int = 1000) -> dict[str, float | int]:
    left_by_id = {item.case_id: item for item in left}
    right_by_id = {item.case_id: item for item in right}
    case_ids = sorted(set(left_by_id) & set(right_by_id) & set(labels))
    if not case_ids or bootstrap_samples < 10:
        raise ValueError("paired cases and at least ten bootstrap samples are required")
    differences = [
        _case_utility(left_by_id[case_id], labels[case_id], assumptions)
        - _case_utility(right_by_id[case_id], labels[case_id], assumptions)
        for case_id in case_ids]
    random = Random(seed)
    estimates = sorted(sum(differences[random.randrange(len(differences))]
                           for _ in differences) / len(differences)
                       for _ in range(bootstrap_samples))
    return {
        "paired_cases": len(differences),
        "mean_difference": sum(differences) / len(differences),
        "ci95_low": estimates[int(.025 * bootstrap_samples)],
        "ci95_high": estimates[min(bootstrap_samples - 1, int(.975 * bootstrap_samples))],
        "bootstrap_samples": bootstrap_samples,
    }


def sensitivity_grid(predictions_by_policy: dict[str, list[PilotPrediction]], labels: dict[str, str], *,
                     correct_rewards=(1.0, 5.0), incorrect_penalties=(2.0, 7.0),
                     abstention_costs=(.1, .25, 1.0)) -> list[UtilityResult]:
    results = []
    for correct in correct_rewards:
        for incorrect in incorrect_penalties:
            for abstention in abstention_costs:
                assumptions = RewardAssumptions(
                    correct_answer_reward=correct, incorrect_answer_penalty=incorrect,
                    abstention_cost=abstention)
                for name, predictions in predictions_by_policy.items():
                    results.append(realized_utility(
                        predictions, labels, policy=name, assumptions=assumptions))
    return results
