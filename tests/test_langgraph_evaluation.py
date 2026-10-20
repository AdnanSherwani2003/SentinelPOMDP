from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.orchestration.evaluation import compare_orchestrators


def test_direct_and_langgraph_are_equivalent_for_both_horizons():
    repo = InMemoryGraphRepository()
    KnowledgeGraphIngestionPipeline(repo).ingest_dataset(generate_supplier_delay_dataset())
    rows = compare_orchestrators(repo)
    assert len(rows) == 8
    assert all(row.equivalent for row in rows)
    assert {row.horizon for row in rows} == {1, 2}
