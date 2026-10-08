from collections import Counter
from dataclasses import dataclass, field

from sentinel_pomdp.decision import DecisionType
from sentinel_pomdp.environment import SecurityInvestigationEnv
from sentinel_pomdp.episode import EpisodeResult, run_episode
from sentinel_pomdp.states import SecurityState


@dataclass
class EvaluationRecord:
    true_state: SecurityState
    predicted_state: SecurityState | None
    terminated_by: DecisionType

    correct: bool | None

    steps: int

    final_confidence: float

    final_belief: dict[SecurityState, float]

    actions: list[str] = field(default_factory=list)


@dataclass
class StateMetrics:
    state: SecurityState

    total: int

    answered: int
    abstained: int

    correct: int
    wrong: int

    coverage: float
    selective_accuracy: float
    correct_rate: float


@dataclass
class CalibrationBin:
    lower: float
    upper: float

    count: int

    average_confidence: float
    empirical_accuracy: float


@dataclass
class EvaluationSummary:
    total_episodes: int

    answered: int
    abstained: int

    correct_answers: int
    wrong_answers: int

    coverage: float
    abstention_rate: float

    selective_accuracy: float
    wrong_answer_rate: float

    overall_correct_rate: float

    average_steps: float

    brier_score: float
    expected_calibration_error: float


def episode_to_record(
    result: EpisodeResult,
) -> EvaluationRecord:

    final_confidence = max(
        result.final_belief.values()
    )

    actions = []

    for step in result.steps:
        if step.decision.action is not None:
            actions.append(
                step.decision.action.value
            )

    return EvaluationRecord(
        true_state=result.true_state,
        predicted_state=result.predicted_state,
        terminated_by=result.terminated_by,
        correct=result.correct,
        steps=len(result.steps),
        final_confidence=final_confidence,
        final_belief=result.final_belief.copy(),
        actions=actions,
    )


def run_balanced_evaluation(
    episodes_per_state: int = 200,
    base_seed: int = 1000,
) -> list[EvaluationRecord]:

    records: list[EvaluationRecord] = []

    seed = base_seed

    for state in SecurityState:

        for _ in range(episodes_per_state):

            env = SecurityInvestigationEnv(
                true_state=state,
                seed=seed,
            )

            result = run_episode(env)

            records.append(
                episode_to_record(result)
            )

            seed += 1

    return records


def multiclass_brier_score(
    records: list[EvaluationRecord],
) -> float:

    if not records:
        raise ValueError(
            "Cannot calculate Brier score "
            "for empty records."
        )

    total_score = 0.0

    for record in records:

        episode_score = 0.0

        for state in SecurityState:

            probability = (
                record.final_belief[state]
            )

            target = (
                1.0
                if state == record.true_state
                else 0.0
            )

            episode_score += (
                probability - target
            ) ** 2

        total_score += episode_score

    return total_score / len(records)


def summarize(
    records: list[EvaluationRecord],
) -> EvaluationSummary:

    if not records:
        raise ValueError(
            "Cannot summarize empty evaluation."
        )

    total = len(records)

    answered_records = [
        record
        for record in records
        if record.terminated_by
        == DecisionType.ANSWER
    ]

    abstained_records = [
        record
        for record in records
        if record.terminated_by
        == DecisionType.ABSTAIN
    ]

    correct = sum(
        record.correct is True
        for record in records
    )

    wrong = sum(
        record.correct is False
        for record in records
    )

    answered = len(answered_records)
    abstained = len(abstained_records)

    coverage = answered / total

    abstention_rate = abstained / total

    selective_accuracy = (
        correct / answered
        if answered > 0
        else 0.0
    )

    wrong_answer_rate = wrong / total

    overall_correct_rate = correct / total

    average_steps = (
        sum(record.steps for record in records)
        / total
    )

    return EvaluationSummary(
        total_episodes=total,
        answered=answered,
        abstained=abstained,
        correct_answers=correct,
        wrong_answers=wrong,
        coverage=coverage,
        abstention_rate=abstention_rate,
        selective_accuracy=selective_accuracy,
        wrong_answer_rate=wrong_answer_rate,
        overall_correct_rate=overall_correct_rate,
        average_steps=average_steps,
        brier_score=multiclass_brier_score(
            records
        ),
        expected_calibration_error=(
            expected_calibration_error(records)
        ),
    )


