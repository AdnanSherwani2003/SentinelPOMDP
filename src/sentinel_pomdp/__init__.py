"""Sentinel POMDP Package.

Partially Observable Markov Decision Process modeling, state estimation,
and belief updating for Sentinel surveillance domains.
"""

from sentinel_pomdp.states import State, GridState, SecurityState
from sentinel_pomdp.actions import Action, SentinelAction, InvestigationAction
from sentinel_pomdp.observations import (
    Observation,
    BaseObservation,
    SecurityObservation,
    SentinelObservation,
    NO_DETECTION,
)
from sentinel_pomdp.model import (
    POMDPModel,
    SentinelPOMDP,
    OBSERVATION_MODEL,
    validate_observation_model,
)
from sentinel_pomdp.belief import (
    BeliefDistribution,
    BeliefState,
    initial_belief,
    update_belief,
)
from sentinel_pomdp.information import (
    entropy,
    possible_observations,
    observation_probability,
    expected_posterior_entropy,
    expected_information_gain,
)
from sentinel_pomdp.planner import rank_actions, select_action

__all__ = [
    "State",
    "GridState",
    "SecurityState",
    "Action",
    "SentinelAction",
    "InvestigationAction",
    "Observation",
    "BaseObservation",
    "SecurityObservation",
    "SentinelObservation",
    "NO_DETECTION",
    "POMDPModel",
    "SentinelPOMDP",
    "OBSERVATION_MODEL",
    "validate_observation_model",
    "BeliefDistribution",
    "BeliefState",
    "initial_belief",
    "update_belief",
    "entropy",
    "possible_observations",
    "observation_probability",
    "expected_posterior_entropy",
    "expected_information_gain",
    "rank_actions",
    "select_action",
]

__version__ = "0.1.0"
