"""Exercise the real HTTP application path entirely in memory and offline."""
from __future__ import annotations

import secrets
from time import perf_counter

from fastapi.testclient import TestClient

from sentinel_pomdp.api.app import create_app
from sentinel_pomdp.api.settings import AppSettings


def main() -> None:
    credential = secrets.token_urlsafe(32)
    app = create_app(AppSettings(api_key=credential))
    questions = [
        "Was Supplier A's shipment late?",
        "Did Supplier A cause the entire production delay?",
        "Did Supplier B deliver on time?",
        "Is Component A certified?",
    ]
    with TestClient(app) as client:
        page = client.get("/")
        print("WEB:", page.status_code, "authenticated_ui=", "Authenticate" in page.text)
        for question in questions:
            started = perf_counter()
            response = client.post(
                "/api/v1/investigations",
                headers={"Authorization": f"Bearer {credential}"},
                json={"question": question},
            )
            elapsed = (perf_counter() - started) * 1000
            body = response.json()
            print(body.get("scenario_id"), body.get("decision") or body.get("status"),
                  body.get("provenance_status"), f"http_ms={elapsed:.3f}")
        denied = client.get(
            "/api/v1/evidence/ev_beta_act50_pass",
            headers={"Authorization": f"Bearer {credential}"})
        print("CROSS_TENANT_EVIDENCE:", denied.status_code, denied.json().get("code"))
        metrics = client.get(
            "/api/v1/metrics/summary",
            headers={"Authorization": f"Bearer {credential}"}).json()
        print("METRICS:", metrics["metrics"])


if __name__ == "__main__":
    main()