def per_state_metrics(
    records: list[EvaluationRecord],
) -> list[StateMetrics]:

    results: list[StateMetrics] = []

    for state in SecurityState:

        state_records = [
            record
            for record in records
            if record.true_state == state
        ]

        total = len(state_records)

        if total == 0:
            continue

        answered = sum(
            record.terminated_by
            == DecisionType.ANSWER
            for record in state_records
        )

        abstained = sum(
            record.terminated_by
            == DecisionType.ABSTAIN
            for record in state_records
        )

        correct = sum(
            record.correct is True
            for record in state_records
        )

        wrong = sum(
            record.correct is False
            for record in state_records
        )

        coverage = answered / total

        selective_accuracy = (
            correct / answered
            if answered > 0
            else 0.0
        )

        correct_rate = correct / total

        results.append(
            StateMetrics(
                state=state,
                total=total,
                answered=answered,
                abstained=abstained,
                correct=correct,
                wrong=wrong,
                coverage=coverage,
                selective_accuracy=selective_accuracy,
                correct_rate=correct_rate,
            )
        )

    return results


def confusion_matrix(
    records: list[EvaluationRecord],
) -> dict[
    SecurityState,
    Counter[str]
]:

    matrix: dict[
        SecurityState,
        Counter[str]
    ] = {}

    for state in SecurityState:
        matrix[state] = Counter()

    for record in records:

        if record.predicted_state is None:
            prediction = "ABSTAIN"
        else:
            prediction = (
                record.predicted_state.value
            )

        matrix[
            record.true_state
        ][prediction] += 1

    return matrix


def action_usage(
    records: list[EvaluationRecord],
) -> Counter[str]:

    counter: Counter[str] = Counter()

    for record in records:
        counter.update(
            record.actions
        )

    return counter


def calibration_bins(
    records: list[EvaluationRecord],
    num_bins: int = 10,
) -> list[CalibrationBin]:

    if num_bins <= 0:
        raise ValueError(
            "num_bins must be positive."
        )

    bins: list[list[EvaluationRecord]] = [
        [] for _ in range(num_bins)
    ]

    for record in records:

        confidence = record.final_confidence

        index = min(
            int(confidence * num_bins),
            num_bins - 1,
        )

        bins[index].append(record)

    results: list[CalibrationBin] = []

    for index, bin_records in enumerate(bins):

        lower = index / num_bins
        upper = (index + 1) / num_bins

        if not bin_records:
            continue

        avg_confidence = sum(
            record.final_confidence
            for record in bin_records
        ) / len(bin_records)

        accuracy = sum(
            max(
                record.final_belief,
                key=record.final_belief.get,
            )
            == record.true_state
            for record in bin_records
        ) / len(bin_records)

        results.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=len(bin_records),
                average_confidence=avg_confidence,
                empirical_accuracy=accuracy,
            )
        )

    return results


def expected_calibration_error(
    records: list[EvaluationRecord],
    num_bins: int = 10,
) -> float:

    if not records:
        raise ValueError(
            "Cannot calculate calibration "
            "for empty records."
        )

    bins = calibration_bins(
        records,
        num_bins,
    )

    total = len(records)

    ece = 0.0

    for calibration_bin in bins:

        weight = (
            calibration_bin.count / total
        )

        gap = abs(
            calibration_bin.empirical_accuracy
            - calibration_bin.average_confidence
        )

        ece += weight * gap

    return ece
