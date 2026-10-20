"""Privacy-safe, reproducible pilot calibration and held-out evaluation runner."""
from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
import tracemalloc
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from sentinel_pomdp.calibration import (
    build_candidate_domain_pack, estimate_categorical_model, evaluate_predictions,
    evaluate_predictions_by_subgroup,
)
from sentinel_pomdp.calibration.reward_sensitivity import (
    RewardAssumptions, paired_utility_difference, sensitivity_grid,
)
from sentinel_pomdp.pilot import PilotDataset, PilotSplit, chronological_group_split, validate_dataset
from sentinel_pomdp.pilot.fixtures import representative_shipment_fixture
from sentinel_pomdp.pilot.replay import ReplayPolicy, replay_logged_policy


def _labels(dataset: PilotDataset, manifest, split: PilotSplit) -> dict[str, str]:
    return {case.case_id: case.ground_truth_label for case in dataset.cases
            if manifest.assignments[case.case_id] == split and case.ground_truth_label
            and case.independent_ground_truth}


def _safe_ref(dataset: PilotDataset, value: str) -> str:
    return "ref-" + sha256(
        f"{dataset.dataset_id}\0{dataset.version}\0{value}".encode("utf-8")).hexdigest()[:16]


def _manifest_output(dataset: PilotDataset, manifest, privacy_safe: bool) -> dict:
    result = manifest.model_dump(mode="json")
    if privacy_safe:
        result["assignments"] = {
            _safe_ref(dataset, key): value for key, value in result["assignments"].items()}
        result["group_assignments"] = {
            _safe_ref(dataset, key): value for key, value in result["group_assignments"].items()}
    return result


def _select_threshold(dataset, manifest, estimate) -> tuple[float, list[dict]]:
    labels = _labels(dataset, manifest, PilotSplit.VALIDATION)
    rows = []
    for threshold in (.60, .65, .70, .75, .80, .85, .90):
        predictions = replay_logged_policy(
            dataset, manifest, estimate,
            ReplayPolicy("validation_logged", True, threshold), split=PilotSplit.VALIDATION)
        metrics = evaluate_predictions(predictions, labels)
        rows.append({"threshold": threshold, "coverage": metrics.coverage,
                     "selective_accuracy": metrics.selective_accuracy,
                     "false_answer_rate": metrics.false_answer_rate})
    eligible = [row for row in rows if row["false_answer_rate"] <= .10]
    selected = max(eligible, key=lambda row: (row["coverage"], row["selective_accuracy"], row["threshold"])) if eligible else max(rows, key=lambda row: row["threshold"])
    return selected["threshold"], rows


def _write_reliability_svg(path: Path, bins: list[dict]) -> None:
    points = " ".join(f"{40 + item['average_confidence'] * 300:.1f},{340 - item['empirical_accuracy'] * 300:.1f}" for item in bins)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="380" height="380" role="img" aria-label="Reliability diagram">
