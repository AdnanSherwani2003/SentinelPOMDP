import sys
import os

# Add src/ to Python path if running script directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import (
    initial_belief,
    update_belief,
)
from sentinel_pomdp.information import entropy
from sentinel_pomdp.observations import Observation
from sentinel_pomdp.planner import (
    rank_actions,
    select_action,
)


def print_belief(belief):
    for state, probability in sorted(
        belief.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        print(
            f"{state.value:25s} "
            f"{probability:.4f}"
        )


belief = initial_belief()

available_actions = set(
    InvestigationAction
)

print("\nINITIAL BELIEF")
print_belief(belief)

print(
    f"\nEntropy: {entropy(belief):.4f}"
)

print("\nACTION RANKING")

for action, score in rank_actions(
    belief,
    available_actions,
):
    print(
        f"{action.value:25s} "
        f"information gain = {score:.4f}"
    )


selected_action = select_action(
    belief,
    available_actions,
)

print(
    f"\nSelected action: "
    f"{selected_action.value}"
)

observation = Observation.NETWORK_C2_PATTERN

print(
    f"Observation: {observation.value}"
)

belief = update_belief(
    belief,
    selected_action,
    observation,
)

available_actions.remove(
    selected_action
)

print("\nUPDATED BELIEF")
print_belief(belief)

print(
    f"\nNew entropy: "
    f"{entropy(belief):.4f}"
)

print("\nNEXT ACTION RANKING")

for action, score in rank_actions(
    belief,
    available_actions,
):
    print(
        f"{action.value:25s} "
        f"information gain = {score:.4f}"
    )
