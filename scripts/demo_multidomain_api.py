"""Disposable local browser demo for Implementation 19; never use as deployment entrypoint."""
from __future__ import annotations

import os

from sentinel_pomdp.api.app import build_dependencies, create_app
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.domains import (
    olist_logistics_pack, procurement_demo_pack, seed_synthetic_procurement,
)
from sentinel_pomdp.security import AuthenticatedPrincipal, Permission


def create_demo_app():
    settings = AppSettings.from_environment()
    if settings.backend != "memory":
        raise ValueError("The synthetic browser demo requires a disposable in-memory graph")
    dependencies = build_dependencies(settings)
    packs = dependencies.domain_packs
    assert packs is not None and dependencies.graph_repository is not None
    draft = procurement_demo_pack(settings.tenant_id)
    if packs.get_version(settings.tenant_id, draft.domain_id, draft.model_version) is None:
        packs.save(settings.tenant_id, packs.validate(settings.tenant_id, draft))
        packs.submit_for_review(settings.tenant_id, draft.domain_id, draft.model_version)
        packs.approve(settings.tenant_id, draft.domain_id, draft.model_version,
                      settings.principal_id)
        packs.activate(settings.tenant_id, draft.domain_id, draft.model_version)
    seed_synthetic_procurement(dependencies.graph_repository, settings.tenant_id)
    if os.getenv("SENTINEL_DEMO_SEED_OLIST") == "1" and dependencies.olist is not None:
        reviewer = AuthenticatedPrincipal(settings.principal_id, settings.tenant_id,
            roles=frozenset({"reviewer"}), permissions=frozenset({
                Permission.DOCUMENT_UPLOAD, Permission.EVIDENCE_REVIEW}))
        if not dependencies.graph_repository.list_entities(settings.tenant_id, "olist_order"):
            preview = dependencies.olist.preview_orders(reviewer, limit=100)
            dependencies.olist.import_orders(reviewer, limit=100,
                expected_archive_sha256=preview["archive_sha256"], review_action="APPROVE")
        olist_pack = olist_logistics_pack(settings.tenant_id)
        if packs.get_version(settings.tenant_id, olist_pack.domain_id,
                             olist_pack.model_version) is None:
            packs.save(settings.tenant_id, packs.validate(settings.tenant_id, olist_pack))
            packs.submit_for_review(settings.tenant_id, olist_pack.domain_id,
                                    olist_pack.model_version)
            packs.approve(settings.tenant_id, olist_pack.domain_id,
                          olist_pack.model_version, settings.principal_id)
            packs.activate(settings.tenant_id, olist_pack.domain_id,
                           olist_pack.model_version)
    return create_app(settings, dependencies)


app = create_demo_app()
