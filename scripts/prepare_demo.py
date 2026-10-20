"""Explicit synthetic fixtures for an isolated controlled demo deployment."""
from __future__ import annotations
import argparse
import json

from sentinel_pomdp.api.app import build_dependencies
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.domains import procurement_demo_pack, seed_synthetic_procurement
from sentinel_pomdp.graph.seed import seed_graph_database
from sentinel_pomdp.security import Permission


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-demo", action="store_true", required=True)
    parser.parse_args()
    settings = AppSettings.from_environment()
    if not settings.tenant_id.startswith("tenant_demo_"):
        raise SystemExit("Synthetic setup requires an isolated tenant_demo_ tenant")
    if settings.provider != "fake" or settings.external_llm_enabled:
        raise SystemExit("Synthetic setup requires offline fake-provider configuration")
    if ("reviewer" not in settings.roles or Permission.MODEL_APPROVE not in settings.permissions):
        raise SystemExit("Synthetic model setup requires the configured authorized demo reviewer")
    dependencies = build_dependencies(settings)
    try:
        if dependencies.configuration_errors:
            raise SystemExit("Demo configuration is not ready")
        graph = dependencies.graph_repository
        report = seed_graph_database(graph, generate_supplier_delay_dataset(
            primary_tenant=settings.tenant_id, secondary_tenant=settings.tenant_id + "_other"))
        if not report.is_success:
            raise SystemExit("Synthetic fixture validation failed")
        seed_synthetic_procurement(graph, settings.tenant_id)
        packs = dependencies.domain_packs
        pack = procurement_demo_pack(settings.tenant_id)
        if packs.get_version(settings.tenant_id, pack.domain_id, pack.model_version) is None:
            packs.save(settings.tenant_id, packs.validate(settings.tenant_id, pack))
            packs.submit_for_review(settings.tenant_id, pack.domain_id, pack.model_version)
            packs.approve(settings.tenant_id, pack.domain_id, pack.model_version, settings.principal_id)
            packs.activate(settings.tenant_id, pack.domain_id, pack.model_version)
        print(json.dumps({"synthetic": True, "tenant": settings.tenant_id,
            "supplier_fixtures_validated": True, "procurement_version": pack.model_version,
            "external_llm": False}))
    finally:
        dependencies.close()


if __name__ == "__main__":
    main()
