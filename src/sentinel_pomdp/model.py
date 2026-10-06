"""POMDP Model interface and Sentinel domain model implementation.

This module defines the transition, observation, and reward dynamics
for partially observable Markov decision processes.
"""

from abc import ABC, abstractmethod
import math
import random
from typing import List, Tuple, Dict, Set, Optional

from sentinel_pomdp.states import State, GridState, SecurityState
from sentinel_pomdp.actions import Action, SentinelAction, InvestigationAction
from sentinel_pomdp.observations import Observation, SentinelObservation, NO_DETECTION


# Synthetic simulation parameters for security observation likelihoods:
# Encodes relative conditional probabilities P(o | s, a) for security investigation.
OBSERVATION_MODEL = {
    InvestigationAction.INSPECT_AUTH: {
        SecurityState.BENIGN: {
            Observation.AUTH_NORMAL: 0.85,
            Observation.AUTH_UNUSUAL_LOGIN: 0.10,
            Observation.AUTH_MFA_ANOMALY: 0.05,
        },
        SecurityState.CREDENTIAL_COMPROMISE: {
            Observation.AUTH_NORMAL: 0.10,
            Observation.AUTH_UNUSUAL_LOGIN: 0.60,
            Observation.AUTH_MFA_ANOMALY: 0.30,
        },
        SecurityState.MALWARE_COMPROMISE: {
            Observation.AUTH_NORMAL: 0.55,
            Observation.AUTH_UNUSUAL_LOGIN: 0.30,
            Observation.AUTH_MFA_ANOMALY: 0.15,
        },
        SecurityState.LATERAL_MOVEMENT: {
            Observation.AUTH_NORMAL: 0.20,
            Observation.AUTH_UNUSUAL_LOGIN: 0.60,
            Observation.AUTH_MFA_ANOMALY: 0.20,
        },
        SecurityState.DATA_EXFILTRATION: {
            Observation.AUTH_NORMAL: 0.40,
            Observation.AUTH_UNUSUAL_LOGIN: 0.40,
            Observation.AUTH_MFA_ANOMALY: 0.20,
        },
    },

    InvestigationAction.INSPECT_PROCESS: {
        SecurityState.BENIGN: {
            Observation.PROCESS_NORMAL: 0.90,
            Observation.PROCESS_SUSPICIOUS_SCRIPT: 0.07,
            Observation.PROCESS_ENCODED_POWERSHELL: 0.02,
            Observation.PROCESS_KNOWN_MALWARE: 0.01,
        },
        SecurityState.CREDENTIAL_COMPROMISE: {
            Observation.PROCESS_NORMAL: 0.65,
            Observation.PROCESS_SUSPICIOUS_SCRIPT: 0.20,
            Observation.PROCESS_ENCODED_POWERSHELL: 0.10,
            Observation.PROCESS_KNOWN_MALWARE: 0.05,
        },
        SecurityState.MALWARE_COMPROMISE: {
            Observation.PROCESS_NORMAL: 0.10,
            Observation.PROCESS_SUSPICIOUS_SCRIPT: 0.20,
            Observation.PROCESS_ENCODED_POWERSHELL: 0.40,
            Observation.PROCESS_KNOWN_MALWARE: 0.30,
        },
        SecurityState.LATERAL_MOVEMENT: {
            Observation.PROCESS_NORMAL: 0.15,
            Observation.PROCESS_SUSPICIOUS_SCRIPT: 0.25,
            Observation.PROCESS_ENCODED_POWERSHELL: 0.40,
            Observation.PROCESS_KNOWN_MALWARE: 0.20,
        },
        SecurityState.DATA_EXFILTRATION: {
            Observation.PROCESS_NORMAL: 0.20,
            Observation.PROCESS_SUSPICIOUS_SCRIPT: 0.30,
            Observation.PROCESS_ENCODED_POWERSHELL: 0.30,
            Observation.PROCESS_KNOWN_MALWARE: 0.20,
        },
    },

    InvestigationAction.INSPECT_NETWORK: {
        SecurityState.BENIGN: {
            Observation.NETWORK_NORMAL: 0.92,
            Observation.NETWORK_RARE_DOMAIN: 0.05,
            Observation.NETWORK_C2_PATTERN: 0.02,
            Observation.NETWORK_HIGH_UPLOAD: 0.01,
        },
        SecurityState.CREDENTIAL_COMPROMISE: {
            Observation.NETWORK_NORMAL: 0.65,
            Observation.NETWORK_RARE_DOMAIN: 0.15,
            Observation.NETWORK_C2_PATTERN: 0.10,
            Observation.NETWORK_HIGH_UPLOAD: 0.10,
        },
        SecurityState.MALWARE_COMPROMISE: {
            Observation.NETWORK_NORMAL: 0.15,
            Observation.NETWORK_RARE_DOMAIN: 0.20,
            Observation.NETWORK_C2_PATTERN: 0.55,
            Observation.NETWORK_HIGH_UPLOAD: 0.10,
        },
        SecurityState.LATERAL_MOVEMENT: {
            Observation.NETWORK_NORMAL: 0.15,
            Observation.NETWORK_RARE_DOMAIN: 0.15,
            Observation.NETWORK_C2_PATTERN: 0.40,
            Observation.NETWORK_HIGH_UPLOAD: 0.30,
        },
        SecurityState.DATA_EXFILTRATION: {
            Observation.NETWORK_NORMAL: 0.05,
            Observation.NETWORK_RARE_DOMAIN: 0.10,
            Observation.NETWORK_C2_PATTERN: 0.20,
            Observation.NETWORK_HIGH_UPLOAD: 0.65,
        },
    },

    InvestigationAction.INSPECT_VULNERABILITY: {
        SecurityState.BENIGN: {
            Observation.VULN_NONE: 0.80,
            Observation.VULN_RELEVANT: 0.20,
        },
        SecurityState.CREDENTIAL_COMPROMISE: {
            Observation.VULN_NONE: 0.75,
            Observation.VULN_RELEVANT: 0.25,
        },
        SecurityState.MALWARE_COMPROMISE: {
            Observation.VULN_NONE: 0.35,
            Observation.VULN_RELEVANT: 0.65,
        },
        SecurityState.LATERAL_MOVEMENT: {
            Observation.VULN_NONE: 0.30,
            Observation.VULN_RELEVANT: 0.70,
        },
        SecurityState.DATA_EXFILTRATION: {
            Observation.VULN_NONE: 0.45,
            Observation.VULN_RELEVANT: 0.55,
        },
    },
}


