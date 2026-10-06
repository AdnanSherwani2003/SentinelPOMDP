"""Observation definitions for the Sentinel POMDP environment.

This module defines sensory feedback and observations emitted by the environment.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Optional, Any


class BaseObservation:
    """Abstract base class for observations."""

    def __eq__(self, other: Any) -> bool:
        raise NotImplementedError

    def __hash__(self) -> int:
        raise NotImplementedError


class Observation(str, Enum):
    # Authentication
    AUTH_NORMAL = "auth_normal"
    AUTH_UNUSUAL_LOGIN = "auth_unusual_login"
    AUTH_MFA_ANOMALY = "auth_mfa_anomaly"

    # Processes
    PROCESS_NORMAL = "process_normal"
    PROCESS_SUSPICIOUS_SCRIPT = "process_suspicious_script"
    PROCESS_ENCODED_POWERSHELL = "process_encoded_powershell"
    PROCESS_KNOWN_MALWARE = "process_known_malware"

    # Network
    NETWORK_NORMAL = "network_normal"
    NETWORK_RARE_DOMAIN = "network_rare_domain"
    NETWORK_C2_PATTERN = "network_c2_pattern"
    NETWORK_HIGH_UPLOAD = "network_high_upload"

    # Vulnerability
    VULN_NONE = "vuln_none"
    VULN_RELEVANT = "vuln_relevant"


SecurityObservation = Observation


@dataclass(frozen=True)
class SentinelObservation(BaseObservation):
    """Observation emitted by the sentinel sensor system.

    Attributes:
        target_detected: Whether the sensor detected a target signal.
        observed_pos: Estimated (x, y) coordinates of target if detected, else None.
        signal_quality: Confidence/strength of observation signal in [0.0, 1.0].
    """
    target_detected: bool
    observed_pos: Optional[Tuple[int, int]] = None
    signal_quality: float = 1.0

    def __repr__(self) -> str:
        if not self.target_detected:
            return "SentinelObservation(Detected=False)"
        return (
            f"SentinelObservation(Detected=True, Position={self.observed_pos}, "
            f"Quality={self.signal_quality:.2f})"
        )


NO_DETECTION = SentinelObservation(target_detected=False, observed_pos=None, signal_quality=0.0)
