from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExtractionExample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    example_id: str
    expected_facts: set[str]
    extracted_facts: set[str]
    supported_extracted_facts: set[str]
    correct_source_locations: set[str]
    expected_source_locations: set[str]
    document_type: str


class ExtractionQuality(BaseModel):
    precision: float
    recall: float
    f1: float
    unsupported_fact_rate: float
    provenance_completeness: float
    source_location_accuracy: float
    examples: int


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_extraction(examples: list[ExtractionExample]) -> ExtractionQuality:
    if not examples:
        raise ValueError("extraction examples are required")
    expected = sum(len(item.expected_facts) for item in examples)
    extracted = sum(len(item.extracted_facts) for item in examples)
    correct = sum(len(item.expected_facts & item.extracted_facts) for item in examples)
    supported = sum(len(item.extracted_facts & item.supported_extracted_facts) for item in examples)
    locations = sum(len(item.expected_source_locations & item.correct_source_locations)
                    for item in examples)
    expected_locations = sum(len(item.expected_source_locations) for item in examples)
    precision = _ratio(correct, extracted)
    recall = _ratio(correct, expected)
    return ExtractionQuality(
        precision=precision, recall=recall,
        f1=2 * precision * recall / (precision + recall) if precision + recall else 0,
        unsupported_fact_rate=1 - _ratio(supported, extracted) if extracted else 0,
        provenance_completeness=_ratio(supported, extracted),
        source_location_accuracy=_ratio(locations, expected_locations), examples=len(examples))


def evaluate_extraction_by_document_type(
        examples: list[ExtractionExample]) -> dict[str, ExtractionQuality]:
    if not examples:
        raise ValueError("extraction examples are required")
    types = sorted({item.document_type for item in examples})
    return {document_type: evaluate_extraction(
        [item for item in examples if item.document_type == document_type])
            for document_type in types}


class SourcePair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left_id: str
    right_id: str
    genuinely_independent: bool
    predicted_independent: bool
    relationship: str


class SourceIndependenceQuality(BaseModel):
    pairs: int
    accuracy: float
    false_independence_rate: float
    false_correlation_rate: float


def evaluate_source_independence(pairs: list[SourcePair]) -> SourceIndependenceQuality:
    if not pairs:
        raise ValueError("source pairs are required")
    correct = sum(item.genuinely_independent == item.predicted_independent for item in pairs)
    actually_correlated = [item for item in pairs if not item.genuinely_independent]
    actually_independent = [item for item in pairs if item.genuinely_independent]
    return SourceIndependenceQuality(
        pairs=len(pairs), accuracy=correct / len(pairs),
        false_independence_rate=_ratio(sum(item.predicted_independent for item in actually_correlated),
                                       len(actually_correlated)),
        false_correlation_rate=_ratio(sum(not item.predicted_independent for item in actually_independent),
                                      len(actually_independent)))
