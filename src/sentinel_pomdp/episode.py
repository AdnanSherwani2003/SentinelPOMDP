from dataclasses import dataclass, field

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import (
    BeliefState,
    initial_belief,
    update_belief,
)
from sentinel_pomdp.decision import (
    Decision,
    DecisionType,
    select_decision,
)
from sentinel_pomdp.environment import SecurityInvestigationEnv
from sentinel_pomdp.observations import Observation
from sentinel_pomdp.states import SecurityState


@dataclass
class InvestigationStep:
    step_number: int

    belief_before: BeliefState

    decision: Decision

    observation: Observation | None = None

    belief_after: BeliefState | None = None


@dataclass
class EpisodeResult:
    true_state: SecurityState

    terminated_by: DecisionType

    predicted_state: SecurityState | None

    correct: bool | None

    final_belief: BeliefState

    steps: list[InvestigationStep] = field(
        default_factory=list
    )


def run_episode(
    env: SecurityInvestigationEnv,
    max_steps: int = 10,
) -> EpisodeResult:

    belief = initial_belief()

    available_actions = set(
        InvestigationAction
    )

    history: list[InvestigationStep] = []

    for step_number in range(1, max_steps + 1):

        decision = select_decision(
            belief,
            available_actions,
        )

        belief_before = belief.copy()

        # ---------------------------------
        # INVESTIGATE
        # ---------------------------------

        if decision.kind == DecisionType.INVESTIGATE:

            if decision.action is None:
                raise RuntimeError(
                    "Investigation decision "
                    "does not contain an action."
                )

            observation = env.observe(
                decision.action
            )

            belief = update_belief(
                belief,
                decision.action,
                observation,
            )

            available_actions.remove(
                decision.action
            )

            history.append(
                InvestigationStep(
                    step_number=step_number,
                    belief_before=belief_before,
                    decision=decision,
                    observation=observation,
                    belief_after=belief.copy(),
                )
            )

            continue

        # ---------------------------------
        # ANSWER
        # ---------------------------------

        if decision.kind == DecisionType.ANSWER:

            predicted_state = decision.hypothesis

            history.append(
                InvestigationStep(
                    step_number=step_number,
                    belief_before=belief_before,
                    decision=decision,
                    belief_after=belief.copy(),
                )
            )

            return EpisodeResult(
                true_state=env.true_state,
                terminated_by=DecisionType.ANSWER,
                predicted_state=predicted_state,
                correct=(
                    predicted_state
                    == env.true_state
                ),
                final_belief=belief.copy(),
                steps=history,
            )

        # ---------------------------------
        # ABSTAIN
        # ---------------------------------

        if decision.kind == DecisionType.ABSTAIN:

            history.append(
                InvestigationStep(
                    step_number=step_number,
                    belief_before=belief_before,
                    decision=decision,
                    belief_after=belief.copy(),
                )
            )

            return EpisodeResult(
                true_state=env.true_state,
                terminated_by=DecisionType.ABSTAIN,
                predicted_state=None,
                correct=None,
                final_belief=belief.copy(),
                steps=history,
            )

    # ---------------------------------
    # Safety fallback
    # ---------------------------------

    return EpisodeResult(
        true_state=env.true_state,
        terminated_by=DecisionType.ABSTAIN,
        predicted_state=None,
        correct=None,
        final_belief=belief.copy(),
        steps=history,
    )
