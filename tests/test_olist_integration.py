from __future__ import annotations
import csv,io,zipfile,secrets
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sentinel_pomdp.api.app import create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.olist import OlistDataset,OlistDatasetError,OlistService,Outcome,Snapshot,discover_olist,evaluate_olist
from sentinel_pomdp.olist.dataset import REQUIRED
from sentinel_pomdp.security import Permission,AuthenticatedPrincipal
from sentinel_pomdp.ingestion.models import CandidateStatus

def reviewer(tenant="tenant_olist_research"):
    return AuthenticatedPrincipal(principal_id="reviewer",tenant_id=tenant,roles=frozenset({"reviewer"}),
        permissions=frozenset({Permission.DOCUMENT_UPLOAD}))

def make_zip(path:Path,n:int=20):
    tables={}
    for name,cols in REQUIRED.items():
        columns=list(cols); rows=[]
        if name=="olist_orders_dataset.csv":
            columns=["order_id","customer_id","order_status","order_purchase_timestamp","order_approved_at","order_delivered_carrier_date","order_delivered_customer_date","order_estimated_delivery_date"]
            for i in range(n):
                day=i%20+1; late=i%3==0
                rows.append([f"o{i}",f"c{i}","delivered",f"2018-01-{day:02} 10:00:00",f"2018-01-{day:02} 11:00:00",f"2018-01-{day:02} 12:00:00",f"2018-02-{20 if late else 10:02} 10:00:00","2018-02-15 00:00:00"])
        elif name=="olist_customers_dataset.csv":
            columns=["customer_id","customer_unique_id"]; rows=[[f"c{i}",f"u{i}"] for i in range(n)]
        elif name=="olist_order_items_dataset.csv":
            columns=["order_id","order_item_id","product_id","seller_id"]; rows=[[f"o{i}","1","p0","s0"] for i in range(n)]
        elif name=="olist_sellers_dataset.csv": columns=["seller_id"]; rows=[["s0"]]
        elif name=="olist_products_dataset.csv": columns=["product_id"]; rows=[["p0"]]
        elif name=="olist_order_payments_dataset.csv": columns=["order_id","payment_sequential"]; rows=[[f"o{i}","1"] for i in range(n)]
        elif name=="olist_order_reviews_dataset.csv": columns=["review_id","order_id"]; rows=[[f"r{i}",f"o{i}"] for i in range(n)]
        elif name=="olist_geolocation_dataset.csv": columns=["geolocation_zip_code_prefix"]; rows=[["1"]]
        else: columns=["product_category_name","product_category_name_english"]; rows=[["x","x"]]
        out=io.StringIO(newline=""); w=csv.writer(out); w.writerow(columns); w.writerows(rows); tables[name]=out.getvalue()
    with zipfile.ZipFile(path,"w") as zf:
        for name,data in tables.items(): zf.writestr("nested/"+name,data)

def test_discovery_nested_and_missing(tmp_path):
    z=tmp_path/"archive.zip"; make_zip(z); assert discover_olist(tmp_path)==z.resolve()
    with pytest.raises(OlistDatasetError): discover_olist(tmp_path/"missing")

def test_outcomes_same_day_missing_and_cancelled(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); orders=list(OlistDataset(z).orders())
    assert orders[0].outcome is Outcome.LATE and orders[1].outcome is Outcome.ON_TIME
    assert "delivered_at" not in orders[0].snapshot(Snapshot.PURCHASE)
    assert "outcome" not in orders[0].snapshot(Snapshot.CARRIER_HANDOFF)
    assert "status_at_source" not in orders[0].snapshot(Snapshot.PURCHASE)
    assert "final_status" not in orders[0].snapshot(Snapshot.CARRIER_HANDOFF)

