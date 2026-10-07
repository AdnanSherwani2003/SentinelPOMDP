import sys
import os

# Add src/ to Python path if running script directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import initial_belief
from sentinel_pomdp.decision import rank_decisions
from sentinel_pomdp.states import SecurityState


def show_decisions(title, belief, actions):
    print(f"\n{title}")
    print("=" * 60)

    decisions = rank_decisions(
        belief,
        actions,
    )

    for decision in decisions:

        if decision.action is not None:
            target = decision.action.value

        elif decision.hypothesis is not None:
            target = decision.hypothesis.value

        else:
            target = "-"

        print(
            f"{decision.kind.value:12s} "
            f"{target:25s} "
            f"utility={decision.utility:.4f}"
        )


belief = initial_belief()

show_decisions(
    "INITIAL DECISION",
    belief,
    list(InvestigationAction),
)

high_confidence_belief = {
    SecurityState.BENIGN: 0.01,
    SecurityState.CREDENTIAL_COMPROMISE: 0.02,
    SecurityState.MALWARE_COMPROMISE: 0.92,
    SecurityState.LATERAL_MOVEMENT: 0.03,
    SecurityState.DATA_EXFILTRATION: 0.02,
}


show_decisions(
    "HIGH-CONFIDENCE DECISION",
    high_confidence_belief,
    list(InvestigationAction),
)

show_decisions(
    "NO MORE EVIDENCE AVAILABLE",
    initial_belief(),
    [],
)
