from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.environment import SecurityInvestigationEnv
from sentinel_pomdp.model import OBSERVATION_MODEL
from sentinel_pomdp.states import SecurityState


def test_environment_uses_given_true_state():
    env = SecurityInvestigationEnv(
        true_state=SecurityState.MALWARE_COMPROMISE,
        seed=42,
    )

    assert (
        env.true_state
        == SecurityState.MALWARE_COMPROMISE
    )


def test_observation_is_valid_for_action_and_state():
    env = SecurityInvestigationEnv(
        true_state=SecurityState.MALWARE_COMPROMISE,
        seed=42,
    )

    action = InvestigationAction.INSPECT_NETWORK

    observation = env.observe(action)

    valid_observations = (
        OBSERVATION_MODEL[action][
            SecurityState.MALWARE_COMPROMISE
        ]
    )

    assert observation in valid_observations


def test_seed_makes_environment_reproducible():
    env_1 = SecurityInvestigationEnv(
        true_state=SecurityState.MALWARE_COMPROMISE,
        seed=123,
    )

    env_2 = SecurityInvestigationEnv(
        true_state=SecurityState.MALWARE_COMPROMISE,
        seed=123,
    )

    observation_1 = env_1.observe(
        InvestigationAction.INSPECT_NETWORK
    )

    observation_2 = env_2.observe(
        InvestigationAction.INSPECT_NETWORK
    )

    assert observation_1 == observation_2
