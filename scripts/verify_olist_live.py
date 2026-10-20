"""Explicitly authorized, bounded Olist batch review through the existing API auth layer."""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sentinel_pomdp.api.app import create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.olist import OlistDataset, Outcome
from sentinel_pomdp.security import Permission


def settings(path: Path, key: str, tenant: str) -> AppSettings:
    return AppSettings(backend="neo4j", provider="fake", api_key=key,
        principal_id="local-olist-reviewer", tenant_id=tenant,
        permissions=frozenset({Permission.DOCUMENT_UPLOAD, Permission.DOCUMENT_READ,
            Permission.EVIDENCE_READ, Permission.PROVENANCE_READ, Permission.INVESTIGATION_EXECUTE}),
        roles=frozenset({"reviewer"}), olist_data_path=str(path))


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--data-path",default="archive (2).zip")
    parser.add_argument("--limit",type=int,default=100)
    parser.add_argument("--output",default="reports/olist/live_acceptance.json")
    parser.add_argument("--authorize-reviewed-import",action="store_true")
    args=parser.parse_args()
    if not args.authorize_reviewed_import:
        parser.error("explicit --authorize-reviewed-import is required for Neo4j writes")
    if not 1<=args.limit<=100:
        parser.error("this acceptance run is bounded to 100 orders")
    archive=Path(args.data_path).resolve()
    dataset=OlistDataset(archive)
    chosen=list(dataset.orders(limit=args.limit))
    if len(chosen)!=args.limit:
        parser.error("archive contains fewer orders than requested")
    expected={order.order_id for order in chosen}
    key=secrets.token_urlsafe(48)
    header={"Authorization":f"Bearer {key}"}
    with TestClient(create_app(settings(archive,key,"tenant_olist_research"))) as client:
        preview_response=client.get(f"/api/v1/olist/import-preview?limit={args.limit}",headers=header)
        preview_response.raise_for_status(); preview=preview_response.json()
        if set(preview["order_ids"])!=expected:
            raise RuntimeError("preview differs from the validated source selection")
        payload={"limit":args.limit,"offset":0,"expected_archive_sha256":preview["archive_sha256"],
                 "review_action":"APPROVE"}
        response=client.post("/api/v1/olist/import",headers=header,json=payload)
        response.raise_for_status(); first=response.json()
        accounted=set(first["order_ids"])|set(first["reconciled_ids"])|set(first["duplicate_ids"])
        if first["errors"] or accounted!=expected:
            raise RuntimeError("batch review did not account for the selected order set")
        repeat=client.post("/api/v1/olist/import",headers=header,json=payload)
        repeat.raise_for_status(); second=repeat.json()
        if second["imported_orders"] or len(second["duplicate_ids"])!=args.limit:
            raise RuntimeError("repeat import was not idempotent")
        examples={}
        for label in (Outcome.LATE,Outcome.ON_TIME,Outcome.UNKNOWN):
            order=next((item for item in chosen if item.outcome is label),None)
            if order is None: continue
            lookup=client.get(f"/api/v1/olist/orders/{order.order_id}",headers=header)
            source=client.get(f"/api/v1/olist/orders/{order.order_id}/source",headers=header)
            prospective=client.post("/api/v1/olist/predictions",headers=header,
                json={"order_id":order.order_id,"decision_time":"CARRIER_HANDOFF"})
            lookup.raise_for_status(); source.raise_for_status(); prospective.raise_for_status()
            if (lookup.json()["outcome"]!=label.value or
                    source.json()["columns"]["order_id"]!=order.order_id or
                    prospective.json()["decision"]!="ABSTAIN" or
                    "delivered_at" in prospective.json()["features"]):
                raise RuntimeError(f"acceptance check failed for {label.value}")
            examples[label.value]={"order_id":order.order_id,"lookup":lookup.json(),
                                   "source":source.json(),"prospective":prospective.json()}
        selected_sellers={item.order_id:set() for item in chosen}
        for _,row in dataset.rows("olist_order_items_dataset.csv"):
            if row["order_id"] in selected_sellers:
                selected_sellers[row["order_id"]].add(row["seller_id"])
        multiseller=next((item for item in chosen if len(selected_sellers[item.order_id])>1),None)
        if multiseller:
            detail=client.get(f"/api/v1/olist/orders/{multiseller.order_id}",headers=header)
            detail.raise_for_status()
            if not detail.json()["multi_seller"] or detail.json()["causal_attribution"]:
                raise RuntimeError("multi-seller causation guard failed")
            examples["multi_seller"]={"order_id":multiseller.order_id,"seller_count":len(detail.json()["seller_ids"])}
        other_key=secrets.token_urlsafe(48)
        with TestClient(create_app(settings(archive,other_key,"tenant_olist_other"))) as other:
            denied=other.get(f"/api/v1/olist/orders/{chosen[0].order_id}",
                headers={"Authorization":f"Bearer {other_key}"})
            if denied.status_code!=404:
                raise RuntimeError("cross-tenant order lookup was not denied")
        manager=Neo4jConnectionManager()
        try:
            with manager.session() as session:
                graph={record["kind"]:record["count"] for record in session.run(
                    "MATCH (n {tenant_id: $tenant}) RETURN head(labels(n)) AS kind, count(n) AS count",
                    tenant="tenant_olist_research")}
                relationships=session.run(
                    "MATCH (a {tenant_id: $tenant})-[r]->(b {tenant_id: $tenant}) RETURN count(r) AS count",
                    tenant="tenant_olist_research").single()["count"]
        finally:
            manager.close()
    report={"status":"LIVE_NEO4J_VERIFIED","archive":str(archive),"archive_sha256":preview["archive_sha256"],
        "reviewer_id":first["reviewer_id"],"tenant_id":"tenant_olist_research",
        "imported_order_ids":first["order_ids"],"imported_orders":first["imported_orders"],
        "reconciled_order_ids":first["reconciled_ids"],
        "duplicate_order_ids_on_repeat":second["duplicate_ids"],"new_orders_on_repeat":second["imported_orders"],
        "facts_written":first["facts"],"evidence_written":first["evidence"],"errors":first["errors"],
        "elapsed_seconds":first["elapsed_seconds"],"orders_per_second":first["orders_per_second"],
        "graph_nodes":graph,"graph_relationships":relationships,"examples":examples,
        "cross_tenant_access":"DENIED","external_llm_used":False}
    target=Path(args.output); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,indent=2,default=str)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"imported_orders":first["imported_orders"],
        "duplicates_on_repeat":len(second["duplicate_ids"]),"graph_nodes":graph,
        "graph_relationships":relationships,"report":str(target.resolve())},indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
