from __future__ import annotations

from collections import Counter, defaultdict
from math import sqrt

from pydantic import BaseModel, ConfigDict, Field

from sentinel_pomdp.pilot import LabelStatus, PilotDataset, PilotSplit, SplitManifest, validate_manifest


class Interval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    estimate: float = Field(ge=0, le=1)
    low: float = Field(ge=0, le=1)
    high: float = Field(ge=0, le=1)
    count: int = Field(ge=0)
    denominator: int = Field(ge=0)


class CalibrationEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str
    dataset_version: str
    split: str = "TRAIN"
    method: str
    smoothing_alpha: float
    labels: list[str]
    prior: dict[str, float]
    prior_intervals: dict[str, Interval]
    observation_model: dict[str, dict[str, dict[str, float]]]
    likelihood_intervals: dict[str, dict[str, dict[str, Interval]]]
    class_counts: dict[str, int]
    action_state_counts: dict[str, dict[str, int]]
    usable_cases: int
    excluded_cases: int
    status: str
    warnings: list[str]


def _wilson(count: int, total: int, estimate: float, z: float = 1.96) -> Interval:
    if total == 0:
        return Interval(estimate=estimate, low=0, high=1, count=count, denominator=total)
    raw = count / total
    denominator = 1 + z * z / total
    center = (raw + z * z / (2 * total)) / denominator
    margin = z * sqrt(raw * (1 - raw) / total + z * z / (4 * total * total)) / denominator
    return Interval(estimate=estimate, low=max(0, center - margin), high=min(1, center + margin),
                    count=count, denominator=total)


def estimate_categorical_model(dataset: PilotDataset, manifest: SplitManifest, *,
                               smoothing_alpha: float = .5,
                               minimum_state_samples: int = 5,
                               minimum_action_state_samples: int = 3) -> CalibrationEstimate:
    """Estimate P(state) and P(observation|state, action) from training records only."""
    validate_manifest(dataset, manifest)
    if smoothing_alpha <= 0:
        raise ValueError("smoothing_alpha must be positive")
    if minimum_state_samples < 1 or minimum_action_state_samples < 1:
        raise ValueError("minimum samples must be positive")
    train_ids = {case_id for case_id, split in manifest.assignments.items()
                 if split == PilotSplit.TRAIN}
    usable = [case for case in dataset.cases if case.case_id in train_ids
              and case.label_status in {LabelStatus.APPROVED, LabelStatus.ADJUDICATED}
              and case.independent_ground_truth and case.ground_truth_label]
    labels = list(dataset.allowed_labels)
    class_counts = Counter(case.ground_truth_label for case in usable)
    total = len(usable)
    prior_denominator = total + smoothing_alpha * len(labels)
    prior = {label: (class_counts[label] + smoothing_alpha) / prior_denominator
             for label in labels}
    prior_intervals = {label: _wilson(class_counts[label], total, prior[label]) for label in labels}
    labels_by_case = {case.case_id: case.ground_truth_label for case in usable}
    counts = defaultdict(lambda: defaultdict(Counter))
    denominators = defaultdict(Counter)
    actions = set()
    for observation in dataset.observations:
        if (observation.case_id not in labels_by_case or not observation.observed
                or not observation.available_at_decision_time):
            continue
        state = labels_by_case[observation.case_id]
        actions.add(observation.action_id)
        counts[observation.action_id][state][observation.observation_token] += 1
        denominators[observation.action_id][state] += 1
    outcomes = list(dataset.allowed_observations)
    model = {}
    intervals = {}
    warnings = []
    blocking_warnings = []
    selected_problem = sum(
        item.case_id in labels_by_case
        and item.selection_mechanism.value == "SUSPECTED_PROBLEM"
        for item in dataset.observations)
    missing = sum(item.case_id in labels_by_case and not item.observed
                  for item in dataset.observations)
    if selected_problem:
        warnings.append(f"NON_RANDOM_ACTION_SELECTION:{selected_problem}")
    if missing:
        warnings.append(f"MISSING_ACTION_OBSERVATIONS:{missing}")
    if not actions:
        warnings.append("NO_OBSERVED_ACTIONS")
        blocking_warnings.append("NO_OBSERVED_ACTIONS")
    for action in sorted(actions):
        model[action] = {}
        intervals[action] = {}
        for state in labels:
            denominator = denominators[action][state]
            smoothed_denominator = denominator + smoothing_alpha * len(outcomes)
            model[action][state] = {
                outcome: (counts[action][state][outcome] + smoothing_alpha) / smoothed_denominator
                for outcome in outcomes}
            intervals[action][state] = {
                outcome: _wilson(counts[action][state][outcome], denominator,
                                  model[action][state][outcome])
                for outcome in outcomes}
            if denominator < minimum_action_state_samples:
                warning = f"SPARSE_ACTION_STATE:{action}:{state}:{denominator}"
                warnings.append(warning)
                blocking_warnings.append(warning)
    for state in labels:
        if class_counts[state] < minimum_state_samples:
            warning = f"SPARSE_CLASS:{state}:{class_counts[state]}"
            warnings.append(warning)
            blocking_warnings.append(warning)
    if any(not denominators[action][state] for action in actions for state in labels):
        warnings.append("UNSUPPORTED_ACTION_STATE_COMBINATION")
        blocking_warnings.append("UNSUPPORTED_ACTION_STATE_COMBINATION")
    status = "EMPIRICALLY_ESTIMATED" if total and not blocking_warnings else "INSUFFICIENT_DATA"
    return CalibrationEstimate(
        dataset_id=dataset.dataset_id, dataset_version=dataset.version,
        method="categorical_counts_dirichlet_smoothing_wilson_intervals",
        smoothing_alpha=smoothing_alpha, labels=labels, prior=prior,
        prior_intervals=prior_intervals, observation_model=model,
        likelihood_intervals=intervals, class_counts=dict(class_counts),
        action_state_counts={action: dict(denominators[action]) for action in sorted(actions)},
        usable_cases=total, excluded_cases=len(train_ids) - total,
        status=status, warnings=sorted(set(warnings)))
