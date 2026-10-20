from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.investigation.evaluation import evaluate_policies


def test_fixed_horizon_one_and_two_share_dataset_and_evidence_gate():
    repo = InMemoryGraphRepository()
    KnowledgeGraphIngestionPipeline(repo).ingest_dataset(generate_supplier_delay_dataset())
    metrics = evaluate_policies(repo)
    assert [m.policy for m in metrics] == ["fixed", "horizon_1", "horizon_2"]
    assert all(m.unsupported_answers == 0 for m in metrics)
    assert all(m.supported_answers == 1 for m in metrics)
    assert all(m.abstentions == 2 for m in metrics)
    assert all(m.conflicts_handled == 1 for m in metrics)
