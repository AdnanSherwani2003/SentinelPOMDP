"""State definitions for the Sentinel POMDP environment.

This module defines base and domain-specific state representations.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Any


class SecurityState(str, Enum):
    BENIGN = "benign"
    CREDENTIAL_COMPROMISE = "credential_compromise"
    MALWARE_COMPROMISE = "malware_compromise"
    LATERAL_MOVEMENT = "lateral_movement"
    DATA_EXFILTRATION = "data_exfiltration"


class State:
    """Abstract base class for POMDP states."""

    def __eq__(self, other: Any) -> bool:
        raise NotImplementedError

    def __hash__(self) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class GridState(State):
    """Discrete state representation for a Sentinel surveillance grid.

    Attributes:
        sentinel_pos: (x, y) coordinates of the sentinel agent.
        target_pos: (x, y) coordinates of the target/intruder.
        target_detected: Flag indicating whether target has been intercepted/detected.
    """
    sentinel_pos: Tuple[int, int]
    target_pos: Tuple[int, int]
    target_detected: bool = False

    def manhattan_distance(self) -> int:
        """Calculate Manhattan distance between sentinel and target."""
        return abs(self.sentinel_pos[0] - self.target_pos[0]) + abs(
            self.sentinel_pos[1] - self.target_pos[1]
        )

    def euclidean_distance(self) -> float:
        """Calculate Euclidean distance between sentinel and target."""
        dx = self.sentinel_pos[0] - self.target_pos[0]
        dy = self.sentinel_pos[1] - self.target_pos[1]
        return (dx * dx + dy * dy) ** 0.5

    def __repr__(self) -> str:
        return (
            f"GridState(Sentinel={self.sentinel_pos}, Target={self.target_pos}, "
            f"Detected={self.target_detected})"
        )