<rect width="100%" height="100%" fill="white"/><line x1="40" y1="340" x2="340" y2="40" stroke="#aaa" stroke-dasharray="4"/>
<line x1="40" y1="340" x2="340" y2="340" stroke="#222"/><line x1="40" y1="340" x2="40" y2="40" stroke="#222"/>
<polyline points="{points}" fill="none" stroke="#087f5b" stroke-width="3"/><text x="165" y="372" font-size="12">Mean confidence</text>
<text x="13" y="200" font-size="12" transform="rotate(-90 13 200)">Empirical accuracy</text></svg>'''
    path.write_text(svg, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--dataset-version")
    parser.add_argument("--model-version")
    parser.add_argument("--evaluation-split", choices=["VALIDATION", "TEST"], default="TEST")
    parser.add_argument("--policies", default="immediate_abstention,logged_fixed_order,logged_greedy_information_gain,logged_expected_utility_h1,logged_pomdp_h2")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/pilot_evaluation"))
    parser.add_argument("--seed", type=int, default=15_001)
    parser.add_argument("--privacy-safe", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--minimum-state-samples", type=int, default=5)
    args = parser.parse_args()
    started = perf_counter()
    tracemalloc.start()
    dataset = (PilotDataset.model_validate_json(args.dataset.read_text(encoding="utf-8"))
               if args.dataset else representative_shipment_fixture())
    if args.dataset_version and args.dataset_version != dataset.version:
        raise SystemExit("requested dataset version does not match the supplied dataset")
    validation = validate_dataset(dataset)
    if not validation.valid:
        raise SystemExit("dataset validation failed: " + ", ".join(validation.errors))
    manifest = chronological_group_split(dataset)
    calibration_started = perf_counter()
    estimate = estimate_categorical_model(
        dataset, manifest, minimum_state_samples=args.minimum_state_samples)
    calibration_seconds = perf_counter() - calibration_started
    if estimate.status != "EMPIRICALLY_ESTIMATED":
        raise SystemExit("calibration rejected: " + ", ".join(estimate.warnings))
    threshold, threshold_rows = _select_threshold(dataset, manifest, estimate)
    available_policies = {
        "immediate_abstention": ReplayPolicy("immediate_abstention", False, threshold),
        "logged_fixed_order": ReplayPolicy("logged_fixed_order", True, threshold),
        "logged_greedy_information_gain": ReplayPolicy("logged_greedy_information_gain", True, threshold),
        "logged_expected_utility_h1": ReplayPolicy("logged_expected_utility_h1", True, threshold),
        "logged_pomdp_h2": ReplayPolicy("logged_pomdp_h2", True, threshold),
    }
    requested = [item.strip() for item in args.policies.split(",") if item.strip()]
    unknown = set(requested) - set(available_policies)
    if unknown:
        raise SystemExit("unknown policies: " + ", ".join(sorted(unknown)))
    policies = {name: available_policies[name] for name in requested}
    evaluation_split = PilotSplit(args.evaluation_split)
    labels = _labels(dataset, manifest, evaluation_split)
    evaluation_started = perf_counter()
    predictions = {name: replay_logged_policy(
        dataset, manifest, estimate, policy, split=evaluation_split)
                   for name, policy in policies.items()}
    metrics = {name: evaluate_predictions(rows, labels) for name, rows in predictions.items()}
    supplier_categories = {
        case.case_id: case.subgroup.get("supplier_category", "unknown")
        for case in dataset.cases if manifest.assignments[case.case_id] == evaluation_split}
    subgroup_metrics = evaluate_predictions_by_subgroup(
        predictions.get("logged_pomdp_h2", next(iter(predictions.values()))), labels,
        supplier_categories, minimum_cases=10)
    evaluation_seconds = perf_counter() - evaluation_started
    model_started = perf_counter()
    candidate = build_candidate_domain_pack(
        estimate=estimate, domain_id=dataset.domain_id, name="Shipment timeliness pilot",
        claim_type="shipment_timeliness",
        model_version=args.model_version or f"calibrated-{dataset.version}",
        relation_hypotheses={"EXPERIENCED_DELAY": "delayed"},
        action_costs={action: .08 for action in estimate.observation_model},
        answer_threshold=threshold, minimum_independent_sources=1,
        holdout_metrics=metrics["logged_pomdp_h2"],
        limitations=["Synthetic representative fixture; real-world calibration is pending.",
                     "Only logged actions are replayed; counterfactual policy effects are not identifiable."])
    model_build_seconds = perf_counter() - model_started
    utilities = sensitivity_grid(predictions, labels)
    historical_assumptions = RewardAssumptions(
        correct_answer_reward=1, incorrect_answer_penalty=7, abstention_cost=.25)
    paired = (paired_utility_difference(
        predictions["logged_pomdp_h2"], predictions["immediate_abstention"], labels,
        assumptions=historical_assumptions, seed=args.seed)
        if {"logged_pomdp_h2", "immediate_abstention"} <= set(predictions) else None)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    validation_output = validation.model_dump(mode="json")
    if args.privacy_safe:
        validation_output["errors"] = sorted({item.split(":", 1)[0]
                                               for item in validation_output["errors"]})
        validation_output["warnings"] = sorted({item.split(":", 1)[0]
                                                 for item in validation_output["warnings"]})
    manifest_output = _manifest_output(dataset, manifest, args.privacy_safe)
    summary = {
        "implementation": 15, "seed": args.seed,
        "dataset": {"id": dataset.dataset_id, "version": dataset.version,
                    "classification": dataset.classification.value,
                    "authorized_use": dataset.authorized_use},
        "real_world_validation_status": "PENDING",
        "dataset_validation": validation_output,
        "document_extraction_quality": {
            "status": "NOT_MEASURED",
            "reason": "The bundled case-level fixture has no independently annotated document corpus; parser correctness is covered by regression fixtures only."},
        "source_independence_validation": {
            "status": "STRUCTURE_VERIFIED_NOT_EMPIRICALLY_VALIDATED",
            "known_source_group_coverage": (
                sum(bool(item.source_group_id) for item in dataset.observations)
                / len(dataset.observations) if dataset.observations else 0),
            "reason": "Source groups are synthetic metadata; genuine organizational dependence remains pending review."},
        "split_manifest": manifest_output,
        "calibration_estimate": estimate.model_dump(mode="json"),
        "validation_threshold_selection": {"selected": threshold, "candidates": threshold_rows},
        "test_metrics": {name: value.model_dump(mode="json") for name, value in metrics.items()},
        "subgroup_metrics": subgroup_metrics,
        "reward_sensitivity": [row.model_dump(mode="json") for row in utilities],
        "pomdp_minus_abstention_historical_assumptions": paired,
        "evaluation_split": evaluation_split.value,
        "candidate_domain_pack": candidate.model_dump(mode="json"),
        "policy_identifiability": {
            "counterfactual_outcomes_fabricated": False,
            "limitation": "The one-action fixture cannot identify differences among investigation policies; their logged replay is intentionally identical."},
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "performance": {
            "calibration_seconds": round(calibration_seconds, 6),
            "evaluation_seconds": round(evaluation_seconds, 6),
            "evaluated_policy_case_rows": sum(len(rows) for rows in predictions.values()),
            "evaluation_rows_per_second": round(
                sum(len(rows) for rows in predictions.values()) / evaluation_seconds, 3)
                if evaluation_seconds else None,
            "domain_pack_build_seconds": round(model_build_seconds, 6),
            "python_peak_traced_memory_bytes": peak_bytes,
            "scope": "bounded local synthetic run; not a production benchmark",
        },
        "runtime_seconds": round(perf_counter() - started, 6),
        "privacy_safe": args.privacy_safe,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    (output / "split_manifest.json").write_text(
        json.dumps(manifest_output, indent=2, sort_keys=True), encoding="utf-8")
    (output / "candidate_domain_pack.json").write_text(
        candidate.model_dump_json(indent=2), encoding="utf-8")
    (output / "data_quality.json").write_text(json.dumps({
        "dataset_validation": summary["dataset_validation"],
        "document_extraction_quality": summary["document_extraction_quality"],
        "source_independence_validation": summary["source_independence_validation"],
    }, indent=2, sort_keys=True), encoding="utf-8")
    with (output / "metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["policy", "scored_cases", "coverage", "selective_accuracy",
                  "false_answer_rate", "unsupported_answer_rate", "brier_score",
                  "log_loss", "ece", "average_investigation_cost"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for name, value in metrics.items():
            writer.writerow({
                "policy": name, "scored_cases": value.scored_cases,
                "coverage": value.coverage, "selective_accuracy": value.selective_accuracy,
                "false_answer_rate": value.false_answer_rate,
                "unsupported_answer_rate": value.unsupported_answer_rate,
                "brier_score": value.multiclass_brier_score, "log_loss": value.log_loss,
                "ece": value.expected_calibration_error,
                "average_investigation_cost": value.average_investigation_cost})
    comparison_lines = [
        "# Pilot policy comparison", "",
        f"Dataset classification: **{dataset.classification.value}**", "",
        "| Policy | Coverage | Selective accuracy | Brier | Mean action cost |",
        "|---|---:|---:|---:|---:|",
    ]
    comparison_lines.extend(
        f"| {name} | {value.coverage:.4f} | {value.selective_accuracy:.4f} | "
        f"{value.multiclass_brier_score:.4f} | {value.average_investigation_cost:.4f} |"
        for name, value in metrics.items())
    comparison_lines.extend([
        "", "The one-action logged fixture cannot identify differences among investigation policies. "
        "No counterfactual observations were generated."])
    (output / "policy_comparison.md").write_text(
        "\n".join(comparison_lines) + "\n", encoding="utf-8")
    with (output / "per_case.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["case_id", "policy", "decision", "predicted_label", "confidence",
                  "evidence_sufficient", "actions", "investigation_cost"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for name, rows in predictions.items():
            for row in rows:
                writer.writerow({"case_id": (_safe_ref(dataset, row.case_id)
                                              if args.privacy_safe else row.case_id), "policy": name,
                                 "decision": row.decision, "predicted_label": row.predicted_label or "",
                                 "confidence": max(row.probabilities.values()),
                                 "evidence_sufficient": row.evidence_sufficient,
                                 "actions": ";".join(row.actions_taken),
                                 "investigation_cost": row.investigation_cost})
    _write_reliability_svg(
        output / "reliability.svg",
        metrics.get("logged_pomdp_h2", next(iter(metrics.values()))).model_dump(mode="json")["reliability_bins"])
    print(json.dumps({"output_dir": str(output.resolve()),
                      "real_world_validation_status": "PENDING",
                      "dataset_classification": dataset.classification.value,
                      "selected_threshold": threshold,
                      "test_cases": len(labels),
                      "runtime_seconds": summary["runtime_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
