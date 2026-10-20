"""Run the durable operations worker as a separate process."""
from __future__ import annotations

import signal
from threading import Event

from sentinel_pomdp.api.app import build_dependencies
from sentinel_pomdp.api.settings import AppSettings
from sentinel_pomdp.operations import DurableWorker, OperationType
from sentinel_pomdp.operations.handlers import (
    document_ingestion_handler, domain_investigation_handler,
    domain_validation_handler, investigation_handler, olist_batch_handler,
)
from sentinel_pomdp.orchestration import PostgresCheckpointStore


def main() -> int:
    settings = AppSettings.from_environment()
    dependencies = build_dependencies(settings)
    if dependencies.configuration_errors:
        raise RuntimeError(
            "worker startup rejected unsafe or incomplete configuration: "
            + "; ".join(dependencies.configuration_errors))
    if dependencies.operations is None or dependencies.company_data is None:
        raise RuntimeError("durable operations and company-data services are required")
    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    checkpoint_store = None
    handlers = {
        OperationType.DOCUMENT_INGESTION: document_ingestion_handler(dependencies.company_data),
        OperationType.DOMAIN_VALIDATION: domain_validation_handler(dependencies.domain_packs),
        OperationType.DOMAIN_INVESTIGATION: domain_investigation_handler(
            dependencies.domain_runtime)}
    if settings.operations_backend == "postgres" and dependencies.graph_repository is not None:
        checkpoint_store = PostgresCheckpointStore(settings.operations_database_url or "")
        handlers[OperationType.INVESTIGATION] = investigation_handler(
            dependencies.graph_repository, checkpoint_store.saver)
    if dependencies.olist is not None:
        handlers[OperationType.OLIST_BATCH] = olist_batch_handler(dependencies.olist)
    worker = DurableWorker(dependencies.operations.repository, handlers)
    try:
        worker.run(stop)
    finally:
        if checkpoint_store is not None:
            checkpoint_store.close()
        dependencies.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
