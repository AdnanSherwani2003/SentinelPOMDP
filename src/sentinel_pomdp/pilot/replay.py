from __future__ import annotations

from dataclasses import dataclass

from sentinel_pomdp.calibration.estimation import CalibrationEstimate
from sentinel_pomdp.calibration.metrics import PilotPrediction

from .dataset import ClaimType, PilotDataset, PilotSplit
from .splits import SplitManifest, validate_manifest


@dataclass(frozen=True)
class ReplayPolicy:
    name: str
    use_logged_observation: bool
    answer_threshold: float
    minimum_independent_sources: int = 1
    action_cost: float = .08


def _posterior(prior: dict[str, float], likelihoods: dict[str, dict[str, float]],
               token: str) -> dict[str, float]:
    unnormalized = {state: prior[state] * likelihoods[state][token] for state in prior}
    total = sum(unnormalized.values())
    if total <= 0:
        raise ValueError("observation has zero probability under every state")
    return {state: value / total for state, value in unnormalized.items()}


def replay_logged_policy(dataset: PilotDataset, manifest: SplitManifest,
                         estimate: CalibrationEstimate, policy: ReplayPolicy, *,
                         split: PilotSplit = PilotSplit.TEST) -> list[PilotPrediction]:
    """Replay only logged observations; never synthesize unavailable action outcomes."""
    validate_manifest(dataset, manifest)
    if estimate.dataset_version != dataset.version:
        raise ValueError("calibration estimate dataset version mismatch")
    observations = {(item.case_id, item.action_id): item for item in dataset.observations}
    predictions = []
    for case in dataset.cases:
        if manifest.assignments[case.case_id] != split:
            continue
        visible_case = case.evaluation_view()
        probabilities = dict(estimate.prior)
        actions = []
        groups = set()
        if policy.use_logged_observation:
            # Current narrow pilot has one registered logged action. Additional actions
            # require an actually recorded outcome; absent counterfactuals are not invented.
            for action in sorted(estimate.observation_model):
                observation = observations.get((case.case_id, action))
                if observation is None or not observation.observed or not observation.available_at_decision_time:
                    continue
                probabilities = _posterior(
                    probabilities, estimate.observation_model[action], observation.observation_token)
                actions.append(action)
                if observation.source_group_id:
                    groups.add(observation.source_group_id)
                break
        predicted = max(probabilities, key=probabilities.get)
        evidence_sufficient = (
            visible_case["claim_type"] == ClaimType.DELIVERY_TIMELINESS.value
            and len(groups) >= policy.minimum_independent_sources)
        decision = "ANSWER" if evidence_sufficient and probabilities[predicted] >= policy.answer_threshold else "ABSTAIN"
        predictions.append(PilotPrediction(
            case_id=case.case_id, probabilities=probabilities, decision=decision,
            predicted_label=predicted if decision == "ANSWER" else None,
            evidence_sufficient=evidence_sufficient, actions_taken=actions,
            investigation_cost=len(actions) * policy.action_cost))
    return predictions
