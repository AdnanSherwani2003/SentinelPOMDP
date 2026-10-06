"""Action definitions for the Sentinel POMDP environment.

This module defines actions available to sentinel agents.
"""

from enum import Enum
from typing import Tuple, List, Dict


class InvestigationAction(str, Enum):
    INSPECT_AUTH = "inspect_auth"
    INSPECT_PROCESS = "inspect_process"
    INSPECT_NETWORK = "inspect_network"
    INSPECT_VULNERABILITY = "inspect_vulnerability"


class SentinelAction(str, Enum):
    """Actions executable by a Sentinel agent."""
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"
    STAY = "STAY"
    SCAN = "SCAN"
    INTERCEPT = "INTERCEPT"

    def get_delta(self) -> Tuple[int, int]:
        """Return directional grid translation offset (dx, dy)."""
        deltas: Dict[SentinelAction, Tuple[int, int]] = {
            SentinelAction.NORTH: (0, 1),
            SentinelAction.SOUTH: (0, -1),
            SentinelAction.EAST: (1, 0),
            SentinelAction.WEST: (-1, 0),
            SentinelAction.STAY: (0, 0),
            SentinelAction.SCAN: (0, 0),
            SentinelAction.INTERCEPT: (0, 0),
        }
        return deltas[self]

    @classmethod
    def movement_actions(cls) -> List["SentinelAction"]:
        """Return list of movement actions."""
        return [cls.NORTH, cls.SOUTH, cls.EAST, cls.WEST, cls.STAY]

    @classmethod
    def all_actions(cls) -> List["SentinelAction"]:
        """Return list of all possible sentinel actions."""
        return list(cls)


Action = SentinelAction
