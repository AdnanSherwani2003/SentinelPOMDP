"""Disposable PostgreSQL reliability checks; never target the application database."""
import os
from threading import Barrier, Thread
from uuid import uuid4

import pytest
import psycopg

from sentinel_pomdp.operations import (
    JobState, NewOperationJob, OperationType, PostgresOperationRepository,
)
from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.investigation import build_scenario_planner, supplier_shipment_delay_scenario
from sentinel_pomdp.orchestration import InvestigationWorkflow, PostgresCheckpointStore

pytestmark = pytest.mark.live_operations


@pytest.fixture
def database_url():
    value = os.getenv("SENTINEL_TEST_OPERATIONS_DATABASE_URL")
    if not value:
        pytest.skip("SENTINEL_TEST_OPERATIONS_DATABASE_URL is not configured")
    if "sentinel_test" not in value:
        pytest.fail("live operations tests require an explicitly disposable sentinel_test database")
    return value


@pytest.fixture(autouse=True)
def clean_disposable_operation_tables(database_url):
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("TRUNCATE operation_jobs CASCADE")
        connection.execute("TRUNCATE operation_audit, worker_heartbeats")


def request(tenant, key):
    return NewOperationJob(
        tenant_id=tenant, principal_id="test-operator",
        operation_type=OperationType.EVALUATION, correlation_id=str(uuid4()),
        payload={"run_id": key}, idempotency_key=key, replay_safe=True,
    )


def test_postgres_restart_durability_and_tenant_scope(database_url):
    tenant = f"tenant-{uuid4()}"
    first = PostgresOperationRepository(database_url)
    job, _ = first.create_job(request(tenant, "restart"))
    first.close()
    second = PostgresOperationRepository(database_url)
    assert second.get_job(tenant, job.job_id).payload == {"run_id": "restart"}
    assert second.get_job("another-tenant", job.job_id) is None
    second.close()


def test_postgres_skip_locked_claim_has_one_owner(database_url):
    tenant = f"tenant-{uuid4()}"
    setup = PostgresOperationRepository(database_url)
    job, _ = setup.create_job(request(tenant, "concurrent"))
    setup.close()
    barrier = Barrier(3)
    claims = []

    def claim(worker_id):
        repository = PostgresOperationRepository(database_url)
        barrier.wait()
        value = repository.claim(worker_id)
        claims.append(value)
        repository.close()

    threads = [Thread(target=claim, args=(f"worker-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    winners = [claim for claim in claims if claim and claim.job.job_id == job.job_id]
    assert len(winners) == 1
    assert winners[0].job.state is JobState.RUNNING


def test_postgres_langgraph_checkpoint_survives_process_resource_restart(database_url):
    graph = InMemoryGraphRepository()
    assert KnowledgeGraphIngestionPipeline(graph).ingest_dataset(
        generate_supplier_delay_dataset()).is_success
    scenario = supplier_shipment_delay_scenario()
    thread_id = f"checkpoint-{uuid4()}"
    with PostgresCheckpointStore(database_url) as first_store:
        first_workflow = InvestigationWorkflow(
            graph, scenario, build_scenario_planner(scenario),
            checkpointer=first_store.saver)
        first = first_workflow.run("tenant_alpha", thread_id=thread_id)
    with PostgresCheckpointStore(database_url) as second_store:
        second_workflow = InvestigationWorkflow(
            graph, scenario, build_scenario_planner(scenario),
            checkpointer=second_store.saver)
        restored = second_workflow.run("tenant_alpha", thread_id=thread_id)
        assert restored.final_belief == first.final_belief
        assert restored.metadata["tool_calls"] == first.metadata["tool_calls"] == 1
        with pytest.raises(ValueError, match="tenant"):
            second_workflow.run("tenant_other", thread_id=thread_id)
        graph.deactivate_document("doc_wh_log_001", "tenant_alpha")
        invalidated = second_workflow.run("tenant_alpha", thread_id=thread_id)
        assert invalidated.decision == "ABSTAIN"
        assert invalidated.final_belief == first.final_belief
        assert invalidated.total_cost == first.total_cost
        assert invalidated.metadata["tool_calls"] == 1


def test_postgres_concurrent_idempotent_submission_creates_one_job(database_url):
    tenant = f"tenant-{uuid4()}"; barrier = Barrier(3); results = []

    def submit():
        repository = PostgresOperationRepository(database_url)
        barrier.wait()
        results.append(repository.create_job(request(tenant, "same-request")))
        repository.close()

    threads = [Thread(target=submit) for _ in range(2)]
    for thread in threads: thread.start()
    barrier.wait()
    for thread in threads: thread.join()
    assert len({item[0].job_id for item in results}) == 1
    assert sorted(item[1] for item in results) == [False, True]
