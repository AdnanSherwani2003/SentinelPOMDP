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
from sentinel_pomdp.multistep import MultiStepPlanner
from sentinel_pomdp.reward import (
    ACTION_COSTS,
    DEFAULT_REWARD_CONFIG,
    RewardConfig,
)
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

    total_cost: float = 0.0

    realized_utility: float = 0.0


def run_episode(
    env: SecurityInvestigationEnv,
    max_steps: int = 10,
    *,
    planner: MultiStepPlanner | None = None,
    reward_config: RewardConfig = DEFAULT_REWARD_CONFIG,
    initial_belief_state: BeliefState | None = None,
    observation_model: dict | None = None,
) -> EpisodeResult:

    belief = initial_belief() if initial_belief_state is None else initial_belief_state.copy()

    available_actions = set(
        InvestigationAction
    )

    history: list[InvestigationStep] = []
    evidence_history: list[tuple[str, str]] = []
    total_investigation_cost = 0.0

    if planner is not None:
        # The domain adapter must represent the same actions and hypotheses.
        if set(planner.states) != {state.value for state in SecurityState}:
            raise ValueError("Planner states do not match this environment")
        if set(planner.actions) != {action.value for action in InvestigationAction}:
            raise ValueError("Planner actions do not match this environment")

    for step_number in range(1, max_steps + 1):

        if planner is None:
            decision = select_decision(belief, available_actions, reward_config)
        else:
            # Reserve a final decision slot: no INVESTIGATE on the last step.
            remaining_investigations = max_steps - step_number
            plan = planner.decide(
                {state.value: prob for state, prob in belief.items()},
                history=evidence_history,
                horizon=min(planner.config.horizon, remaining_investigations),
            )
            decision = Decision(
                kind=DecisionType(plan.kind.lower()),
                action=InvestigationAction(plan.action) if plan.action is not None else None,
                hypothesis=SecurityState(plan.hypothesis) if plan.hypothesis is not None else None,
                utility=plan.expected_utility,
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

            act_costs = ACTION_COSTS[decision.action]
            step_cost = (
                reward_config.operational_cost_weight * act_costs.operational
                + reward_config.privacy_cost_weight * act_costs.privacy
                + reward_config.latency_cost_weight * act_costs.latency
            )
            total_investigation_cost += step_cost

            observation = env.observe(
                decision.action
            )

            belief = update_belief(
                belief,
                decision.action,
                observation,
                observation_model=observation_model,
            )

            available_actions.remove(
                decision.action
            )

            if planner is not None:
                evidence_history.append((decision.action.value, observation.value))

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

            is_correct = (predicted_state == env.true_state)
            term_reward = (
                reward_config.correct_answer_reward
                if is_correct
                else -reward_config.wrong_answer_penalty
            )

            return EpisodeResult(
                true_state=env.true_state,
                terminated_by=DecisionType.ANSWER,
                predicted_state=predicted_state,
                correct=is_correct,
                final_belief=belief.copy(),
                steps=history,
                total_cost=total_investigation_cost,
                realized_utility=term_reward - total_investigation_cost,
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

            term_reward = -reward_config.abstain_penalty

            return EpisodeResult(
                true_state=env.true_state,
                terminated_by=DecisionType.ABSTAIN,
                predicted_state=None,
                correct=None,
                final_belief=belief.copy(),
                steps=history,
                total_cost=total_investigation_cost,
                realized_utility=term_reward - total_investigation_cost,
            )

    # ---------------------------------
    # Safety fallback
    # ---------------------------------

    term_reward = -reward_config.abstain_penalty
    return EpisodeResult(
        true_state=env.true_state,
        terminated_by=DecisionType.ABSTAIN,
        predicted_state=None,
        correct=None,
        final_belief=belief.copy(),
        steps=history,
        total_cost=total_investigation_cost,
        realized_utility=term_reward - total_investigation_cost,
    )
