import math

from sentinel_pomdp.decision import DecisionType
from sentinel_pomdp.environment import SecurityInvestigationEnv
from sentinel_pomdp.episode import run_episode
from sentinel_pomdp.states import SecurityState


def test_episode_always_terminates():
    env = SecurityInvestigationEnv(
        true_state=SecurityState.MALWARE_COMPROMISE,
        seed=42,
    )

    result = run_episode(env)

    assert result.terminated_by in {
        DecisionType.ANSWER,
        DecisionType.ABSTAIN,
    }


def test_episode_respects_max_steps():
    env = SecurityInvestigationEnv(
        true_state=SecurityState.MALWARE_COMPROMISE,
        seed=42,
    )

    result = run_episode(
        env,
        max_steps=3,
    )

    assert len(result.steps) <= 3


def test_answer_correct_flag_matches_ground_truth():
    env = SecurityInvestigationEnv(
        true_state=SecurityState.MALWARE_COMPROMISE,
        seed=42,
    )

    result = run_episode(env)

    if result.terminated_by == DecisionType.ANSWER:

        assert result.correct == (
            result.predicted_state
            == result.true_state
        )


def test_abstention_has_no_prediction():
    env = SecurityInvestigationEnv(
        true_state=SecurityState.BENIGN,
        seed=42,
    )

    result = run_episode(env)

    if result.terminated_by == DecisionType.ABSTAIN:
        assert result.predicted_state is None
        assert result.correct is None


def test_all_episode_beliefs_remain_valid():
    env = SecurityInvestigationEnv(
        true_state=SecurityState.DATA_EXFILTRATION,
        seed=99,
    )

    result = run_episode(env)

    for step in result.steps:

        assert math.isclose(
            sum(step.belief_before.values()),
            1.0,
            abs_tol=1e-9,
        )

        if step.belief_after is not None:

            assert math.isclose(
                sum(step.belief_after.values()),
                1.0,
                abs_tol=1e-9,
            )

            for probability in step.belief_after.values():
                assert 0.0 <= probability <= 1.0
