from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from .dataset import LabelStatus, PilotDataset


class DatasetValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid: bool
    case_count: int
    observation_count: int
    definitive_labels: int
    unresolved_labels: int
    missing_observations: int
    biased_selection_records: int
    unknown_source_dependencies: int
    errors: list[str]
    warnings: list[str]
    label_counts: dict[str, int]


def validate_dataset(dataset: PilotDataset) -> DatasetValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    case_ids = [case.case_id for case in dataset.cases]
    if not case_ids:
        errors.append("EMPTY_DATASET")
    if len(case_ids) != len(set(case_ids)):
        errors.append("DUPLICATE_CASE_ID")
    known = set(case_ids)
    evidence_sources: dict[str, set[str]] = {case_id: set() for case_id in known}
    seen_pairs: set[tuple[str, str]] = set()
    for observation in dataset.observations:
        if observation.case_id not in known:
            errors.append(f"ORPHAN_OBSERVATION:{observation.case_id}")
        pair = (observation.case_id, observation.action_id)
        if pair in seen_pairs:
            errors.append(f"DUPLICATE_CASE_ACTION:{observation.case_id}:{observation.action_id}")
        seen_pairs.add(pair)
        if observation.observation_token not in dataset.allowed_observations and observation.observed:
            errors.append(f"INVALID_OBSERVATION:{observation.case_id}:{observation.action_id}")
        if observation.observed and not observation.source_group_id:
            warnings.append(f"UNKNOWN_SOURCE_DEPENDENCY:{observation.case_id}:{observation.action_id}")
        if observation.case_id in evidence_sources and observation.source_document_id:
            evidence_sources[observation.case_id].add(observation.source_document_id)
    for case in dataset.cases:
        if set(case.ground_truth_source_ids) & evidence_sources[case.case_id]:
            errors.append(f"GROUND_TRUTH_EVIDENCE_LEAKAGE:{case.case_id}")
    definitive = [case for case in dataset.cases if case.label_status in {
        LabelStatus.ADJUDICATED, LabelStatus.APPROVED}]
    unresolved = len(dataset.cases) - len(definitive)
    if unresolved:
        warnings.append(f"UNRESOLVED_LABELS:{unresolved}")
    labels = Counter(case.ground_truth_label for case in definitive if case.ground_truth_label)
    return DatasetValidationReport(
        valid=not errors, case_count=len(dataset.cases),
        observation_count=len(dataset.observations), definitive_labels=len(definitive),
        unresolved_labels=unresolved,
        missing_observations=sum(not item.observed for item in dataset.observations),
        biased_selection_records=sum(item.selection_mechanism.value == "SUSPECTED_PROBLEM"
                                     for item in dataset.observations),
        unknown_source_dependencies=sum(item.observed and not item.source_group_id
                                        for item in dataset.observations),
        errors=sorted(set(errors)), warnings=sorted(set(warnings)),
        label_counts=dict(sorted(labels.items())))
