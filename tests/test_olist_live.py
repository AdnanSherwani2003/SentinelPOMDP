from pathlib import Path
from uuid import uuid4
import pytest
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.repository import Neo4jGraphRepository
from sentinel_pomdp.olist import OlistDataset,OlistService
from sentinel_pomdp.security import AuthenticatedPrincipal,Permission

_manager=Neo4jConnectionManager()
_archive=Path(__file__).resolve().parents[1]/"archive (2).zip"
pytestmark=[pytest.mark.live_olist,pytest.mark.skipif(not _manager.ping() or not _archive.exists(),
    reason="live Neo4j or local Olist archive is unavailable")]

def test_live_olist_graph_provenance_and_tenant_isolation():
    tenant="olist-live-"+uuid4().hex; repo=Neo4jGraphRepository(_manager)
    service=OlistService(OlistDataset(_archive),repo)
    reviewer=AuthenticatedPrincipal(principal_id="live-reviewer",tenant_id=tenant,
        roles=frozenset({"reviewer"}),permissions=frozenset({Permission.DOCUMENT_UPLOAD}))
    preview=service.preview_orders(reviewer,limit=10)
    summary=service.import_orders(reviewer,limit=10,expected_archive_sha256=preview["archive_sha256"],review_action="APPROVE")
    assert summary.errors==0
    order=next(service.dataset.orders())
    result=service.lookup(tenant,order.order_id)
    assert result["sources"][0]["row"]==f"row:{order.source_row}"
    with pytest.raises(KeyError): service.lookup("other-tenant",order.order_id)