def test_import_lookup_tenant_isolation_idempotency(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); repo=InMemoryGraphRepository(); s=OlistService(OlistDataset(z),repo)
    preview=s.preview_orders(reviewer(),limit=10)
    first=s.import_orders(reviewer(),limit=10,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    second=s.import_orders(reviewer(),limit=10,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    assert first.errors==0 and second.errors==0
    assert first.imported_orders==10 and second.imported_orders==0 and len(second.duplicate_ids)==10
    assert len(repo.find_facts("tenant_olist_research",relation_type="OLIST_DELIVERY_OUTCOME"))==10
    assert s.lookup("tenant_olist_research","o0")["outcome"]=="shipment_delayed"
    source=s.source_order_row("tenant_olist_research","o0")
    assert source["source_row"]==2 and source["columns"]["order_id"]=="o0"
    assert source["file_sha256"]==s.dataset.content_hash("olist_orders_dataset.csv")
    with pytest.raises(KeyError): s.lookup("other","o0")
    with pytest.raises(KeyError): s.source_order_row("other","o0")
    candidates=s.review_service.store.list_candidates("tenant_olist_research")
    assert len(candidates)==50
    assert all(c.status is CandidateStatus.APPROVED and c.reviewed_by=="reviewer"
               and c.reviewed_at and c.graph_fact_id for c in candidates)

def test_partial_failure_reports_progress_and_resumes_without_duplicate_reviews(tmp_path,monkeypatch):
    z=tmp_path/"o.zip"; make_zip(z); repo=InMemoryGraphRepository(); s=OlistService(OlistDataset(z),repo)
    preview=s.preview_orders(reviewer(),limit=2)
    original=repo.upsert_evidence; calls=0
    def fail_first_evidence(item):
        nonlocal calls
        calls+=1
        if calls==1: raise RuntimeError("injected interruption")
        return original(item)
    monkeypatch.setattr(repo,"upsert_evidence",fail_first_evidence)
    with pytest.raises(RuntimeError,match="injected interruption"):
        s.import_orders(reviewer(),limit=2,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    interrupted=s.batch_status(reviewer(),limit=2)
    assert interrupted["read_only"] and interrupted["state_counts"]=={
        "COMMITTED":0,"PARTIAL":1,"PENDING":1,"REJECTED":0}
    first_reviews={c.candidate_id:(c.status,c.reviewed_at,c.reviewed_by)
                   for c in s.review_service.store.list_candidates("tenant_olist_research")}
    monkeypatch.setattr(repo,"upsert_evidence",original)
    recovered=s.import_orders(reviewer(),limit=2,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    assert recovered.reconciled_ids==("o0",) and recovered.order_ids==("o1",)
    assert s.batch_status(reviewer(),limit=2)["state_counts"]["COMMITTED"]==2
    final_reviews={c.candidate_id:(c.status,c.reviewed_at,c.reviewed_by)
                   for c in s.review_service.store.list_candidates("tenant_olist_research")}
    for candidate_id,(status,reviewed_at,reviewed_by) in first_reviews.items():
        if status is CandidateStatus.APPROVED:
            assert final_reviews[candidate_id]==(status,reviewed_at,reviewed_by)
    repeat=s.import_orders(reviewer(),limit=2,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    assert repeat.duplicate_ids==("o0","o1")

def test_batch_status_is_tenant_scoped_and_does_not_create_candidates(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); repo=InMemoryGraphRepository(); s=OlistService(OlistDataset(z),repo)
    status=s.batch_status(reviewer("isolated"),limit=3)
    assert status["state_counts"]["PENDING"]==3
    assert s.review_service.store.list_candidates("isolated")==[]
    assert repo.list_entities("isolated")==[]

def test_rejected_batch_cannot_publish_or_be_reapproved(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); repo=InMemoryGraphRepository(); s=OlistService(OlistDataset(z),repo)
    preview=s.preview_orders(reviewer(),limit=1)
    rejected=s.import_orders(reviewer(),limit=1,expected_archive_sha256=preview["archive_sha256"],
        review_action="REJECT")
    assert rejected.rejected_ids==("o0",)
    assert not repo.find_facts("tenant_olist_research",relation_type="OLIST_DELIVERY_OUTCOME")
    assert all(c.status is CandidateStatus.REJECTED for c in
        s.review_service.store.list_candidates("tenant_olist_research"))
    with pytest.raises(ValueError,match="rejected candidate"):
        s.import_orders(reviewer(),limit=1,expected_archive_sha256=preview["archive_sha256"],
            review_action="APPROVE")

def test_legacy_graph_reconciliation_preserves_counts_and_creates_current_review(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); repo=InMemoryGraphRepository()
    first=OlistService(OlistDataset(z),repo)
    preview=first.preview_orders(reviewer(),limit=1)
    first.import_orders(reviewer(),limit=1,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    fact_count=len(repo.find_facts("tenant_olist_research"))
    fresh=OlistService(OlistDataset(z),repo)
    from dataclasses import replace
    second_reviewer=replace(reviewer(),principal_id="second-reviewer")
    result=fresh.import_orders(second_reviewer,limit=1,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    assert result.reconciled_ids==("o0",) and result.imported_orders==0
    assert len(repo.find_facts("tenant_olist_research"))==fact_count
    assert all(c.reviewed_at and c.reviewed_by=="second-reviewer" for c in
        fresh.review_service.store.list_candidates("tenant_olist_research"))
    assert repo.find_facts("tenant_olist_research",relation_type="OLIST_DELIVERY_OUTCOME")[0].attributes["reviewed_by"]=="reviewer"
    repeat=fresh.import_orders(reviewer(),limit=1,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    assert repeat.duplicate_ids==("o0",) and not repeat.reconciled_ids

def test_reconciliation_stops_on_changed_published_fact(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); repo=InMemoryGraphRepository()
    first=OlistService(OlistDataset(z),repo); preview=first.preview_orders(reviewer(),limit=1)
    first.import_orders(reviewer(),limit=1,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    fact=repo.find_facts("tenant_olist_research",subject_id="o0",relation_type="OLIST_DELIVERY_OUTCOME")[0]
    repo.upsert_relation_fact(fact.model_copy(update={"attributes":{**fact.attributes,"outcome":"unknown"}}))
    fresh=OlistService(OlistDataset(z),repo)
    with pytest.raises(ValueError,match="differs"):
        fresh.import_orders(reviewer(),limit=1,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    assert repo.get_relation_fact(fact.fact_id,"tenant_olist_research").attributes["outcome"]=="unknown"
    assert fresh.review_service.store.list_candidates("tenant_olist_research")==[]

def test_invalid_extracted_identifier_rejected_before_graph_write(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); repo=InMemoryGraphRepository(); s=OlistService(OlistDataset(z),repo)
    order=next(s.dataset.orders())
    from dataclasses import replace
    with pytest.raises(ValueError,match="identifier is missing"):
        s._fact_specs("tenant_olist_research","reviewer",replace(order,customer_id=""),[],"doc1","doc2")
    assert repo.list_entities("tenant_olist_research")==[]

def test_prospective_leakage_and_evaluation(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z,30); repo=InMemoryGraphRepository(); s=OlistService(OlistDataset(z),repo)
    preview=s.preview_orders(reviewer("t"),limit=1)
    s.import_orders(reviewer("t"),limit=1,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    snap=s.prospective_snapshot("t","o0",Snapshot.CARRIER_HANDOFF)
    assert snap["outcome_hidden"] and "delivered_at" not in snap["features"]
    assert snap["decision"]=="ABSTAIN" and "status_at_source" not in snap["features"]
    with pytest.raises(ValueError): s.prospective_snapshot("t","o0",Snapshot.DELIVERY_COMPLETED)
    result=evaluate_olist(OlistDataset(z)); assert result["outcome_hidden_during_prediction"]
    assert result["split"]["train"]==18 and result["split"]["validation"]==6 and result["split"]["test"]==6

def test_withdrawn_source_cannot_be_used_or_silently_reapproved(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); repo=InMemoryGraphRepository(); s=OlistService(OlistDataset(z),repo)
    preview=s.preview_orders(reviewer(),limit=1)
    s.import_orders(reviewer(),limit=1,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    source=s.lookup("tenant_olist_research","o0")["sources"][0]
    assert repo.deactivate_document(source["document_id"],"tenant_olist_research")
    with pytest.raises(KeyError): s.lookup("tenant_olist_research","o0")
    with pytest.raises(ValueError): s.import_orders(reviewer(),limit=1,
        expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")

def test_requires_reviewer_and_bounded_limit(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); s=OlistService(OlistDataset(z),InMemoryGraphRepository())
    with pytest.raises(ValueError): s.import_orders("t",limit=1,expected_archive_sha256="0"*64,review_action="APPROVE")
    with pytest.raises(ValueError): s.preview_orders(reviewer("t"),limit=10001)
    with pytest.raises(ValueError): s.import_orders(reviewer("t"),limit=1,expected_archive_sha256="0"*64,review_action="APPROVE")
    analyst=AuthenticatedPrincipal(principal_id="analyst",tenant_id="t",roles=frozenset({"analyst"}),
        permissions=frozenset({Permission.DOCUMENT_UPLOAD}))
    with pytest.raises(ValueError,match="authorized reviewer"):
        s.preview_orders(analyst,limit=1)

def test_olist_api_review_auth_and_tenant_scope(tmp_path):
    z=tmp_path/"o.zip"; make_zip(z); key=secrets.token_urlsafe(32)
    permissions=frozenset({Permission.DOCUMENT_UPLOAD,Permission.DOCUMENT_READ,
        Permission.EVIDENCE_READ,Permission.PROVENANCE_READ,Permission.INVESTIGATION_EXECUTE})
    settings=AppSettings(api_key=key,tenant_id="tenant_olist_research",principal_id="reviewer-1",
        permissions=permissions,roles=frozenset({"reviewer"}),olist_data_path=str(z),
        document_store_path=str(tmp_path/"reviews"))
    with TestClient(create_app(settings)) as client:
        h={"Authorization":f"Bearer {key}"}
        preview=client.get("/api/v1/olist/import-preview?limit=10",headers=h).json()
        assert client.post("/api/v1/olist/import",headers=h,json={"limit":10,
            "expected_archive_sha256":preview["archive_sha256"],"review_action":"APPROVE"}).status_code==200
        batch=client.get("/api/v1/olist/import-status?limit=10",headers=h)
        assert batch.status_code==200 and batch.json()["state_counts"]["COMMITTED"]==10
        factual=client.get("/api/v1/olist/orders/o0",headers=h)
        assert factual.status_code==200 and factual.json()["causal_attribution"] is False
        source=client.get("/api/v1/olist/orders/o0/source",headers=h)
        assert source.status_code==200 and source.json()["columns"]["order_id"]=="o0"
        prospective=client.post("/api/v1/olist/predictions",headers=h,json={"order_id":"o0","decision_time":"PURCHASE"})
        assert prospective.status_code==200 and "delivered_at" not in prospective.json()["features"]
        assert prospective.json()["decision"]=="ABSTAIN"
        approval=client.post("/api/v1/olist/predictions",headers=h,json={"order_id":"o0","decision_time":"APPROVAL"})
        assert approval.status_code==200 and approval.json()["claim_type"]=="PROSPECTIVE_RISK"

def test_actual_archive_schema_and_temporal_examples():
    path=Path(__file__).resolve().parents[1]/"archive (2).zip"
    if not path.exists(): pytest.skip("local Olist archive unavailable")
    dataset=OlistDataset(path)
    sample=list(dataset.orders(limit=100))
    assert any(order.outcome is Outcome.LATE for order in sample)
    assert any(order.outcome is Outcome.ON_TIME for order in sample)
    assert all("delivered_at" not in order.snapshot(Snapshot.CARRIER_HANDOFF) for order in sample)
    assert all("final_status" not in order.snapshot(Snapshot.PURCHASE) for order in sample)
    assert dataset.eligibility_breakdown()=={
        "eligible":96221,"missing_or_invalid_customer_delivery_date":2965,
        "invalid_date_ordering":249,"non_delivered_final_status":6}
