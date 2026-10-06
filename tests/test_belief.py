"""Unit tests for POMDP Belief Distribution and Bayesian Belief Update.
"""

import pytest
import math

from sentinel_pomdp.states import GridState, SecurityState
from sentinel_pomdp.actions import SentinelAction, InvestigationAction
from sentinel_pomdp.observations import SentinelObservation, NO_DETECTION, Observation
from sentinel_pomdp.model import SentinelPOMDP, validate_observation_model
from sentinel_pomdp.belief import BeliefDistribution, initial_belief, update_belief


@pytest.fixture
def mini_model():
    """Create a 3x3 Sentinel POMDP model for fast testing."""
    return SentinelPOMDP(
        grid_width=3,
        grid_height=3,
        target_move_prob=0.1,
        sensor_decay_rate=0.5,
        false_positive_prob=0.02,
    )


def test_uniform_belief_initialization(mini_model):
    states = mini_model.get_states()
    belief = BeliefDistribution.uniform(states)

    assert len(states) == 3 * 3 * 3 * 3 * 2  # 162 total states
    total_prob = sum(belief[s] for s in states)
    assert math.isclose(total_prob, 1.0, abs_tol=1e-6)

    # Uniform probability per state
    expected_prob = 1.0 / len(states)
    for s in states:
        assert math.isclose(belief[s], expected_prob, abs_tol=1e-6)


def test_point_mass_initialization(mini_model):
    states = mini_model.get_states()
    target_s = states[0]

    belief = BeliefDistribution.point_mass(target_s, states)

    assert math.isclose(belief[target_s], 1.0, abs_tol=1e-6)
    assert math.isclose(belief.entropy(), 0.0, abs_tol=1e-6)
    most_likely, prob = belief.most_likely_state()
    assert most_likely == target_s
    assert math.isclose(prob, 1.0, abs_tol=1e-6)


def test_belief_entropy(mini_model):
    states = mini_model.get_states()
    belief = BeliefDistribution.uniform(states)

    expected_entropy = math.log2(len(states))
    assert math.isclose(belief.entropy(), expected_entropy, abs_tol=1e-4)


def test_bayes_belief_update(mini_model):
    states = mini_model.get_states()
    initial_b = BeliefDistribution.uniform(states)

    action = SentinelAction.SCAN
    obs = SentinelObservation(target_detected=True, observed_pos=(1, 1), signal_quality=1.0)

    updated_b = initial_b.update(mini_model, action, obs)

    # Belief should sum to 1.0
    total_prob = sum(updated_b[s] for s in states)
    assert math.isclose(total_prob, 1.0, abs_tol=1e-6)

    # Entropy after receiving a specific target observation should decrease
    assert updated_b.entropy() < initial_b.entropy()

    # States with target near (1,1) should have significantly higher probability
    most_likely, high_p = updated_b.most_likely_state()
    assert most_likely.target_pos == (1, 1)
    assert high_p > (1.0 / len(states))


def test_belief_update_no_detection(mini_model):
    states = mini_model.get_states()
    initial_b = BeliefDistribution.uniform(states)

    action = SentinelAction.NORTH
    obs = NO_DETECTION

    updated_b = initial_b.update(mini_model, action, obs)

    total_prob = sum(updated_b[s] for s in states)
    assert math.isclose(total_prob, 1.0, abs_tol=1e-6)


def test_initial_belief_sums_to_one():
    belief = initial_belief()

    assert math.isclose(
        sum(belief.values()),
        1.0,
        abs_tol=1e-9,
    )


def test_observation_model_is_valid():
    validate_observation_model()


def test_posterior_sums_to_one():
    belief = initial_belief()

    posterior = update_belief(
        belief,
        InvestigationAction.INSPECT_PROCESS,
        Observation.PROCESS_ENCODED_POWERSHELL,
    )

    assert math.isclose(
        sum(posterior.values()),
        1.0,
        abs_tol=1e-9,
    )


def test_encoded_powershell_increases_malware_belief():
    belief = initial_belief()

    posterior = update_belief(
        belief,
        InvestigationAction.INSPECT_PROCESS,
        Observation.PROCESS_ENCODED_POWERSHELL,
    )

    assert (
        posterior[SecurityState.MALWARE_COMPROMISE]
        >
        belief[SecurityState.MALWARE_COMPROMISE]
    )


def test_encoded_powershell_reduces_benign_belief():
    belief = initial_belief()

    posterior = update_belief(
        belief,
        InvestigationAction.INSPECT_PROCESS,
        Observation.PROCESS_ENCODED_POWERSHELL,
    )

    assert (
        posterior[SecurityState.BENIGN]
        <
        belief[SecurityState.BENIGN]
    )


def test_probabilities_remain_between_zero_and_one():
    belief = initial_belief()

    posterior = update_belief(
        belief,
        InvestigationAction.INSPECT_NETWORK,
        Observation.NETWORK_C2_PATTERN,
    )

    for probability in posterior.values():
        assert 0.0 <= probability <= 1.0



