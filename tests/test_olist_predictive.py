from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sentinel_pomdp.olist import (LogisticRiskModel, OlistDataset, Outcome, PredictionStage,
    TemporalFeatureError, build_temporal_examples, evaluate_predictive_models,
    feature_registry, validate_feature_payload)
from sentinel_pomdp.olist.dataset import REQUIRED
from sentinel_pomdp.olist.predictive import _probability_metrics, fit_logistic, temporal_split


def temporal_zip(path: Path, count: int = 30) -> None:
    tables={}
    for name, required in REQUIRED.items():
        columns=list(required); rows=[]
        if name=="olist_orders_dataset.csv":
            columns=["order_id","customer_id","order_status","order_purchase_timestamp","order_approved_at",
                     "order_delivered_carrier_date","order_delivered_customer_date","order_estimated_delivery_date"]
            for index in range(count):
                purchased=datetime(2018,1,1,8)+timedelta(days=index)
                delivered=purchased+timedelta(days=4 if index%4==0 else 2)
                stamp=lambda value: value.strftime("%Y-%m-%d %H:%M:%S")
                rows.append([f"o{index}",f"c{index}","delivered",stamp(purchased),
                    stamp(purchased+timedelta(hours=2)),stamp(purchased+timedelta(days=1)),
                    stamp(delivered),stamp(purchased+timedelta(days=3,hours=-8))])
        elif name=="olist_order_items_dataset.csv":
            columns=["order_id","order_item_id","product_id","seller_id"]
            rows=[[f"o{i}","1","p0","s0"] for i in range(count)]
        elif name=="olist_customers_dataset.csv": columns=["customer_id","customer_unique_id"]; rows=[[f"c{i}",f"u{i}"] for i in range(count)]
        elif name=="olist_sellers_dataset.csv": columns=["seller_id"]; rows=[["s0"]]
        elif name=="olist_products_dataset.csv": columns=["product_id"]; rows=[["p0"]]
        elif name=="olist_order_payments_dataset.csv": columns=["order_id","payment_sequential"]; rows=[[f"o{i}","1"] for i in range(count)]
        elif name=="olist_order_reviews_dataset.csv": columns=["review_id","order_id"]; rows=[[f"r{i}",f"o{i}"] for i in range(count)]
        elif name=="olist_geolocation_dataset.csv": columns=["geolocation_zip_code_prefix"]; rows=[["1"]]
        else: columns=["product_category_name","product_category_name_english"]; rows=[["x","x"]]
        output=io.StringIO(newline=""); writer=csv.writer(output); writer.writerow(columns); writer.writerows(rows)
        tables[name]=output.getvalue()
    with zipfile.ZipFile(path,"w") as archive:
        for name,data in tables.items(): archive.writestr(name,data)


def test_feature_registry_rejects_future_and_later_stage_fields():
    purchase={item["name"] for item in feature_registry(PredictionStage.PURCHASE)}
    assert "seller_history_rate" in purchase and "handoff_elapsed_days" not in purchase
    with pytest.raises(TemporalFeatureError,match="future outcome"):
        validate_feature_payload(PredictionStage.PURCHASE,{"outcome":"shipment_delayed"})
    with pytest.raises(TemporalFeatureError,match="unavailable"):
        validate_feature_payload(PredictionStage.PURCHASE,{"handoff_elapsed_days":1.0})
    with pytest.raises(TemporalFeatureError):
        validate_feature_payload(PredictionStage.CARRIER_HANDOFF,{"review_score":5})


def test_temporal_seller_history_uses_only_already_delivered_orders(tmp_path):
    path=tmp_path/"olist.zip"; temporal_zip(path)
    examples=build_temporal_examples(OlistDataset(path),PredictionStage.PURCHASE)
    assert examples[0].values["seller_history_rate"] is None
    # At order o4 purchase, only o1 has completed; same-time and later outcomes
    # are intentionally not treated as knowable.
    order4=next(item for item in examples if item.order_id=="o4")
    assert order4.values["seller_history_count_log"]==pytest.approx(__import__("math").log1p(1))
    assert order4.values["seller_history_rate"]==0.0
    assert all("outcome" not in item.values and "final_status" not in item.values for item in examples)
    assert all(item.provenance["seller_history_rate"]["decision_time_cutoff"]==item.decision_time.isoformat()
               for item in examples)