def validate_observation_model() -> None:
    tolerance = 1e-9

    for action, state_table in OBSERVATION_MODEL.items():
        for state, observation_table in state_table.items():

            probabilities = list(observation_table.values())

            if any(p < 0.0 or p > 1.0 for p in probabilities):
                raise ValueError(
                    f"Invalid probability for {action=} {state=}"
                )

            total = sum(probabilities)

            if abs(total - 1.0) > tolerance:
                raise ValueError(
                    f"Probabilities do not sum to 1 "
                    f"for {action=} {state=}: {total}"
                )


class POMDPModel(ABC):
    """Abstract Base Class for a Discrete POMDP Model."""

    @abstractmethod
    def get_states(self) -> List[State]:
        """Return full finite state space S."""
        pass

    @abstractmethod
    def get_actions(self) -> List[Action]:
        """Return full finite action space A."""
        pass

    @abstractmethod
    def get_observations(self) -> List[Observation]:
        """Return full finite observation space O."""
        pass

    @abstractmethod
    def transition_probability(self, state: State, action: Action, next_state: State) -> float:
        """Compute transition probability P(s' | s, a)."""
        pass

    @abstractmethod
    def observation_probability(self, next_state: State, action: Action, obs: Observation) -> float:
        """Compute observation probability P(o | s', a)."""
        pass

    @abstractmethod
    def reward(self, state: State, action: Action, next_state: State) -> float:
        """Compute reward R(s, a, s')."""
        pass

    def sample_next_state(self, state: State, action: Action) -> State:
        """Sample next state s' ~ P(s' | s, a)."""
        states = self.get_states()
        probs = [self.transition_probability(state, action, s_prime) for s_prime in states]
        return random.choices(states, weights=probs, k=1)[0]

    def sample_observation(self, next_state: State, action: Action) -> Observation:
        """Sample observation o ~ P(o | s', a)."""
        observations = self.get_observations()
        probs = [self.observation_probability(next_state, action, obs) for obs in observations]
        return random.choices(observations, weights=probs, k=1)[0]


