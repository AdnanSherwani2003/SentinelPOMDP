from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from .dataset import PilotDataset, PilotSplit


class SplitManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str
    dataset_version: str
    strategy: str
    assignments: dict[str, PilotSplit]
    group_assignments: dict[str, PilotSplit]
    created_by: str
    warnings: list[str] = Field(default_factory=list)


def chronological_group_split(dataset: PilotDataset, *, train_fraction: float = .6,
                              validation_fraction: float = .2,
                              created_by: str = "deterministic-split-v1") -> SplitManifest:
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("split fractions must be between zero and one")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train and validation fractions must leave a test split")
    grouped = defaultdict(list)
    for case in dataset.cases:
        grouped[case.leakage_group_id].append(case)
    ordered = sorted(grouped, key=lambda group: (
        min(case.event_time for case in grouped[group]), group))
    if len(ordered) < 3:
        raise ValueError("at least three leakage groups are required")
    train_end = max(1, int(len(ordered) * train_fraction))
    validation_end = max(train_end + 1, int(len(ordered) * (train_fraction + validation_fraction)))
    validation_end = min(validation_end, len(ordered) - 1)
    group_assignments = {}
    for index, group in enumerate(ordered):
        split = (PilotSplit.TRAIN if index < train_end else
                 PilotSplit.VALIDATION if index < validation_end else PilotSplit.TEST)
        group_assignments[group] = split
    assignments = {case.case_id: group_assignments[case.leakage_group_id]
                   for case in dataset.cases}
    manifest = SplitManifest(
        dataset_id=dataset.dataset_id, dataset_version=dataset.version,
        strategy="chronological_group_holdout", assignments=assignments,
        group_assignments=group_assignments, created_by=created_by)
    validate_manifest(dataset, manifest)
    return manifest


def validate_manifest(dataset: PilotDataset, manifest: SplitManifest) -> None:
    if manifest.dataset_id != dataset.dataset_id or manifest.dataset_version != dataset.version:
        raise ValueError("split manifest dataset version mismatch")
    if set(manifest.assignments) != {case.case_id for case in dataset.cases}:
        raise ValueError("split manifest must assign every case exactly once")
    observed: dict[str, PilotSplit] = {}
    for case in dataset.cases:
        split = manifest.assignments[case.case_id]
        previous = observed.setdefault(case.leakage_group_id, split)
        if previous != split:
            raise ValueError("leakage group appears in multiple splits")
        if manifest.group_assignments.get(case.leakage_group_id) != split:
            raise ValueError("case and group split assignments disagree")
    if set(manifest.assignments.values()) != set(PilotSplit):
        raise ValueError("train, validation, and test must all be represented")
