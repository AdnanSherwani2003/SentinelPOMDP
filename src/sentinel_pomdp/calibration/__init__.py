"""Count-based probability estimation and held-out diagnostics."""

from .estimation import CalibrationEstimate, estimate_categorical_model
from .metrics import CalibrationMetrics, PilotPrediction, evaluate_predictions, evaluate_predictions_by_subgroup
from .quality import ExtractionExample, ExtractionQuality, SourcePair, SourceIndependenceQuality, evaluate_extraction, evaluate_extraction_by_document_type, evaluate_source_independence
from .approval import build_candidate_domain_pack

__all__ = [
    "CalibrationEstimate", "CalibrationMetrics", "ExtractionExample", "ExtractionQuality",
    "PilotPrediction", "SourceIndependenceQuality", "SourcePair", "estimate_categorical_model",
    "evaluate_extraction", "evaluate_predictions", "evaluate_source_independence",
    "evaluate_predictions_by_subgroup",
    "evaluate_extraction_by_document_type",
    "build_candidate_domain_pack",
]
