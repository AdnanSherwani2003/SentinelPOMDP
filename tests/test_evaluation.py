import math

from sentinel_pomdp.evaluation import (
    multiclass_brier_score,
    run_balanced_evaluation,
    summarize,
)
from sentinel_pomdp.states import SecurityState


def test_balanced_evaluation_has_expected_size():
    records = run_balanced_evaluation(
        episodes_per_state=5,
        base_seed=100,
    )

    assert len(records) == (
        len(SecurityState) * 5
    )


def test_balanced_evaluation_has_equal_state_counts():
    records = run_balanced_evaluation(
        episodes_per_state=5,
        base_seed=100,
    )

    for state in SecurityState:

        count = sum(
            record.true_state == state
            for record in records
        )

        assert count == 5


def test_evaluation_summary_rates_are_valid():
    records = run_balanced_evaluation(
        episodes_per_state=5,
        base_seed=200,
    )

    summary = summarize(records)

    assert 0.0 <= summary.coverage <= 1.0

    assert (
        0.0
        <= summary.abstention_rate
        <= 1.0
    )

    assert (
        0.0
        <= summary.selective_accuracy
        <= 1.0
    )

    assert (
        0.0
        <= summary.wrong_answer_rate
        <= 1.0
    )


def test_coverage_plus_abstention_equals_one():
    records = run_balanced_evaluation(
        episodes_per_state=5,
        base_seed=300,
    )

    summary = summarize(records)

    assert math.isclose(
        summary.coverage
        + summary.abstention_rate,
        1.0,
        abs_tol=1e-9,
    )


def test_brier_score_is_non_negative():
    records = run_balanced_evaluation(
        episodes_per_state=5,
        base_seed=400,
    )

    score = multiclass_brier_score(
        records
    )

    assert score >= 0.0


def test_evaluation_is_reproducible():
    records_1 = run_balanced_evaluation(
        episodes_per_state=3,
        base_seed=999,
    )

    records_2 = run_balanced_evaluation(
        episodes_per_state=3,
        base_seed=999,
    )

    predictions_1 = [
        (
            record.true_state,
            record.predicted_state,
            record.terminated_by,
        )
        for record in records_1
    ]

    predictions_2 = [
        (
            record.true_state,
            record.predicted_state,
            record.terminated_by,
        )
        for record in records_2
    ]

    assert predictions_1 == predictions_2
