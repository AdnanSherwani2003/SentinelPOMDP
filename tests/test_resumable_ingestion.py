from hashlib import sha256
import json

from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.ingestion import DatasetConfiguration, EnterpriseDataService, LocalDocumentStore
from sentinel_pomdp.operations import (
    DurableWorker, JobState, NewOperationJob, OperationType, SQLiteOperationRepository,
)
from sentinel_pomdp.operations.handlers import document_ingestion_handler


def services(tmp_path):
    graph = InMemoryGraphRepository()
    store = LocalDocumentStore(tmp_path / "documents")
    ingestion = EnterpriseDataService(store, graph)
    ingestion.configure_dataset("tenant-a", DatasetConfiguration(
        dataset_id="delivery", name="Delivery",
        field_mapping={"purchase_order": "po", "expected_date": "expected", "actual_date": "actual"}))
    operations = SQLiteOperationRepository(tmp_path / "operations.db")
    return graph, store, ingestion, operations


def enqueue(store, operations, content, *, key="upload-1"):
    staged = store.stage_upload(
        "tenant-a", filename="delivery.csv", content=content,
        declared_media_type="text/csv", dataset_id="delivery")
    job, _ = operations.create_job(NewOperationJob(
        tenant_id="tenant-a", principal_id="uploader-a",
        operation_type=OperationType.DOCUMENT_INGESTION, correlation_id="corr-a",
        payload={"upload_id": staged["upload_id"], "sha256": staged["sha256"]},
        idempotency_key=key, replay_safe=True))
    return staged, job


def test_staged_ingestion_resumes_started_idempotent_step(tmp_path):
    graph, store, ingestion, operations = services(tmp_path)
    content = b"po,expected,actual\nPO-1,2026-01-01,2026-01-03\n"
    staged, job = enqueue(store, operations, content)
    interrupted = operations.claim("crashed-worker")
    value = {"upload_id": staged["upload_id"], "sha256": staged["sha256"]}
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    operations.journal_put(
        interrupted, "document_ingestion", "STARTED",
        sha256(encoded.encode("utf-8")).hexdigest())
    operations.fail(interrupted, "PROCESS_INTERRUPTED", retryable=True, backoff_seconds=0)

    worker = DurableWorker(operations, {
        OperationType.DOCUMENT_INGESTION: document_ingestion_handler(ingestion)})
    assert worker.run_once()
    restored = operations.get_job("tenant-a", job.job_id)
    assert restored.state is JobState.COMPLETED
    assert restored.result["candidates_created"] == 1
    assert len(store.list_documents("tenant-a")) == 1
    assert len(store.list_candidates("tenant-a")) == 1
    # Ingestion never approves or publishes candidate evidence by itself.
    assert graph.find_facts("tenant-a") == []


def test_reimport_is_duplicate_and_does_not_duplicate_candidates(tmp_path):
    _graph, store, ingestion, operations = services(tmp_path)
    content = b"po,expected,actual\nPO-1,2026-01-01,2026-01-03\n"
    _staged, first = enqueue(store, operations, content, key="first")
    worker = DurableWorker(operations, {
        OperationType.DOCUMENT_INGESTION: document_ingestion_handler(ingestion)})
    worker.run_once()
    _staged, second = enqueue(store, operations, content, key="second")
    worker.run_once()
    assert operations.get_job("tenant-a", first.job_id).result["duplicate"] is False
    assert operations.get_job("tenant-a", second.job_id).result["duplicate"] is True
    assert len(store.list_documents("tenant-a")) == 1
    assert len(store.list_candidates("tenant-a")) == 1


def test_staged_upload_integrity_and_tenant_scope(tmp_path):
    _graph, store, _ingestion, _operations = services(tmp_path)
    staged = store.stage_upload(
        "tenant-a", filename="a.csv", content=b"safe",
        declared_media_type="text/csv", dataset_id="delivery")
    assert store.get_staged_upload("tenant-b", staged["upload_id"]) is None
    content_path = store._path("tenant-a", "staged", staged["upload_id"], ".bin")
    content_path.write_bytes(b"tampered")
    try:
        store.get_staged_upload("tenant-a", staged["upload_id"])
        assert False, "tampered upload must fail closed"
    except ValueError as exc:
        assert "integrity" in str(exc)
