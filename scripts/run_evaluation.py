from sentinel_pomdp.evaluation import (
    action_usage,
    calibration_bins,
    confusion_matrix,
    per_state_metrics,
    run_balanced_evaluation,
    summarize,
)


EPISODES_PER_STATE = 200


print(
    "\nRunning balanced evaluation..."
)

records = run_balanced_evaluation(
    episodes_per_state=EPISODES_PER_STATE,
    base_seed=1000,
)

summary = summarize(records)


print("\n" + "=" * 70)
print("OVERALL PERFORMANCE")
print("=" * 70)

print(
    f"Total episodes:       "
    f"{summary.total_episodes}"
)

print(
    f"Answered:             "
    f"{summary.answered}"
)

print(
    f"Abstained:            "
    f"{summary.abstained}"
)

print(
    f"Correct answers:      "
    f"{summary.correct_answers}"
)

print(
    f"Wrong answers:        "
    f"{summary.wrong_answers}"
)

print(
    f"Coverage:             "
    f"{summary.coverage:.2%}"
)

print(
    f"Selective accuracy:   "
    f"{summary.selective_accuracy:.2%}"
)

print(
    f"Abstention rate:      "
    f"{summary.abstention_rate:.2%}"
)

print(
    f"Wrong-answer rate:    "
    f"{summary.wrong_answer_rate:.2%}"
)

print(
    f"Overall correct rate: "
    f"{summary.overall_correct_rate:.2%}"
)

print(
    f"Average steps:        "
    f"{summary.average_steps:.2f}"
)

print(
    f"Brier score:          "
    f"{summary.brier_score:.4f}"
)

print(
    f"Calibration error:    "
    f"{summary.expected_calibration_error:.4f}"
)

print("\n" + "=" * 70)
print("PER-STATE PERFORMANCE")
print("=" * 70)

for metric in per_state_metrics(records):

    print(
        f"\n{metric.state.value}"
    )

    print(
        f"  Total:               "
        f"{metric.total}"
    )

    print(
        f"  Coverage:            "
        f"{metric.coverage:.2%}"
    )

    print(
        f"  Selective accuracy:  "
        f"{metric.selective_accuracy:.2%}"
    )

    print(
        f"  Overall correct:     "
        f"{metric.correct_rate:.2%}"
    )

    print(
        f"  Abstained:           "
        f"{metric.abstained}"
    )

print("\n" + "=" * 70)
print("ACTION USAGE")
print("=" * 70)

for action, count in action_usage(
    records
).most_common():

    print(
        f"{action:25s} "
        f"{count}"
    )

print("\n" + "=" * 70)
print("CALIBRATION")
print("=" * 70)

for bin_result in calibration_bins(records):

    print(
        f"{bin_result.lower:.1f}-"
        f"{bin_result.upper:.1f} | "
        f"n={bin_result.count:4d} | "
        f"confidence="
        f"{bin_result.average_confidence:.3f} | "
        f"accuracy="
        f"{bin_result.empirical_accuracy:.3f}"
    )

matrix = confusion_matrix(records)

print("\n" + "=" * 70)
print("CONFUSION MATRIX")
print("=" * 70)

for true_state, predictions in matrix.items():

    print(
        f"\nTrue: {true_state.value}"
    )

    for prediction, count in (
        predictions.most_common()
    ):
        print(
            f"  {prediction:25s} "
            f"{count}"
        )
