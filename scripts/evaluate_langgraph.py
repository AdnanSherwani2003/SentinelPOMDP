"""Compare the direct session loop with LangGraph orchestration."""
from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.orchestration.evaluation import compare_orchestrators

repo = InMemoryGraphRepository()
KnowledgeGraphIngestionPipeline(repo).ingest_dataset(generate_supplier_delay_dataset())
for row in compare_orchestrators(repo):
    print(row)
