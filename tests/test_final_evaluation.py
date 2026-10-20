import pytest

from sentinel_pomdp.evaluation import multiclass_log_loss
from sentinel_pomdp.final_evaluation import (
    bootstrap_paired_mean_difference, run_final_synthetic_benchmark,
)


def test_final_benchmark_is_reproducible_and_balanced():
    report_a, records_a = run_final_synthetic_benchmark(episodes_per_state=2, seed=77)
    report_b, records_b = run_final_synthetic_benchmark(episodes_per_state=2, seed=77)
    assert report_a["state_distribution"] == report_b["state_distribution"]
    assert report_a["total_episodes_per_policy"] == 10
    assert set(records_a) == {
        "immediate", "fixed_order", "greedy_information_gain",
        "expected_utility_h1", "pomdp_h2",
    }
    for policy in records_a:
        signature_a = [(r.true_state, r.predicted_state, r.actions, r.correct) for r in records_a[policy]]
        signature_b = [(r.true_state, r.predicted_state, r.actions, r.correct) for r in records_b[policy]]
        assert signature_a == signature_b


def test_metrics_are_finite_and_do_not_claim_graph_grounding():
    report, records = run_final_synthetic_benchmark(episodes_per_state=1, seed=9)
    for row in report["policies"]:
        assert 0 <= row["answer_rate"] <= 1
        assert 0 <= row["brier_score"] <= 2
        assert row["log_loss"] >= 0
        assert row["unsupported_answer_rate"] == 0
    assert multiclass_log_loss(records["pomdp_h2"]) >= 0


def test_bootstrap_is_paired_and_seeded():
    first = bootstrap_paired_mean_difference([2, 4, 6], [1, 2, 3], seed=10, samples=100)
    second = bootstrap_paired_mean_difference([2, 4, 6], [1, 2, 3], seed=10, samples=100)
    assert first == second
    assert first["mean_difference"] == pytest.approx(2.0)
    with pytest.raises(ValueError):
        bootstrap_paired_mean_difference([], [], seed=1)
