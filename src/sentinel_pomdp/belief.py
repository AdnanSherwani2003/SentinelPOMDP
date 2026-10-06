"""Belief distribution and Bayesian belief update engine for POMDPs.

This module maintains probability distributions over state spaces and
performs exact recursive Bayesian filtering.
"""

from typing import Dict, List, Tuple, Optional
import math
import numpy as np

from sentinel_pomdp.states import State, SecurityState
from sentinel_pomdp.actions import Action, InvestigationAction
from sentinel_pomdp.observations import Observation
from sentinel_pomdp.model import POMDPModel, OBSERVATION_MODEL


BeliefState = Dict[SecurityState, float]


def initial_belief() -> BeliefState:
    return {
        SecurityState.BENIGN: 0.45,
        SecurityState.CREDENTIAL_COMPROMISE: 0.20,
        SecurityState.MALWARE_COMPROMISE: 0.15,
        SecurityState.LATERAL_MOVEMENT: 0.12,
        SecurityState.DATA_EXFILTRATION: 0.08,
    }


def update_belief(
    belief: BeliefState,
    action: InvestigationAction,
    observation: Observation,
) -> BeliefState:
    unnormalized: BeliefState = {}

    for state, prior_probability in belief.items():
        observation_probability = (
            OBSERVATION_MODEL[action][state].get(observation, 0.0)
        )

        unnormalized[state] = (
            observation_probability * prior_probability
        )

    normalization_constant = sum(unnormalized.values())

    if normalization_constant <= 0:
        raise ValueError(
            "Observation has zero probability under the current model."
        )

    posterior = {
        state: probability / normalization_constant
        for state, probability in unnormalized.items()
    }

    return posterior


class BeliefDistribution:
    """Discrete probability distribution over POMDP state space S."""

    def __init__(self, probabilities: Dict[State, float]):
        """Initialize belief distribution.

        Args:
            probabilities: Mapping from State objects to non-negative probabilities.
        """
        self._probs: Dict[State, float] = dict(probabilities)
        self.normalize()

    @classmethod
    def uniform(cls, states: List[State]) -> "BeliefDistribution":
        """Create uniform belief distribution over provided states."""
        if not states:
            raise ValueError("State space cannot be empty.")
        p = 1.0 / len(states)
        return cls({s: p for s in states})

    @classmethod
    def point_mass(cls, target_state: State, all_states: List[State]) -> "BeliefDistribution":
        """Create point-mass distribution concentrated on target_state."""
        if target_state not in all_states:
            raise ValueError("Target state must exist in all_states list.")
        probs = {s: 0.0 for s in all_states}
        probs[target_state] = 1.0
        return cls(probs)

    def get(self, state: State) -> float:
        """Get probability assigned to a specific state."""
        return self._probs.get(state, 0.0)

    def __getitem__(self, state: State) -> float:
        return self.get(state)

    def items(self):
        """Return iterable of (state, probability) pairs."""
        return self._probs.items()

    def states(self) -> List[State]:
        """Return list of states with non-zero probability."""
        return list(self._probs.keys())

    def normalize(self) -> "BeliefDistribution":
        """Normalize distribution so probabilities sum to 1.0."""
        total = sum(self._probs.values())
        if total <= 0:
            # Fallback to uniform if sum is zero or invalid
            n = len(self._probs)
            if n > 0:
                p = 1.0 / n
                self._probs = {s: p for s in self._probs}
            return self

        self._probs = {s: p / total for s, p in self._probs.items()}
        return self

    def entropy(self) -> float:
        """Compute Shannon entropy H(b) = - sum(b(s) * log2(b(s))) in bits."""
        h = 0.0
        for p in self._probs.values():
            if p > 1e-12:
                h -= p * math.log2(p)
        return h

    def most_likely_state(self) -> Tuple[State, float]:
        """Return tuple of (most_probable_state, max_probability)."""
        best_state = max(self._probs.items(), key=lambda item: item[1])
        return best_state[0], best_state[1]

    def update(
        self,
        model: POMDPModel,
        action: Action,
        observation: Observation,
    ) -> "BeliefDistribution":
        """Perform exact Bayesian belief update.

        Computes next belief b'(s') proportional to:
            O(o | s', a) * sum_{s} [ T(s' | s, a) * b(s) ]

        Args:
            model: POMDP Model containing transition and observation probabilities.
            action: Action executed by agent.
            observation: Observation received from environment.

        Returns:
            Updated BeliefDistribution instance.
        """
        all_states = model.get_states()
        next_probs: Dict[State, float] = {}

        # Pre-calculate prior belief values
        prior_b = np.array([self.get(s) for s in all_states], dtype=np.float64)

        # 1. State transition step: P(s' | b, a) = sum_s T(s' | s, a) * b(s)
        # Compute predicted belief over s'
        pred_b = np.zeros(len(all_states), dtype=np.float64)
        for j, s_prime in enumerate(all_states):
            t_row = np.array(
                [model.transition_probability(s, action, s_prime) for s in all_states],
                dtype=np.float64,
            )
            pred_b[j] = np.dot(t_row, prior_b)

        # 2. Observation update step: b'(s') = O(o | s', a) * pred_b(s')
        obs_probs = np.array(
            [model.observation_probability(s_prime, action, observation) for s_prime in all_states],
            dtype=np.float64,
        )

        unnorm_b = obs_probs * pred_b

        total_obs_prob = np.sum(unnorm_b)

        if total_obs_prob <= 1e-15:
            # Fallback if observation was unexpected or probability is ~0
            updated_probs = {s: pred_b[i] for i, s in enumerate(all_states)}
        else:
            norm_b = unnorm_b / total_obs_prob
            updated_probs = {s: float(norm_b[i]) for i, s in enumerate(all_states)}

        return BeliefDistribution(updated_probs)