def test_training_and_threshold_selection_do_not_use_test_labels(tmp_path):
    path=tmp_path/"olist.zip"; temporal_zip(path,30)
    split=temporal_split(build_temporal_examples(OlistDataset(path),PredictionStage.PURCHASE))
    original=fit_logistic(split,PredictionStage.PURCHASE)
    changed=replace(split,test=tuple(replace(item,label="shipment_delayed" if item.label=="shipment_on_time"
        else "shipment_on_time") for item in split.test))
    refit=fit_logistic(changed,PredictionStage.PURCHASE)
    assert original.coefficients==refit.coefficients
    assert original.intercept==refit.intercept and original.threshold==refit.threshold
    assert all(item.label_available_at < split.validation_start for item in split.train_fit)
    assert all(item.label_available_at < split.test_start for item in split.validation_tune)


def test_unapproved_predictive_model_abstains_and_approved_probability_normalizes(tmp_path):
    path=tmp_path/"olist.zip"; temporal_zip(path,30)
    split=temporal_split(build_temporal_examples(OlistDataset(path),PredictionStage.PURCHASE))
    candidate=fit_logistic(split,PredictionStage.PURCHASE)
    denied=candidate.serve(split.test[0])
    assert denied["status"]=="INSUFFICIENT_MODEL" and denied["decision"]=="ABSTAIN"
    approved=replace(candidate,status="APPROVED",approved_by="reviewer")
    result=approved.serve(split.test[0])
    assert 0 <= result["probability_late"] <= 1
    assert result["claim_type"]=="PROSPECTIVE_RISK" and result["model_version"]==approved.model_version


def test_sparse_or_single_class_training_fails_closed(tmp_path):
    path=tmp_path/"olist.zip"; temporal_zip(path,30)
    split=temporal_split(build_temporal_examples(OlistDataset(path),PredictionStage.PURCHASE))
    with pytest.raises(ValueError,match="both delivery outcomes"):
        fit_logistic(replace(split,train_fit=tuple(replace(item,label=Outcome.ON_TIME.value)
            for item in split.train_fit)),PredictionStage.PURCHASE)
    with pytest.raises(ValueError,match="insufficient temporally available"):
        fit_logistic(replace(split,train_fit=split.train_fit[:5]),PredictionStage.PURCHASE)


def test_probability_scores_and_abstention_accounting_are_exact(tmp_path):
    path=tmp_path/"olist.zip"; temporal_zip(path,12)
    rows=tuple(build_temporal_examples(OlistDataset(path),PredictionStage.PURCHASE)[:2])
    probabilities=[.8,.2]
    labels=[int(item.label==Outcome.LATE.value) for item in rows]
    metrics=_probability_metrics(rows,probabilities,.9)
    expected=sum((p-y)**2 for p,y in zip(probabilities,labels))/2
    assert metrics["brier_score"]==pytest.approx(expected)
    assert metrics["coverage"]==0 and metrics["selective_accuracy"] is None
    assert metrics["confusion_matrix_answered"]=={
        "true_positive":0,"true_negative":0,"false_positive":0,"false_negative":0}


def test_predictive_evaluation_is_reproducible_and_has_no_fabricated_actions(tmp_path):
    path=tmp_path/"olist.zip"; temporal_zip(path,30)
    first=evaluate_predictive_models(OlistDataset(path),PredictionStage.PURCHASE,seed=17)
    second=evaluate_predictive_models(OlistDataset(path),PredictionStage.PURCHASE,seed=17)
    assert first["logistic"]==second["logistic"]
    assert first["pomdp_one_step"]["status"]=="NOT_EVALUABLE"
    assert first["pomdp_horizon_two"]["status"]=="NOT_EVALUABLE"
    assert first["immediate_abstention"]["selective_accuracy"] is None
    assert first["candidate_activation"]=="NOT_ACTIVATED"
    assert first["prior_only"]["cases"]==first["logistic"]["cases"]==first["split"]["test"]


def test_actual_archive_temporal_counts_and_future_exclusion():
    path=Path(__file__).resolve().parents[1]/"archive (2).zip"
    if not path.exists(): pytest.skip("local Olist archive unavailable")
    dataset=OlistDataset(path)
    purchase=build_temporal_examples(dataset,PredictionStage.PURCHASE)
    carrier=build_temporal_examples(dataset,PredictionStage.CARRIER_HANDOFF)
    assert len(purchase)==96221 and len(carrier)==96220
    assert all(item.label_available_at>item.decision_time for item in purchase)
    assert all(not ({"outcome","order_delivered_customer_date","final_status"}&set(item.values)) for item in carrier)
