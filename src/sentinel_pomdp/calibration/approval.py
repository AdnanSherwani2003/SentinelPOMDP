from __future__ import annotations

from datetime import datetime, timezone

from sentinel_pomdp.domains import (
    CalibrationMetadata, CalibrationStatus, DomainAction, DomainPack,
    DomainPackStatus, ParameterSource,
)

from .estimation import CalibrationEstimate
from .metrics import CalibrationMetrics


def build_candidate_domain_pack(*, estimate: CalibrationEstimate, domain_id: str,
                                name: str, claim_type: str, model_version: str,
                                relation_hypotheses: dict[str, str], action_costs: dict[str, float],
                                answer_threshold: float,
                                minimum_independent_sources: int,
                                holdout_metrics: CalibrationMetrics | None = None,
                                limitations: list[str] | None = None) -> DomainPack:
    if estimate.status != "EMPIRICALLY_ESTIMATED":
        raise ValueError("insufficient-data estimates cannot become domain-pack candidates")
    if set(action_costs) != set(estimate.observation_model):
        raise ValueError("action costs must cover every estimated action")
    validation = {}
    status = CalibrationStatus.EMPIRICALLY_ESTIMATED
    if holdout_metrics is not None:
        validation = {
            "brier_score": holdout_metrics.multiclass_brier_score,
            "log_loss": holdout_metrics.log_loss,
            "expected_calibration_error": holdout_metrics.expected_calibration_error,
            "coverage": holdout_metrics.coverage,
            "selective_accuracy": holdout_metrics.selective_accuracy,
            "unsupported_answer_rate": holdout_metrics.unsupported_answer_rate,
        }
        status = CalibrationStatus.VALIDATED_ON_HOLDOUT
    counts = {f"class:{key}": value for key, value in estimate.class_counts.items()}
    for action, rows in estimate.action_state_counts.items():
        counts.update({f"action:{action}:state:{state}": count for state, count in rows.items()})
    return DomainPack(
        domain_id=domain_id, name=name, claim_type=claim_type,
        hypotheses=estimate.labels, prior=estimate.prior,
        actions=[DomainAction(action_id=action, relation_hypotheses=relation_hypotheses,
                              cost=action_costs[action])
                 for action in sorted(estimate.observation_model)],
        observation_model=estimate.observation_model,
        answer_threshold=answer_threshold,
        minimum_independent_sources=minimum_independent_sources,
        status=DomainPackStatus.PROVISIONAL, model_version=model_version,
        calibration_note=(
            "Estimated from training data only; approval requires independent review. "
            "Holdout metrics do not establish cross-organization validity."),
        parameter_source=ParameterSource.EMPIRICALLY_ESTIMATED,
        calibration=CalibrationMetadata(
            training_dataset_id=estimate.dataset_id,
            training_dataset_version=estimate.dataset_version,
            split_manifest_strategy="chronological_group_holdout",
            method=estimate.method, sample_counts=counts, validation_results=validation,
            status=status, estimated_at=datetime.now(timezone.utc),
            limitations=limitations or []))
