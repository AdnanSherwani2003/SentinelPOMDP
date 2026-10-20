"""Reproduce Implementation 17 offline evaluation without persistent graph writes."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
import tracemalloc
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.ingestion import EnterpriseDataService, LocalDocumentStore
from sentinel_pomdp.olist import (OlistDataset, OlistService, PredictionStage,
    build_temporal_examples, evaluate_olist, evaluate_predictive_models, feature_registry)
from sentinel_pomdp.olist.dataset import inventory_olist
from sentinel_pomdp.olist.predictive import dataset_fingerprint
from sentinel_pomdp.security import AuthenticatedPrincipal, Permission


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def scale_once(dataset: OlistDataset, limit: int) -> dict[str, object]:
    repository = InMemoryGraphRepository()
    with tempfile.TemporaryDirectory(prefix="sentinel-i17-scale-") as directory:
        review = EnterpriseDataService(LocalDocumentStore(directory), repository)
        service = OlistService(dataset, repository, review_service=review)
        reviewer = AuthenticatedPrincipal(principal_id="implementation17-disposable-reviewer",
            tenant_id=f"disposable_olist_scale_{limit}",roles=frozenset({"reviewer"}),
            permissions=frozenset({Permission.DOCUMENT_UPLOAD}))
        preview = service.preview_orders(reviewer, limit=limit)
        tracemalloc.start(); started = time.perf_counter()
        first = service.import_orders(reviewer, limit=limit,
            expected_archive_sha256=preview["archive_sha256"], review_action="APPROVE")
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory(); tracemalloc.stop()
        repeat = service.import_orders(reviewer, limit=limit,
            expected_archive_sha256=preview["archive_sha256"], review_action="APPROVE")
        candidates = review.store.list_candidates(reviewer.tenant_id)
        latencies=[]
        for order_id in preview["order_ids"][:min(100,len(preview["order_ids"]))]:
            query_started=time.perf_counter(); service.lookup(reviewer.tenant_id,order_id)
            latencies.append((time.perf_counter()-query_started)*1000)
        ordered_latency=sorted(latencies)
        return {"environment":"DISPOSABLE_IN_MEMORY","orders_requested":limit,
            "orders_imported":first.imported_orders,"duplicates_first":len(first.duplicate_ids),
            "duplicates_repeat":len(repeat.duplicate_ids),"rejected":len(first.rejected_ids),
            "candidate_facts":len(candidates),"approved_candidates":sum(c.status.value=="APPROVED" for c in candidates),
            "entities_write_attempts":first.entities,"facts_write_attempts":first.facts,
            "evidence_write_attempts":first.evidence,"elapsed_seconds":elapsed,
            "orders_per_second":limit/elapsed,"peak_python_bytes":peak,
            "resulting_graph_entities":len(repository.list_entities(reviewer.tenant_id)),
            "resulting_fact_edges":len(repository.find_facts(reviewer.tenant_id)),
            "resulting_evidence_records":sum(key[0]==reviewer.tenant_id for key in repository.evidence),
            "resulting_evidence_fact_links":sum(len(value) for key,value in repository.fact_evidence_links.items()
                if key[0]==reviewer.tenant_id),
            "average_lookup_ms":sum(latencies)/len(latencies),
            "p95_lookup_ms":ordered_latency[max(0,int(.95*len(ordered_latency))-1)],
            "database_storage_growth":"NOT_MEASURABLE_IN_DISPOSABLE_MEMORY",
            "persistent_research_tenant_modified":False,"review_store_path":"temporary-and-removed"}


def reliability_svg(result: dict[str, object]) -> str:
    bins = result["logistic"]["reliability_bins"]
    points = " ".join(f"{50+float(row['average_probability_late'])*500:.1f},{330-float(row['empirical_late_rate'])*280:.1f}" for row in bins)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="620" height="380" viewBox="0 0 620 380">
<rect width="620" height="380" fill="white"/><line x1="50" y1="330" x2="550" y2="50" stroke="#aaa" stroke-dasharray="5 5"/>
<line x1="50" y1="330" x2="550" y2="330" stroke="#222"/><line x1="50" y1="330" x2="50" y2="50" stroke="#222"/>
<polyline points="{points}" fill="none" stroke="#087f5b" stroke-width="3"/><g fill="#087f5b">{''.join(f'<circle cx="{50+float(row["average_probability_late"])*500:.1f}" cy="{330-float(row["empirical_late_rate"])*280:.1f}" r="4"/>' for row in bins)}</g>
<text x="225" y="370" font-family="sans-serif" font-size="14">Predicted probability of delay</text>
<text x="16" y="215" transform="rotate(-90 16 215)" font-family="sans-serif" font-size="14">Observed delay frequency</text>
<text x="50" y="28" font-family="sans-serif" font-size="18">Olist purchase-time reliability</text></svg>'''


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-path",default="archive (2).zip")
    parser.add_argument("--output",default="reports/olist/implementation17")
    parser.add_argument("--skip-scale",action="store_true")
    args=parser.parse_args(); output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    dataset=OlistDataset(args.data_path)
    inventory=inventory_olist(dataset,"olist-2018")
    fingerprint=dataset_fingerprint(dataset)
    eligibility=dataset.eligibility_breakdown()
    write_json(output/"temporal_feature_audit.json",{
        "dataset":fingerprint,"eligibility":eligibility,
        "purchase_features":feature_registry(PredictionStage.PURCHASE),
        "approval_features":feature_registry(PredictionStage.APPROVAL),
        "carrier_features":feature_registry(PredictionStage.CARRIER_HANDOFF),
        "prohibited_pre_outcome":["actual customer delivery","final status","outcome","post-delivery review","future seller outcomes"],
        "availability_limitation":"The archive contains event timestamps, not operational access-log timestamps."})
    stage_results={}
    stage_runtimes={}
    for stage in PredictionStage:
        started=time.perf_counter()
        stage_results[stage.value]=evaluate_predictive_models(dataset,stage)
        stage_runtimes[stage.value]=time.perf_counter()-started
    purchase=stage_results[PredictionStage.PURCHASE.value]
    approval=stage_results[PredictionStage.APPROVAL.value]
    carrier=stage_results[PredictionStage.CARRIER_HANDOFF.value]
    legacy=evaluate_olist(dataset)
    write_json(output/"evaluation_split_manifest.json",{
        "dataset":fingerprint,"eligibility":eligibility,"purchase":purchase["split"],
        "approval":approval["split"],"carrier_handoff":carrier["split"],
        "strategy":"chronological 60/20/20; fitting labels must be knowable before next-period start",
        "seed":purchase["seed"],"generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "software":{"python":platform.python_version(),"sentinel_pomdp":version("sentinel-pomdp")}})
    write_json(output/"model_candidates.json",{
        "purchase":purchase["model"],"approval":approval["model"],"carrier_handoff":carrier["model"],
        "empirical_training":{stage:{"prior":result["training"],
            "feature_likelihoods":result["feature_likelihoods"]}
            for stage,result in stage_results.items()},
        "activation":"NOT_ACTIVATED","approval_required":True})
    write_json(output/"calibration_metrics.json",{
        "purchase_logistic":purchase["logistic"],"approval_logistic":approval["logistic"],
        "carrier_logistic":carrier["logistic"],
        "subgroups":{stage:result["subgroups"] for stage,result in stage_results.items()},
        "temporal_stability":{stage:result["temporal_stability"] for stage,result in stage_results.items()},
        "evaluation_runtime_seconds":stage_runtimes})
    comparison={"prior_only_purchase":purchase["prior_only"],
        "schedule_margin_implementation16":{"snapshot":legacy["snapshot"],"metrics":legacy["metrics"],
            "prior_only_metrics":legacy["prior_only_metrics"],"selected_threshold":legacy["selected_threshold"]},
        "logistic_purchase":purchase["logistic"],"logistic_approval":approval["logistic"],
        "logistic_carrier_handoff":carrier["logistic"],
        "immediate_abstention":purchase["immediate_abstention"]}
    write_json(output/"baseline_comparison.json",comparison)
    write_json(output/"pomdp_policy_results.json",{
        "one_step":purchase["pomdp_one_step"],"horizon_two":purchase["pomdp_horizon_two"],
        "immediate_abstention":purchase["immediate_abstention"],
        "conclusion":"No POMDP planning value is identifiable from unperformed investigations in this archive."})
    scale_path=output/"import_scaling.json"
    if args.skip_scale and scale_path.exists():
        scaling=json.loads(scale_path.read_text(encoding="utf-8")).get("stages",[])
    else:
        scaling=[] if args.skip_scale else [scale_once(dataset,100),scale_once(dataset,1000)]
    write_json(output/"import_scaling.json",{"stages":scaling,
        "persistent_import_authorization":"NOT_GRANTED","persistent_orders_added":0,
        "limitations":["Disposable in-memory single-machine measurements do not establish production scalability."]})
    (output/"reliability.svg").write_text(reliability_svg(purchase),encoding="utf-8")
    summary=f"""# Implementation 17 predictive evaluation

