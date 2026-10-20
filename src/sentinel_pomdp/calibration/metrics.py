from __future__ import annotations

from math import log

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PilotPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    probabilities: dict[str, float]
    decision: str
    predicted_label: str | None = None
    evidence_sufficient: bool
    actions_taken: list[str] = Field(default_factory=list)
    investigation_cost: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def normalized(self) -> "PilotPrediction":
        if not self.probabilities or abs(sum(self.probabilities.values()) - 1) > 1e-9:
            raise ValueError("prediction probabilities must sum to 1")
        if any(value < 0 or value > 1 for value in self.probabilities.values()):
            raise ValueError("prediction probabilities must be in [0, 1]")
        if self.decision == "ANSWER" and not self.predicted_label:
            raise ValueError("answers require a predicted label")
        return self


class ReliabilityBin(BaseModel):
    lower: float
    upper: float
    count: int
    average_confidence: float
    empirical_accuracy: float


class CalibrationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scored_cases: int
    answered: int
    abstained: int
    correct_answers: int
    incorrect_answers: int
    coverage: float
    selective_accuracy: float
    false_answer_rate: float
    unsupported_answer_rate: float
    appropriate_abstentions: int
    unnecessary_abstentions: int
    multiclass_brier_score: float
    log_loss: float
    expected_calibration_error: float
    average_investigation_cost: float
    reliability_bins: list[ReliabilityBin]


def evaluate_predictions(predictions: list[PilotPrediction], labels: dict[str, str], *,
                         num_bins: int = 10) -> CalibrationMetrics:
    if not predictions or num_bins < 1:
        raise ValueError("predictions and positive num_bins are required")
    scored = [item for item in predictions if item.case_id in labels]
    if not scored:
        raise ValueError("no independently labeled predictions are available")
    classes = sorted(scored[0].probabilities)
    if not set(labels.values()) <= set(classes):
        raise ValueError("ground-truth label is outside the prediction classes")
    if any(set(item.probabilities) != set(classes) for item in scored):
        raise ValueError("prediction classes do not match label classes")
    answered = [item for item in scored if item.decision == "ANSWER"]
    correct = sum(item.predicted_label == labels[item.case_id] for item in answered)
    incorrect = len(answered) - correct
    unsupported = sum(not item.evidence_sufficient for item in answered)
    brier = sum(sum((item.probabilities[name] - (name == labels[item.case_id])) ** 2
                    for name in classes) for item in scored) / len(scored)
    log_loss = -sum(log(max(1e-15, item.probabilities[labels[item.case_id]]))
                    for item in scored) / len(scored)
    bin_rows = [[] for _ in range(num_bins)]
    for item in scored:
        predicted = max(item.probabilities, key=item.probabilities.get)
        confidence = item.probabilities[predicted]
        bin_rows[min(int(confidence * num_bins), num_bins - 1)].append(
            (confidence, predicted == labels[item.case_id]))
    bins = []
    ece = 0.0
    for index, rows in enumerate(bin_rows):
        if not rows:
            continue
        confidence = sum(row[0] for row in rows) / len(rows)
        accuracy = sum(row[1] for row in rows) / len(rows)
        ece += len(rows) / len(scored) * abs(confidence - accuracy)
        bins.append(ReliabilityBin(lower=index / num_bins, upper=(index + 1) / num_bins,
                                   count=len(rows), average_confidence=confidence,
                                   empirical_accuracy=accuracy))
    abstained = [item for item in scored if item.decision != "ANSWER"]
    appropriate = sum(max(item.probabilities, key=item.probabilities.get) != labels[item.case_id]
                      or not item.evidence_sufficient for item in abstained)
    return CalibrationMetrics(
        scored_cases=len(scored), answered=len(answered), abstained=len(abstained),
        correct_answers=correct, incorrect_answers=incorrect,
        coverage=len(answered) / len(scored),
        selective_accuracy=correct / len(answered) if answered else 0,
        false_answer_rate=incorrect / len(scored), unsupported_answer_rate=unsupported / len(scored),
        appropriate_abstentions=appropriate, unnecessary_abstentions=len(abstained) - appropriate,
        multiclass_brier_score=brier, log_loss=log_loss,
        expected_calibration_error=ece,
        average_investigation_cost=sum(item.investigation_cost for item in scored) / len(scored),
        reliability_bins=bins)


def evaluate_predictions_by_subgroup(
        predictions: list[PilotPrediction], labels: dict[str, str],
        subgroup_by_case: dict[str, str], *, minimum_cases: int = 10,
        num_bins: int = 10) -> dict[str, dict]:
    if minimum_cases < 1:
        raise ValueError("minimum_cases must be positive")
    results = {}
    for subgroup in sorted(set(subgroup_by_case.values())):
        case_ids = {case_id for case_id, value in subgroup_by_case.items()
                    if value == subgroup and case_id in labels}
        rows = [item for item in predictions if item.case_id in case_ids]
        if len(rows) < minimum_cases:
            results[subgroup] = {"status": "INSUFFICIENT_DATA", "sample_count": len(rows)}
        else:
            metrics = evaluate_predictions(
                rows, {case_id: labels[case_id] for case_id in case_ids}, num_bins=num_bins)
            results[subgroup] = {"status": "MEASURED", "sample_count": len(rows),
                                 "metrics": metrics.model_dump(mode="json")}
    return results
