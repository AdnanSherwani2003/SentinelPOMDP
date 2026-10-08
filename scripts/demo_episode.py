import sys
import os

# Add src/ to Python path if running script directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from sentinel_pomdp.decision import DecisionType
from sentinel_pomdp.environment import SecurityInvestigationEnv
from sentinel_pomdp.episode import run_episode
from sentinel_pomdp.states import SecurityState


def print_belief(belief):
    for state, probability in sorted(
        belief.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        print(
            f"    {state.value:25s} "
            f"{probability:.4f}"
        )


env = SecurityInvestigationEnv(
    true_state=SecurityState.BENIGN,
    seed=42,
)

result = run_episode(env)


print("\n" + "=" * 70)
print("AUTONOMOUS SECURITY INVESTIGATION")
print("=" * 70)


for step in result.steps:

    print(
        f"\nSTEP {step.step_number}"
    )

    print("\nBelief before:")
    print_belief(
        step.belief_before
    )

    print(
        f"\nDecision: "
        f"{step.decision.kind.value}"
    )

    if step.decision.action is not None:
        print(
            f"Action: "
            f"{step.decision.action.value}"
        )

    if step.observation is not None:
        print(
            f"Observation: "
            f"{step.observation.value}"
        )

    if step.decision.hypothesis is not None:
        print(
            f"Hypothesis: "
            f"{step.decision.hypothesis.value}"
        )

    print(
        f"Utility: "
        f"{step.decision.utility:.4f}"
    )

    if step.belief_after is not None:
        print("\nBelief after:")
        print_belief(
            step.belief_after
        )


print("\n" + "=" * 70)
print("RESULT")
print("=" * 70)

print(
    f"True state: "
    f"{result.true_state.value}"
)

print(
    f"Termination: "
    f"{result.terminated_by.value}"
)

print(
    f"Predicted state: "
    f"{result.predicted_state.value if result.predicted_state else 'None'}"
)

print(
    f"Correct: "
    f"{result.correct}"
)

print(
    f"Steps: "
    f"{len(result.steps)}"
)
