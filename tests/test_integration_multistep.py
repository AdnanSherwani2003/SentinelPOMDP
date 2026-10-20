"""Integration tests: the real enum-domain simulator uses the new planner."""
import pytest

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import initial_belief
from sentinel_pomdp.decision import DecisionType
from sentinel_pomdp.environment import SecurityInvestigationEnv
from sentinel_pomdp.episode import run_episode
from sentinel_pomdp.evaluation import run_balanced_evaluation, summarize
from sentinel_pomdp.information import expected_information_gain
from sentinel_pomdp.integration import build_investigation_planner
from sentinel_pomdp.reward import DEFAULT_REWARD_CONFIG, investigation_utility
from sentinel_pomdp.states import SecurityState


def test_domain_adapter_matches_current_model_and_reward():
    planner = build_investigation_planner(horizon=1)
    belief = initial_belief()
    assert set(planner.actions) == {action.value for action in InvestigationAction}
    assert set(planner.states) == {state.value for state in SecurityState}
    b = {state.value: probability for state, probability in belief.items()}
    # The horizon-1 immediate information-gain term matches legacy action reward.
    for action in InvestigationAction:
        costs = planner.costs[action.value]
        assert planner.config.information_gain_weight * expected_information_gain(belief, action) - costs == pytest.approx(
            investigation_utility(belief, action, DEFAULT_REWARD_CONFIG), abs=1e-9
        )
        for state in SecurityState:
            assert sum(planner.likelihoods[action.value][state.value].values()) == pytest.approx(1)


def test_multistep_episode_replans_after_real_observations():
    planner = build_investigation_planner(horizon=2)
    env = SecurityInvestigationEnv(true_state=SecurityState.DATA_EXFILTRATION, seed=55)
    result = run_episode(env, planner=planner)
    assert result.terminated_by in (DecisionType.ANSWER, DecisionType.ABSTAIN)
    actions = [step.decision.action for step in result.steps if step.decision.action]
    assert len(actions) == len(set(actions))
    history = []
    belief = initial_belief()
    for step in result.steps:
        assert step.belief_before == pytest.approx(belief)
        if step.decision.action:
            assert step.observation is not None
            belief = {SecurityState(state): p for state, p in planner.posterior(
                {s.value: p for s, p in belief.items()},
                step.decision.action.value, step.observation.value
            ).items()}
            history.append((step.decision.action.value, step.observation.value))
            assert step.belief_after == pytest.approx(belief)
    assert result.final_belief == pytest.approx(belief)
    assert len(result.steps) <= 10
    assert result.steps[-1].decision.kind != DecisionType.INVESTIGATE


def test_budget_reserves_terminal_decision_and_preserves_legacy_default():
    plan = build_investigation_planner(horizon=2)
    for max_steps in (1, 2, 3):
        env = SecurityInvestigationEnv(true_state=SecurityState.BENIGN, seed=12)
        result = run_episode(env, max_steps=max_steps, planner=plan)
        assert len(result.steps) <= max_steps
        assert result.steps[-1].decision.kind in {DecisionType.ABSTAIN, DecisionType.ANSWER}
    legacy_1 = run_episode(SecurityInvestigationEnv(true_state=SecurityState.BENIGN, seed=12))
    legacy_2 = run_episode(SecurityInvestigationEnv(true_state=SecurityState.BENIGN, seed=12), planner=None)
    assert legacy_1 == legacy_2


def test_evaluation_can_compare_horizons_reproducibly():
    for depth in (1, 2):
        planner = build_investigation_planner(horizon=depth)
        a = run_balanced_evaluation(episodes_per_state=2, base_seed=30, planner=planner)
        b = run_balanced_evaluation(episodes_per_state=2, base_seed=30, planner=planner)
        assert a == b
        assert len(a) == len(SecurityState) * 2
        summary = summarize(a)
        assert summary.answered + summary.abstained == summary.total_episodes
        assert all(0.0 <= p <= 1.0 for r in a for p in r.final_belief.values())
