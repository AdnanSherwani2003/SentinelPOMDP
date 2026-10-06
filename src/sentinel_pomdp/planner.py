from collections.abc import Iterable

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import BeliefState
from sentinel_pomdp.information import expected_information_gain


def rank_actions(
    belief: BeliefState,
    available_actions: Iterable[InvestigationAction] | None = None,
) -> list[tuple[InvestigationAction, float]]:

    if available_actions is None:
        available_actions = list(InvestigationAction)

    scored_actions = []

    for action in available_actions:
        score = expected_information_gain(
            belief,
            action,
        )

        scored_actions.append(
            (action, score)
        )

    return sorted(
        scored_actions,
        key=lambda item: (-item[1], item[0].value),
    )


def select_action(
    belief: BeliefState,
    available_actions: Iterable[InvestigationAction] | None = None,
) -> InvestigationAction:

    ranked = rank_actions(
        belief,
        available_actions,
    )

    if not ranked:
        raise ValueError(
            "No investigation actions are available."
        )

    return ranked[0][0]
