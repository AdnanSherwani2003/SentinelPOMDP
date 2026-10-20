from langgraph.checkpoint.memory import InMemorySaver

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.investigation import (
    build_scenario_planner, run_graph_investigation, supplier_shipment_delay_scenario,
)
from sentinel_pomdp.operations import (
    DurableWorker, JobState, NewOperationJob, OperationContext, OperationType,
    SQLiteOperationRepository,
)
from sentinel_pomdp.operations.handlers import investigation_handler


def test_durable_investigation_retry_preserves_math_and_does_not_repeat_evidence(tmp_path):
    graph = InMemoryGraphRepository()
    assert KnowledgeGraphIngestionPipeline(graph).ingest_dataset(
        generate_supplier_delay_dataset()).is_success
    operations = SQLiteOperationRepository(tmp_path / "operations.db")
    job, _ = operations.create_job(NewOperationJob(
        tenant_id="tenant_alpha", principal_id="analyst-a",
        operation_type=OperationType.INVESTIGATION, correlation_id="corr-a",
        payload={"scenario_id": "supplier_a_shipment_delay", "horizon": 2,
                 "max_tool_calls": 3, "budget": 1.0},
        idempotency_key="investigation-a", replay_safe=True))
    saver = InMemorySaver()
    handler = investigation_handler(graph, saver)

    # Simulate a process failure after the workflow checkpoint committed but before job completion.
    first_claim = operations.claim("worker-before-crash")
    first_result = handler(OperationContext(operations, first_claim, 30), first_claim.job.payload)
    operations.fail(first_claim, "PROCESS_CRASH_SIMULATION", retryable=True, backoff_seconds=0)

    DurableWorker(operations, {OperationType.INVESTIGATION: handler}).run_once()
    restored = operations.get_job("tenant_alpha", job.job_id)
    assert restored.state is JobState.COMPLETED
    assert restored.result == first_result
    assert len(restored.result["evidence_ids"]) == len(set(restored.result["evidence_ids"]))

    scenario = supplier_shipment_delay_scenario()
    direct = run_graph_investigation(
        graph, scenario, build_scenario_planner(scenario), "tenant_alpha")
    assert restored.result["decision"] == direct.decision
    assert restored.result["selected_hypothesis"] == direct.selected_hypothesis
    assert restored.result["final_belief"] == direct.final_belief


def test_durable_investigation_rejects_unregistered_scenario(tmp_path):
    graph = InMemoryGraphRepository(); operations = SQLiteOperationRepository(tmp_path / "operations.db")
    job, _ = operations.create_job(NewOperationJob(
        tenant_id="tenant_alpha", principal_id="analyst-a",
        operation_type=OperationType.INVESTIGATION, correlation_id="corr-a",
        payload={"scenario_id": "model_chosen_arbitrary_tool"}, replay_safe=True))
    DurableWorker(operations, {
        OperationType.INVESTIGATION: investigation_handler(graph, InMemorySaver())}).run_once()
    restored = operations.get_job("tenant_alpha", job.job_id)
    assert restored.state is JobState.FAILED
    assert restored.error_code == "UNREGISTERED_SCENARIO"
