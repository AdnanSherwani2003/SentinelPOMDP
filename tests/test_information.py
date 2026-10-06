import math

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import initial_belief
from sentinel_pomdp.information import (
    entropy,
    expected_information_gain,
    observation_probability,
    possible_observations,
)
from sentinel_pomdp.planner import select_action
from sentinel_pomdp.states import SecurityState


def test_certain_belief_has_zero_entropy():
    belief = {
        SecurityState.BENIGN: 1.0,
        SecurityState.CREDENTIAL_COMPROMISE: 0.0,
        SecurityState.MALWARE_COMPROMISE: 0.0,
        SecurityState.LATERAL_MOVEMENT: 0.0,
        SecurityState.DATA_EXFILTRATION: 0.0,
    }

    assert math.isclose(
        entropy(belief),
        0.0,
        abs_tol=1e-9,
    )


def test_initial_belief_has_positive_entropy():
    belief = initial_belief()

    assert entropy(belief) > 0.0


def test_observation_probabilities_sum_to_one():
    belief = initial_belief()

    for action in InvestigationAction:

        total = sum(
            observation_probability(
                belief,
                action,
                observation,
            )
            for observation in possible_observations(action)
        )

        assert math.isclose(
            total,
            1.0,
            abs_tol=1e-9,
        )


def test_information_gain_is_non_negative():
    belief = initial_belief()

    for action in InvestigationAction:

        information_gain = expected_information_gain(
            belief,
            action,
        )

        assert information_gain >= -1e-9


def test_network_is_best_initial_action():
    belief = initial_belief()

    selected = select_action(belief)

    assert (
        selected
        == InvestigationAction.INSPECT_NETWORK
    )
