from dataclasses import dataclass

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import BeliefState
from sentinel_pomdp.information import expected_information_gain
from sentinel_pomdp.states import SecurityState


@dataclass(frozen=True)
class ActionCost:
    operational: float
    privacy: float
    latency: float


@dataclass(frozen=True)
class RewardConfig:
    information_gain_weight: float = 1.0

    operational_cost_weight: float = 0.5
    privacy_cost_weight: float = 0.5
    latency_cost_weight: float = 0.25

    correct_answer_reward: float = 1.0
    wrong_answer_penalty: float = 5.0

    abstain_penalty: float = 0.25

    min_answer_confidence: float = 0.85


DEFAULT_REWARD_CONFIG = RewardConfig()


ACTION_COSTS = {
    InvestigationAction.INSPECT_AUTH: ActionCost(
        operational=0.08,
        privacy=0.20,
        latency=0.08,
    ),

    InvestigationAction.INSPECT_PROCESS: ActionCost(
        operational=0.10,
        privacy=0.10,
        latency=0.12,
    ),

    InvestigationAction.INSPECT_NETWORK: ActionCost(
        operational=0.12,
        privacy=0.12,
        latency=0.15,
    ),

    InvestigationAction.INSPECT_VULNERABILITY: ActionCost(
        operational=0.05,
        privacy=0.05,
        latency=0.05,
    ),
}


def investigation_utility(
    belief: BeliefState,
    action: InvestigationAction,
    config: RewardConfig = DEFAULT_REWARD_CONFIG,
) -> float:

    information_gain = expected_information_gain(
        belief,
        action,
    )

    cost = ACTION_COSTS[action]

    utility = (
        config.information_gain_weight * information_gain
        - config.operational_cost_weight * cost.operational
        - config.privacy_cost_weight * cost.privacy
        - config.latency_cost_weight * cost.latency
    )

    return utility


def best_hypothesis(
    belief: BeliefState,
) -> tuple[SecurityState, float]:

    state, probability = max(
        belief.items(),
        key=lambda item: item[1],
    )

    return state, probability


def answer_utility(
    belief: BeliefState,
    config: RewardConfig = DEFAULT_REWARD_CONFIG,
) -> tuple[SecurityState, float]:

    state, confidence = best_hypothesis(belief)

    if confidence < config.min_answer_confidence:
        return state, -float("inf")

    utility = (
        confidence * config.correct_answer_reward
        - (1.0 - confidence) * config.wrong_answer_penalty
    )

    return state, utility


def abstain_utility(
    config: RewardConfig = DEFAULT_REWARD_CONFIG,
) -> float:
    return -config.abstain_penalty
