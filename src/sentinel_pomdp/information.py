import math

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.belief import BeliefState, update_belief
from sentinel_pomdp.model import OBSERVATION_MODEL
from sentinel_pomdp.observations import Observation


def entropy(belief: BeliefState) -> float:
    """
    Shannon entropy of the belief distribution in bits.
    """
    total = 0.0

    for probability in belief.values():
        if probability > 0.0:
            total -= probability * math.log2(probability)

    return total


def possible_observations(
    action: InvestigationAction,
) -> set[Observation]:
    observations: set[Observation] = set()

    for state_table in OBSERVATION_MODEL[action].values():
        observations.update(state_table.keys())

    return observations


def observation_probability(
    belief: BeliefState,
    action: InvestigationAction,
    observation: Observation,
) -> float:
    probability = 0.0

    for state, state_probability in belief.items():
        likelihood = (
            OBSERVATION_MODEL[action][state]
            .get(observation, 0.0)
        )

        probability += state_probability * likelihood

    return probability


def expected_posterior_entropy(
    belief: BeliefState,
    action: InvestigationAction,
) -> float:
    expected_entropy = 0.0

    for observation in possible_observations(action):

        probability_of_observation = observation_probability(
            belief,
            action,
            observation,
        )

        if probability_of_observation <= 0.0:
            continue

        posterior = update_belief(
            belief,
            action,
            observation,
        )

        expected_entropy += (
            probability_of_observation
            * entropy(posterior)
        )

    return expected_entropy


def expected_information_gain(
    belief: BeliefState,
    action: InvestigationAction,
) -> float:
    current_entropy = entropy(belief)

    future_entropy = expected_posterior_entropy(
        belief,
        action,
    )

    return current_entropy - future_entropy
