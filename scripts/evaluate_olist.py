"""Reproducible, privacy-minimized Olist inventory and temporal evaluation."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sentinel_pomdp.olist import (OlistDataset,Snapshot,discover_olist,
                                  evaluate_olist,inventory_olist)

def write(path: Path, value) -> None:
    path.write_text(json.dumps(value,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--data-path"); p.add_argument("--import-limit",type=int,default=100)
    p.add_argument("--dataset-version",default="olist-public-2018"); p.add_argument("--seed",type=int,default=16)
    p.add_argument("--model-version",default="olist-margin-v1"); p.add_argument("--evaluation-split",default="chronological")
    p.add_argument("--decision-time",choices=["PURCHASE","CARRIER_HANDOFF"],default="CARRIER_HANDOFF")
    p.add_argument("--backend",choices=["memory"],default="memory"); p.add_argument("--output-dir",default="reports/olist")
    args=p.parse_args(); started=perf_counter(); root=Path(__file__).resolve().parents[1]
    path=Path(args.data_path).resolve() if args.data_path else discover_olist(root)
    dataset=OlistDataset(path); output=Path(args.output_dir); output.mkdir(parents=True,exist_ok=True)
    inventory=inventory_olist(dataset,args.dataset_version); write(output/"dataset_inventory.json",inventory.to_dict())
    # Evaluation is read-only. The authenticated review API handles publication.
    write(output/"import_summary.json",{"status":"NOT_REQUESTED_BY_READ_ONLY_EVALUATOR",
        "imported_orders":0,"requested_limit":args.import_limit,
        "instruction":"Use POST /api/v1/olist/import with an authenticated reviewer."})
    graph={"status":"NOT_MEASURED_BY_READ_ONLY_EVALUATOR","entities":0,"facts":0,"evidence":0,
           "relationships":0,"tenant":"tenant_olist_research"}
    write(output/"graph_integrity.json",graph)
    evaluation=evaluate_olist(dataset,snapshot=Snapshot(args.decision_time))
    evaluation.pop("rows"); evaluation.update({"dataset_version":args.dataset_version,"model_version":args.model_version,
        "seed":args.seed,"runtime_seconds":perf_counter()-started})
    write(output/"calibration_summary.json",{k:evaluation[k] for k in
        ("method","prior_late","likelihood_by_outcome","posterior_by_margin_bucket","training_counts","limitations")})
    write(output/"candidate_domain_pack.json",{"status":"NOT_ELIGIBLE_FOR_APPROVAL",
        "model_version":args.model_version,"dataset_version":args.dataset_version,
        "reason":"Schedule margin is a predictive feature, but does not supply independent evidence of a delivered outcome. No operational domain pack was created or activated.",
        "observational_likelihoods":evaluation["likelihood_by_outcome"]})
    write(output/"split_manifest.json",evaluation["split"]); write(output/"prediction_metrics.json",evaluation)
    write(output/"policy_comparison.json",{"immediate_abstention":{"coverage":0,"wrong_answer_rate":0},
        "prior_only":evaluation["prior_only_metrics"],"schedule_margin_statistical_baseline":evaluation["metrics"],
        "one_step_pomdp_with_evidence_gate":evaluation["pomdp_with_evidence_gate"],
        "multi_step":"NOT_ESTIMABLE_FROM_HISTORICAL DATA"})
    table_lines=[f"- {n}: {t.rows:,} rows; {t.duplicate_primary_keys} duplicate primary keys" for n,t in inventory.tables.items()]
    (output/"data_quality.md").write_text("# Olist data quality\n\n"+"\n".join(table_lines)+"\n",encoding="utf-8")
    (output/"final_olist_evaluation.md").write_text(
        "# Olist historical evaluation\n\n"
        f"Dataset: {path.name} ({inventory.license}). Read-only evaluation; no graph publication. "
        f"Chronological split: {evaluation['split']}. Held-out metrics: {evaluation['metrics']}.\n\n"
        "This validates source-backed historical lookup and a leakage-safe observational baseline. "
        "It does not prove causation, independent physical delivery ground truth, counterfactual action value, "
        "or production readiness. Raw order identifiers are omitted from reports.\n",encoding="utf-8")
    print(json.dumps({"dataset":str(path),"rows":{n:t.rows for n,t in inventory.tables.items()},
        "imported":0,"metrics":evaluation["metrics"],"output":str(output.resolve())},indent=2))
    return 0
if __name__=="__main__": raise SystemExit(main())
