"""Leakage-safe, interpretable Olist delivery-risk model evaluation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from math import exp, log, sqrt
from random import Random
from typing import Literal

import numpy as np

from .dataset import OlistDataset, Outcome
from .temporal import PredictionStage, TemporalExample, build_temporal_examples, feature_registry


MODEL_VERSION = "olist-logistic-temporal-v1"
FEATURE_VERSION = "olist-temporal-registry-v1"
REWARD_SPECIFICATION = {"correct_answer": 1.0, "wrong_answer": -5.0,
                        "abstain": 0.0, "investigation_cost": 0.0}


@dataclass(frozen=True)
class TemporalSplit:
    train: tuple[TemporalExample, ...]
    validation: tuple[TemporalExample, ...]
    test: tuple[TemporalExample, ...]
    train_fit: tuple[TemporalExample, ...]
    validation_tune: tuple[TemporalExample, ...]
    validation_start: datetime
    test_start: datetime


@dataclass(frozen=True)
class LogisticRiskModel:
    model_version: str
    feature_version: str
    stage: PredictionStage
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    missing_fill: tuple[float, ...]
    threshold: float
    status: Literal["CANDIDATE", "APPROVED"]
    approved_by: str | None
    training_cases: int
    validation_cases: int
    fitted_at: str

    def probability_late(self, values: dict[str, float | None]) -> float:
        row = []
        for index, name in enumerate(self.feature_names):
            value = values.get(name)
            row.append(self.missing_fill[index] if value is None else float(value))
        normalized = (np.asarray(row) - np.asarray(self.means)) / np.asarray(self.scales)
        score = self.intercept + float(np.dot(normalized, np.asarray(self.coefficients)))
        return 1.0 / (1.0 + exp(-max(-35.0, min(35.0, score))))

    def serve(self, example: TemporalExample) -> dict[str, object]:
        if self.status != "APPROVED" or not self.approved_by:
            return {"claim_type": "PROSPECTIVE_RISK", "status": "INSUFFICIENT_MODEL",
                    "decision": "ABSTAIN", "model_version": self.model_version,
                    "reason": "Reviewer approval is required before prospective risk can be served."}
        if example.stage is not self.stage:
            raise ValueError("prediction stage does not match approved model")
        probability = self.probability_late(example.values)
        confidence = max(probability, 1 - probability)
        return {"claim_type": "PROSPECTIVE_RISK", "status": "ESTIMATED_RISK",
                "decision": "ANSWER" if confidence >= self.threshold else "ABSTAIN",
                "probability_late": probability, "model_version": self.model_version,
                "calibration_status": "VALIDATED_ON_HOLDOUT",
                "limitations": ["Olist timestamps do not prove operational data-access time.",
                    "This forecast is not a verified historical fact."]}


def temporal_split(examples: list[TemporalExample]) -> TemporalSplit:
    ordered = sorted(examples, key=lambda item: (item.decision_time, item.order_id))
    if len(ordered) < 10:
        raise ValueError("at least 10 temporal examples are required")
    a = int(len(ordered) * .6)
    b = int(len(ordered) * .8)
    train, validation, test = tuple(ordered[:a]), tuple(ordered[a:b]), tuple(ordered[b:])
    validation_start = validation[0].decision_time
    test_start = test[0].decision_time
    # A label is fit/tuning eligible only after that order's delivery was knowable.
    train_fit = tuple(item for item in train if item.label_available_at < validation_start)
    validation_tune = tuple(item for item in validation if item.label_available_at < test_start)
    return TemporalSplit(train, validation, test, train_fit, validation_tune,
                         validation_start, test_start)


def _matrix(rows: tuple[TemporalExample, ...], names: tuple[str, ...],
            fills: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    raw = np.asarray([[np.nan if item.values.get(name) is None else item.values[name]
                       for name in names] for item in rows], dtype=float)
    if fills is None:
        fills = np.nanmedian(raw, axis=0)
        fills = np.where(np.isnan(fills), 0.0, fills)
    raw = np.where(np.isnan(raw), fills, raw)
    labels = np.asarray([item.label == Outcome.LATE.value for item in rows], dtype=float)
    return raw, labels, fills


def fit_logistic(split: TemporalSplit, stage: PredictionStage, *,
                 l2: float = .05, steps: int = 700, learning_rate: float = .08) -> LogisticRiskModel:
    if len(split.train_fit) < 10:
        raise ValueError("insufficient temporally available training labels")
    names = tuple(item["name"] for item in feature_registry(stage))
    x, y, fills = _matrix(split.train_fit, names)
    if len(set(y.tolist())) < 2:
        raise ValueError("both delivery outcomes are required to fit a predictive model")
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales = np.where(scales < 1e-9, 1.0, scales)
    z = (x - means) / scales
    weights = np.zeros(z.shape[1], dtype=float)
    base = min(.999, max(.001, float(y.mean())))
    intercept = log(base / (1 - base))
    for _ in range(steps):
        scores = np.clip(intercept + z @ weights, -35, 35)
        probabilities = 1 / (1 + np.exp(-scores))
        residual = probabilities - y
        weights -= learning_rate * ((z.T @ residual) / len(z) + l2 * weights)
        intercept -= learning_rate * float(residual.mean())
    candidate = LogisticRiskModel(MODEL_VERSION + "-" + stage.value.lower(), FEATURE_VERSION,
        stage, names, tuple(means), tuple(scales), tuple(weights), float(intercept), tuple(fills),
        .5, "CANDIDATE", None, len(split.train_fit), len(split.validation_tune),
        datetime.now(timezone.utc).isoformat())
    threshold = select_threshold(candidate, split.validation_tune)
    return LogisticRiskModel(**{**asdict(candidate), "threshold": threshold})


def select_threshold(model: LogisticRiskModel, validation: tuple[TemporalExample, ...]) -> float:
    best = None
    for threshold in [value / 100 for value in range(50, 100)]:
        utility = answered = wrong = 0
        for item in validation:
            probability = model.probability_late(item.values)
            if max(probability, 1 - probability) < threshold:
                continue
            answered += 1
            correct = (probability >= .5) == (item.label == Outcome.LATE.value)
            wrong += not correct
            utility += (REWARD_SPECIFICATION["correct_answer"] if correct
                        else REWARD_SPECIFICATION["wrong_answer"])
        candidate = (utility, -wrong, answered, -threshold)
        if best is None or candidate > best[0]:
            best = (candidate, threshold)
    assert best is not None
    return best[1]


def _probability_metrics(rows: tuple[TemporalExample, ...], probabilities: list[float],
                         threshold: float) -> dict[str, object]:
    labels = [int(item.label == Outcome.LATE.value) for item in rows]
    answered = [index for index, probability in enumerate(probabilities)
                if max(probability, 1 - probability) >= threshold]
    correct = sum((probabilities[index] >= .5) == bool(labels[index]) for index in answered)
    wrong = len(answered) - correct
    brier = sum((probability - label) ** 2 for probability, label in zip(probabilities, labels)) / len(rows)
    log_loss = -sum(label * log(max(probability, 1e-15))
                    + (1-label) * log(max(1-probability, 1e-15))
                    for probability, label in zip(probabilities, labels)) / len(rows)
    bins = []
    ece = 0.0
    for lower_index in range(10):
        indexes = [index for index, probability in enumerate(probabilities)
                   if lower_index / 10 <= probability < (lower_index + 1) / 10
                   or (lower_index == 9 and probability == 1)]
        if not indexes:
            continue
        average = sum(probabilities[index] for index in indexes) / len(indexes)
        rate = sum(labels[index] for index in indexes) / len(indexes)
        ece += len(indexes) / len(rows) * abs(average-rate)
        bins.append({"lower":lower_index/10,"upper":(lower_index+1)/10,
                     "count":len(indexes),"average_probability_late":average,
                     "empirical_late_rate":rate})
    utility = correct * REWARD_SPECIFICATION["correct_answer"] + wrong * REWARD_SPECIFICATION["wrong_answer"]
    expected_utility=0.0
    true_positive=true_negative=false_positive=false_negative=0
    for index in answered:
        probability=probabilities[index]
        predicts_late=probability >= .5
        expected_utility += ((probability if predicts_late else 1-probability)
            * REWARD_SPECIFICATION["correct_answer"]
            + ((1-probability) if predicts_late else probability)
            * REWARD_SPECIFICATION["wrong_answer"])
        if predicts_late and labels[index]: true_positive+=1
        elif predicts_late: false_positive+=1
        elif labels[index]: false_negative+=1
        else: true_negative+=1
    return {"cases":len(rows),"answered":len(answered),"abstained":len(rows)-len(answered),
        "correct_answers":correct,"incorrect_answers":wrong,"coverage":len(answered)/len(rows),
        "selective_accuracy":correct/len(answered) if answered else None,
        "abstention_rate":1-len(answered)/len(rows),"brier_score":brier,"log_loss":log_loss,
        "expected_calibration_error":ece,"reliability_bins":bins,
        "confusion_matrix_answered":{"true_positive":true_positive,"true_negative":true_negative,
            "false_positive":false_positive,"false_negative":false_negative},
        "expected_utility":expected_utility,"realized_utility":utility,
        "average_action_count":0.0,"investigation_cost":0.0}


def _bootstrap_interval(rows: tuple[TemporalExample, ...], probabilities: list[float],
                        threshold: float, seed: int, samples: int = 200) -> dict[str, list[float]]:
    random = Random(seed)
    coverage=[]; accuracy=[]; brier=[]
    for _ in range(samples):
        indexes=[random.randrange(len(rows)) for _ in rows]
        sample_rows=tuple(rows[index] for index in indexes)
        sample_probabilities=[probabilities[index] for index in indexes]
        metric=_probability_metrics(sample_rows,sample_probabilities,threshold)
        coverage.append(metric["coverage"]); brier.append(metric["brier_score"])
        if metric["selective_accuracy"] is not None: accuracy.append(metric["selective_accuracy"])
    def interval(values):
        ordered=sorted(values); return [ordered[int(.025*len(ordered))],ordered[int(.975*len(ordered))-1]]
    return {"coverage_95":interval(coverage),"selective_accuracy_95":interval(accuracy) if accuracy else [],
            "brier_95":interval(brier)}


def _wilson(successes: int, total: int) -> dict[str, float | int]:
    if not total:
        return {"estimate":0.0,"low":0.0,"high":1.0,"count":0,"denominator":0}
    z=1.96; estimate=successes/total; denominator=1+z*z/total
    center=(estimate+z*z/(2*total))/denominator
    margin=z*sqrt(estimate*(1-estimate)/total+z*z/(4*total*total))/denominator
    return {"estimate":estimate,"low":max(0.0,center-margin),"high":min(1.0,center+margin),
            "count":successes,"denominator":total}


def _categorical_likelihoods(rows: tuple[TemporalExample, ...], stage: PredictionStage) -> dict[str, object]:
    def bucket(name: str, value: float | None) -> str:
        if value is None: return "missing"
        if name=="estimated_lead_days": return "short" if value<10 else "medium" if value<20 else "long"
        if name=="seller_history_rate": return "low" if value<.05 else "medium" if value<.15 else "high"
        return "past_estimate" if value<0 else "0_to_7" if value<8 else "8_plus"
    names=["estimated_lead_days","seller_history_rate"]
    if stage is PredictionStage.CARRIER_HANDOFF: names.append("days_remaining_at_handoff")
    result={}
    states=(Outcome.LATE.value,Outcome.ON_TIME.value)
    for name in names:
        observed=sorted({bucket(name,item.values.get(name)) for item in rows})
        result[name]={}
        for state in states:
            state_rows=[item for item in rows if item.label==state]
            counts={value:sum(bucket(name,item.values.get(name))==value for item in state_rows)
                    for value in observed}
            denominator=len(state_rows)+.5*len(observed)
            result[name][state]={value:{
                "probability":(counts[value]+.5)/denominator,
                "count":counts[value],"state_denominator":len(state_rows)} for value in observed}
    return {"status":"EMPIRICALLY_ESTIMATED_FEATURE_ASSOCIATIONS",
        "method":"training-only categorical counts with Jeffreys smoothing",
        "not_an_action_model":True,"features":result}


def evaluate_predictive_models(dataset: OlistDataset, stage: PredictionStage, *, seed: int = 17) -> dict[str, object]:
    examples = build_temporal_examples(dataset, stage)
    split = temporal_split(examples)
    model = fit_logistic(split, stage)
    prior = sum(item.label == Outcome.LATE.value for item in split.train_fit) / len(split.train_fit)
    prior_probabilities = [prior] * len(split.test)
    model_probabilities = [model.probability_late(item.values) for item in split.test]
    prior_metrics = _probability_metrics(split.test, prior_probabilities, .5)
    logistic_metrics = _probability_metrics(split.test, model_probabilities, model.threshold)
    logistic_metrics["uncertainty"] = _bootstrap_interval(
        split.test, model_probabilities, model.threshold, seed)
    subgroups={}
    for available in (False,True):
        indexes=[i for i,item in enumerate(split.test) if item.seller_history_available is available]
        if indexes:
            subgroup_rows=tuple(split.test[i] for i in indexes)
            subgroup_probs=[model_probabilities[i] for i in indexes]
            subgroups["seller_history_available" if available else "seller_history_missing"] = \
                _probability_metrics(subgroup_rows,subgroup_probs,model.threshold)
    temporal_slices={}
    for quarter in range(4):
        start=quarter*len(split.test)//4
        end=(quarter+1)*len(split.test)//4
        if end<=start: continue
        rows=tuple(split.test[start:end]); probabilities=model_probabilities[start:end]
        temporal_slices[f"test_quarter_{quarter+1}"]={
            "decision_start":rows[0].decision_time.isoformat(),
            "decision_end":rows[-1].decision_time.isoformat(),
            **_probability_metrics(rows,probabilities,model.threshold)}
    class_counts={label:sum(item.label==label for item in split.train_fit)
                  for label in (Outcome.LATE.value,Outcome.ON_TIME.value)}
    return {"stage":stage.value,"target":"actual customer delivery date later than estimated delivery date",
        "hidden_states":[Outcome.LATE.value,Outcome.ON_TIME.value],"seed":seed,
        "model":asdict(model),"feature_registry":feature_registry(stage),
        "split":{"train":len(split.train),"validation":len(split.validation),"test":len(split.test),
            "train_fit_after_label_gap":len(split.train_fit),
            "validation_tune_after_label_gap":len(split.validation_tune),
            "validation_start":split.validation_start.isoformat(),"test_start":split.test_start.isoformat()},
        "training":{"prior_late":prior,"prior_late_interval":_wilson(class_counts[Outcome.LATE.value],len(split.train_fit)),
            "class_counts":class_counts,
            "missing_seller_history":sum(not item.seller_history_available for item in split.train_fit)},
        "feature_likelihoods":_categorical_likelihoods(split.train_fit,stage),
        "prior_only":prior_metrics,"logistic":logistic_metrics,"subgroups":subgroups,
        "temporal_stability":temporal_slices,
        "reward_specification":REWARD_SPECIFICATION,
        "pomdp_one_step":{"status":"NOT_EVALUABLE","reason":"No on-demand investigation action with a logged counterfactual observation exists in Olist."},
        "pomdp_horizon_two":{"status":"NOT_EVALUABLE","reason":"The archive cannot identify outcomes for unperformed action sequences."},
        "immediate_abstention":{"coverage":0.0,"selective_accuracy":None,"realized_utility":0.0,
            "average_action_count":0.0},
        "candidate_activation":"NOT_ACTIVATED",
        "limitations":["Published event timestamps do not prove when an operational system exposed each field.",
            "Seller history is restricted to deliveries completed before each decision timestamp.",
            "Model selection and threshold selection use no test outcomes."]}


def dataset_fingerprint(dataset: OlistDataset) -> dict[str, object]:
    hashes={name:dataset.content_hash(name) for name in sorted(dataset.names())
            if name.endswith(".csv")}
    return {"dataset_version":"olist-2018","archive_path":str(dataset.path),
            "archive_sha256":sha256(dataset.path.read_bytes()).hexdigest() if dataset.path.is_file() else None,
            "file_sha256":hashes}
