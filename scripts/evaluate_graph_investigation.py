"""Print the deterministic Implementation 8 policy comparison."""
from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.investigation.evaluation import evaluate_policies

repo = InMemoryGraphRepository()
KnowledgeGraphIngestionPipeline(repo).ingest_dataset(generate_supplier_delay_dataset())
for metrics in evaluate_policies(repo):
    print(metrics)