class SentinelPOMDP(POMDPModel):
    """Concrete POMDP Model for Sentinel surveillance on a 2D grid.

    The sentinel moves on a grid and attempts to locate/intercept an intruder target.
    Sensor detection probability decays exponentially with distance, with enhanced scan mode.
    """

    def __init__(
        self,
        grid_width: int = 5,
        grid_height: int = 5,
        target_move_prob: float = 0.2,
        sensor_decay_rate: float = 0.4,
        false_positive_prob: float = 0.05,
        scan_boost_factor: float = 1.5,
    ):
        """Initialize Sentinel POMDP Model.

        Args:
            grid_width: Width of 2D grid.
            grid_height: Height of 2D grid.
            target_move_prob: Probability target moves to adjacent cell each timestep.
            sensor_decay_rate: Exponential decay rate alpha for detection distance.
            false_positive_prob: Base rate of false positive detections.
            scan_boost_factor: Multiplier for sensor detection probability during SCAN action.
        """
        self.width = grid_width
        self.height = grid_height
        self.target_move_prob = target_move_prob
        self.sensor_decay = sensor_decay_rate
        self.false_positive_prob = false_positive_prob
        self.scan_boost = scan_boost_factor

        self._states: List[GridState] = self._generate_states()
        self._actions: List[SentinelAction] = SentinelAction.all_actions()
        self._observations: List[SentinelObservation] = self._generate_observations()

    def _generate_states(self) -> List[GridState]:
        states = []
        for sx in range(self.width):
            for sy in range(self.height):
                for tx in range(self.width):
                    for ty in range(self.height):
                        for det in (False, True):
                            states.append(
                                GridState(
                                    sentinel_pos=(sx, sy),
                                    target_pos=(tx, ty),
                                    target_detected=det,
                                )
                            )
        return states

    def _generate_observations(self) -> List[SentinelObservation]:
        obs_list: List[SentinelObservation] = [NO_DETECTION]
        for tx in range(self.width):
            for ty in range(self.height):
                obs_list.append(
                    SentinelObservation(
                        target_detected=True,
                        observed_pos=(tx, ty),
                        signal_quality=1.0,
                    )
                )
        return obs_list

    def get_states(self) -> List[GridState]:
        return self._states

    def get_actions(self) -> List[SentinelAction]:
        return self._actions

    def get_observations(self) -> List[SentinelObservation]:
        return self._observations

    def _clamp_pos(self, x: int, y: int) -> Tuple[int, int]:
        return (max(0, min(self.width - 1, x)), max(0, min(self.height - 1, y)))

    def transition_probability(self, state: State, action: Action, next_state: State) -> float:
        if not isinstance(state, GridState) or not isinstance(next_state, GridState):
            return 0.0

        # Intercept action terminal state logic
        if state.target_detected:
            return 1.0 if next_state == state else 0.0

        # Sentinel deterministic movement
        dx, dy = action.get_delta()
        expected_sx, expected_sy = self._clamp_pos(
            state.sentinel_pos[0] + dx, state.sentinel_pos[1] + dy
        )

        if next_state.sentinel_pos != (expected_sx, expected_sy):
            return 0.0

        # Check intercept action detection flag transition
        if action == SentinelAction.INTERCEPT:
            if state.sentinel_pos == state.target_pos:
                expected_det = True
            else:
                expected_det = False
            if next_state.target_detected != expected_det:
                return 0.0
        else:
            if next_state.target_detected != state.target_detected:
                return 0.0

        # Target movement distribution
        tx, ty = state.target_pos
        neighbors = []
        for d_x, d_y in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nx, ny = tx + d_x, ty + d_y
            if 0 <= nx < self.width and 0 <= ny < self.height:
                neighbors.append((nx, ny))

        p_stay = 1.0 - self.target_move_prob
        p_move_each = self.target_move_prob / len(neighbors) if neighbors else 0.0

        ntx, nty = next_state.target_pos
        if (ntx, nty) == (tx, ty):
            return p_stay
        elif (ntx, nty) in neighbors:
            return p_move_each
        else:
            return 0.0

    def observation_probability(self, next_state: State, action: Action, obs: Observation) -> float:
        if not isinstance(next_state, GridState) or not isinstance(obs, SentinelObservation):
            return 0.0

        dist = next_state.manhattan_distance()
        base_detect_prob = math.exp(-self.sensor_decay * dist)

        if action == SentinelAction.SCAN:
            detect_prob = min(0.99, base_detect_prob * self.scan_boost)
        else:
            detect_prob = base_detect_prob

        if not obs.target_detected:
            # P(No detection | state, action) = 1 - detect_prob
            return max(0.001, 1.0 - detect_prob)

        # True target location report vs false positive
        true_pos = next_state.target_pos
        if obs.observed_pos == true_pos:
            return detect_prob * (1.0 - self.false_positive_prob)
        else:
            # False observation at wrong location
            other_cells = self.width * self.height - 1
            return detect_prob * (self.false_positive_prob / max(1, other_cells))

    def reward(self, state: State, action: Action, next_state: State) -> float:
        if not isinstance(state, GridState) or not isinstance(next_state, GridState):
            return 0.0

        if action == SentinelAction.INTERCEPT:
            if state.sentinel_pos == state.target_pos:
                return 100.0  # Successful target neutralization
            return -20.0  # Failed intercept penalty

        if action == SentinelAction.SCAN:
            return -2.0  # Scanning energy cost

        return -1.0  # Movement / step cost