Dataset: Olist 2018; archive SHA-256 `{fingerprint['archive_sha256']}`. Eligible orders: {eligibility.get('eligible')} of {sum(eligibility.values())}.

## Result

The purchase-time logistic candidate achieved Brier {purchase['logistic']['brier_score']:.6f} and log loss {purchase['logistic']['log_loss']:.6f}, versus prior-only Brier {purchase['prior_only']['brier_score']:.6f} and log loss {purchase['prior_only']['log_loss']:.6f}. The candidate is **not activated**. These are held-out predictive measurements, not historical facts.

The preserved Implementation 16 schedule-margin result has Brier {legacy['metrics']['brier_score']:.6f} and log loss {legacy['metrics']['log_loss']:.6f}; its prior-only comparator has Brier {legacy['prior_only_metrics']['brier_score']:.6f} and log loss {legacy['prior_only_metrics']['log_loss']:.6f}.

## POMDP value

One-step and horizon-2 policy value are **NOT EVALUABLE**: Olist does not log outcomes for investigations that were not performed. Free attributes are features, not autonomous actions. Immediate abstention has zero coverage, N/A selective accuracy, zero cost, and zero realized utility under the fixed reward specification.

## Temporal safeguards

Seller history contains only eligible deliveries completed before each decision timestamp. Training fitting and validation tuning exclude labels not knowable by the following split boundary. Actual delivery, final status, outcome, post-delivery reviews, and future seller performance are prohibited before outcome revelation.

## Limitations

The public archive lacks operational access timestamps, so availability is reconstructed conservatively from event times. No additional persistent Neo4j orders were imported. Disposable scale measurements are local engineering measurements only.
"""
    (output/"evaluation_summary.md").write_text(summary,encoding="utf-8")
    print(json.dumps({"status":"COMPLETE","output":str(output.resolve()),
        "purchase_brier":purchase["logistic"]["brier_score"],
        "prior_brier":purchase["prior_only"]["brier_score"],
        "model_activated":False,"persistent_orders_added":0},indent=2))
    return 0


if __name__=="__main__": raise SystemExit(main())
