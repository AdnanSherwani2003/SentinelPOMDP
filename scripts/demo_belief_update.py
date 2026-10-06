import sys
import os

# Add src/ to Python path if running script directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import initial_belief, update_belief
from sentinel_pomdp.observations import Observation


def print_belief(title, belief):
    print(f"\n{title}")
    print("-" * 50)

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

print_belief(
    "INITIAL BELIEF",
    belief,
)

belief = update_belief(
    belief,
    InvestigationAction.INSPECT_PROCESS,
    Observation.PROCESS_ENCODED_POWERSHELL,
)

print_belief(
    "AFTER ENCODED POWERSHELL",
    belief,
)

belief = update_belief(
    belief,
    InvestigationAction.INSPECT_NETWORK,
    Observation.NETWORK_C2_PATTERN,
)

print_belief(
    "AFTER C2 NETWORK PATTERN",
    belief,
)
