from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import BeliefState
from sentinel_pomdp.reward import (
    DEFAULT_REWARD_CONFIG,
    RewardConfig,
    abstain_utility,
    answer_utility,
    best_hypothesis,
    investigation_utility,
)
from sentinel_pomdp.states import SecurityState


class DecisionType(str, Enum):
    INVESTIGATE = "investigate"
    ANSWER = "answer"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class Decision:
    kind: DecisionType
    utility: float

    action: InvestigationAction | None = None
    hypothesis: SecurityState | None = None


def rank_decisions(
    belief: BeliefState,
    available_actions: Iterable[InvestigationAction],
    config: RewardConfig = DEFAULT_REWARD_CONFIG,
) -> list[Decision]:

    candidates: list[Decision] = []

    # Investigation candidates
    for action in available_actions:
        candidates.append(
            Decision(
                kind=DecisionType.INVESTIGATE,
                action=action,
                utility=investigation_utility(
                    belief,
                    action,
                    config,
                ),
            )
        )

    # Answer candidate
    hypothesis, confidence = best_hypothesis(belief)

    if confidence >= config.min_answer_confidence:
        _, utility = answer_utility(
            belief,
            config,
        )

        candidates.append(
            Decision(
                kind=DecisionType.ANSWER,
                hypothesis=hypothesis,
                utility=utility,
            )
        )

    # Abstention is always available
    candidates.append(
        Decision(
            kind=DecisionType.ABSTAIN,
            utility=abstain_utility(config),
        )
    )

    return sorted(
        candidates,
        key=lambda decision: decision.utility,
        reverse=True,
    )


def select_decision(
    belief: BeliefState,
    available_actions: Iterable[InvestigationAction],
    config: RewardConfig = DEFAULT_REWARD_CONFIG,
) -> Decision:

    decisions = rank_decisions(
        belief,
        available_actions,
        config,
    )

    if not decisions:
        raise ValueError(
            "No valid decisions are available."
        )

    return decisions[0]
