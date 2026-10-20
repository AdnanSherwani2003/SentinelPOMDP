"""Ground-truth review is intentionally separate from evidence extraction review."""
from __future__ import annotations

from .dataset import LabelReview, LabelStatus, PilotCase


def add_label_review(case: PilotCase, review: LabelReview) -> PilotCase:
    if review.reviewer_ref in {item.reviewer_ref for item in case.reviews}:
        raise ValueError("a reviewer may submit only one label review per case")
    reviews = [*case.reviews, review]
    labels = {item.label for item in reviews}
    status = LabelStatus.DISPUTED if len(labels) > 1 else LabelStatus.IN_REVIEW
    return case.model_copy(update={"reviews": reviews, "label_status": status})


def adjudicate_label(case: PilotCase, *, label: str | None, adjudicator_ref: str,
                     source_ids: list[str], method: str) -> PilotCase:
    if not case.reviews:
        raise ValueError("adjudication requires at least one independent review")
    if not adjudicator_ref or adjudicator_ref in {item.reviewer_ref for item in case.reviews}:
        raise ValueError("adjudicator must be identified and independent of reviewers")
    if label is None:
        return case.model_copy(update={
            "ground_truth_label": None, "ground_truth_source_ids": [],
            "independent_ground_truth": False, "label_status": LabelStatus.UNKNOWN,
            "label_method": method})
    if not source_ids:
        raise ValueError("adjudicated labels require authoritative source provenance")
    return case.model_copy(update={
        "ground_truth_label": label, "ground_truth_source_ids": source_ids,
        "independent_ground_truth": True, "label_status": LabelStatus.ADJUDICATED,
        "label_method": f"{method}; adjudicator={adjudicator_ref}"})
