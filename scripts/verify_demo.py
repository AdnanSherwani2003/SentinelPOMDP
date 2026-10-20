"""Exercise the isolated controlled demo over actual HTTP without logging its key."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from time import perf_counter, sleep
import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/implementation20/demo_acceptance.json"))
    args = parser.parse_args()
    config = dict(line.split("=", 1) for line in args.env_file.read_text().splitlines() if "=" in line)
    assert config["SENTINEL_TENANT_ID"].startswith("tenant_demo_")
    base = "http://127.0.0.1:" + config["SENTINEL_PORT"]
    results = {}
    with httpx.Client(base_url=base, timeout=60,
                     headers={"Authorization": "Bearer " + config["SENTINEL_API_KEY"]}) as client:
        assert httpx.get(base + "/api/v1/session").status_code == 401
        results["session"] = client.get("/api/v1/session").json()
        for name, question, expected in (
            ("shipment", "Was Supplier A's shipment late?", "ANSWER"),
            ("causation", "Did Supplier A cause the entire production delay?", "ABSTAIN"),
            ("contradiction", "Did Supplier B deliver on time?", "ABSTAIN"),
            ("missing", "Is Component A certified?", "ABSTAIN")):
            started = perf_counter()
            response = client.post("/api/v1/investigations", json={"question": question})
            response.raise_for_status()
            result = response.json()
            assert result["decision"] == expected
            results[name] = {"response": result, "http_ms": (perf_counter() - started) * 1000}
        response = client.post("/api/v1/domains/procurement_document_match/investigate",
            json={"question": "Does INV-1001 match PO-2001?", "version": "synthetic-v1"})
        response.raise_for_status()
        results["procurement"] = response.json()
        assert results["procurement"]["classification"] == "MATCH_SUPPORTED"
        denied = client.get("/api/v1/evidence/ev_beta_act50_pass")
        assert denied.status_code == 403
        results["cross_tenant_evidence_http"] = denied.status_code
        mapping = {"dataset_id": "demo_delivery", "name": "SYNTHETIC review demo",
            "field_mapping": {"purchase_order": "po", "supplier": "supplier",
                              "expected_date": "expected", "actual_date": "actual"}}
        client.post("/api/v1/company-data/datasets", json=mapping).raise_for_status()
        source = b"po,supplier,expected,actual\nPO-DEMO,SYNTHETIC,2026-01-01,2026-01-03\n"
        upload = client.post("/api/v1/company-data/uploads", data={"dataset_id": "demo_delivery"},
            files={"file": ("synthetic_delivery.csv", source, "text/csv")})
        upload.raise_for_status()
        results["source_document"] = upload.json()
        candidates = client.get("/api/v1/company-data/candidates").json()
        reviewed = []
        for candidate in candidates:
            if candidate["dataset_id"] == "demo_delivery" and candidate["status"] != "APPROVED":
                decision = client.post(f"/api/v1/company-data/candidates/{candidate['candidate_id']}/review",
                                       json={"action": "APPROVE"})
                decision.raise_for_status()
                reviewed.append(decision.json())
        results["review_decisions"] = reviewed
        submitted = client.post("/api/v1/jobs", json={"operation_type": "INVESTIGATION",
            "payload": {"scenario_id": "supplier_a_shipment_delay"},
            "idempotency_key": "i20-demo-investigation"})
        submitted.raise_for_status()
        job = submitted.json()
        for _ in range(100):
            response = client.get("/api/v1/jobs/" + job["job_id"])
            response.raise_for_status()
            job = response.json()
            if job["state"] in {"COMPLETED", "FAILED", "NEEDS_RECONCILIATION"}:
                break
            sleep(.2)
        assert job["state"] == "COMPLETED", job
        assert job["result"]["decision"] == "ANSWER"
        results["durable_job"] = job
        results["operations_health"] = client.get("/api/v1/operations/health").json()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"demo": "PASS", "checks": list(results), "credential_logged": False}))


if __name__ == "__main__":
    main()
