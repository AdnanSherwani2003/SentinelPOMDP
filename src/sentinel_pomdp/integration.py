"""Domain adapter: existing enum-based simulator -> domain-neutral POMDP planner.

This retains the repository's observation probabilities, action costs and
answer/abstain utilities. It deliberately does not inspect the hidden truth.
"""

from __future__ import annotations

from sentinel_pomdp.actions import InvestigationAction
from sentinel_pomdp.model import CALIBRATED_OBSERVATION_MODEL, OBSERVATION_MODEL
from sentinel_pomdp.multistep import MultiStepPlanner, PlanningConfig, SupportPredicate
from sentinel_pomdp.reward import (
    ACTION_COSTS,
    DEFAULT_REWARD_CONFIG,
    RewardConfig,
)
from sentinel_pomdp.states import SecurityState


def security_evidence_support(hypothesis: str, history: Sequence[tuple[str, str]]) -> bool:
    """Explicit, testable evidence-support policy for the synthetic benchmark domain.

    Distinguishes high posterior probability from adequate supporting evidence:
    - Evidence cannot be empty (requires at least one real observation).
    - BENIGN requires observed normalcy and strictly forbids any attack anomaly.
    - An attack hypothesis requires affirmative anomaly evidence corresponding to that vector.
    - Hypotheses with contradictory evidence are vetoed (agent will ABSTAIN).
    """
    if not history:
        return False

    obs_set = set(history)
    anomalies = {
        (InvestigationAction.INSPECT_AUTH.value, "auth_unusual_login"),
        (InvestigationAction.INSPECT_AUTH.value, "auth_mfa_anomaly"),
        (InvestigationAction.INSPECT_PROCESS.value, "process_suspicious_script"),
        (InvestigationAction.INSPECT_PROCESS.value, "process_encoded_powershell"),
        (InvestigationAction.INSPECT_PROCESS.value, "process_known_malware"),
        (InvestigationAction.INSPECT_NETWORK.value, "network_rare_domain"),
        (InvestigationAction.INSPECT_NETWORK.value, "network_c2_pattern"),
        (InvestigationAction.INSPECT_NETWORK.value, "network_high_upload"),
        (InvestigationAction.INSPECT_VULNERABILITY.value, "vuln_relevant"),
    }

    has_anomaly = bool(obs_set & anomalies)

    if hypothesis == SecurityState.BENIGN.value:
        # Benign is supported only if observations were gathered and NO attack anomaly was observed.
        return not has_anomaly

    if hypothesis == SecurityState.CREDENTIAL_COMPROMISE.value:
        return bool(obs_set & {
            (InvestigationAction.INSPECT_AUTH.value, "auth_unusual_login"),
            (InvestigationAction.INSPECT_AUTH.value, "auth_mfa_anomaly"),
        })

    if hypothesis == SecurityState.MALWARE_COMPROMISE.value:
        return bool(obs_set & {
            (InvestigationAction.INSPECT_PROCESS.value, "process_known_malware"),
            (InvestigationAction.INSPECT_PROCESS.value, "process_encoded_powershell"),
            (InvestigationAction.INSPECT_NETWORK.value, "network_c2_pattern"),
        })

    if hypothesis == SecurityState.LATERAL_MOVEMENT.value:
        return bool(obs_set & {
            (InvestigationAction.INSPECT_AUTH.value, "auth_unusual_login"),
            (InvestigationAction.INSPECT_PROCESS.value, "process_encoded_powershell"),
            (InvestigationAction.INSPECT_NETWORK.value, "network_rare_domain"),
        }) and has_anomaly

    if hypothesis == SecurityState.DATA_EXFILTRATION.value:
        return (InvestigationAction.INSPECT_NETWORK.value, "network_high_upload") in obs_set

    return False


def build_investigation_planner(
    horizon: int = 2,
    gamma: float = 0.95,
    reward_config: RewardConfig = DEFAULT_REWARD_CONFIG,
    *,
    model_version: str = "baseline",
    use_support_predicate: bool = False,
    support_predicate: SupportPredicate | None = None,
    min_observations: int = 0,
    answer_threshold: float | None = None,
) -> MultiStepPlanner:
    """Build a lookahead policy using the baseline or calibrated observation model.

    Horizon 1 and horizon 2 differ only in how far they look ahead. The
    information-gain reward component is switched on for this adapter to match
    the old decision layer's immediate action utility (information gain - cost).
    This is a synthetic benchmark adapter, not a real evidence verifier.
    """
    raw_model = (
        CALIBRATED_OBSERVATION_MODEL
        if model_version == "calibrated"
        else OBSERVATION_MODEL
    )

    observation_model = {
        action.value: {
            state.value: {obs.value: probability for obs, probability in row.items()}
            for state, row in states.items()
        }
        for action, states in raw_model.items()
    }
    action_costs = {
        action.value: (
            reward_config.operational_cost_weight * costs.operational
            + reward_config.privacy_cost_weight * costs.privacy
            + reward_config.latency_cost_weight * costs.latency
        )
        for action, costs in ACTION_COSTS.items()
    }

    effective_support_predicate: SupportPredicate | None = None
    if use_support_predicate:
        effective_support_predicate = (
            security_evidence_support if support_predicate is None else support_predicate
        )
    elif support_predicate is not None:
        effective_support_predicate = support_predicate

    threshold = (
        reward_config.min_answer_confidence
        if answer_threshold is None
        else answer_threshold
    )

    return MultiStepPlanner(
        states=[state.value for state in SecurityState],
        observation_model=observation_model,
        action_costs=action_costs,
        support_predicate=effective_support_predicate,
        config=PlanningConfig(
            horizon=horizon,
            gamma=gamma,
            correct_answer_reward=reward_config.correct_answer_reward,
            incorrect_answer_penalty=reward_config.wrong_answer_penalty,
            abstain_reward=-reward_config.abstain_penalty,
            answer_threshold=threshold,
            min_observations=min_observations,
            information_gain_weight=reward_config.information_gain_weight,
        ),
    )
