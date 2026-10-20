"""Database Seeding Service for SentinelPOMDP Knowledge Graph.

Loads synthetic datasets into a configured BaseGraphRepository.
"""
from __future__ import annotations

import logging
from typing import Optional

from sentinel_pomdp.data.synthetic.supplier_delay import (
    SupplierDelayDataset,
    generate_supplier_delay_dataset,
)
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import (
    IngestionReport,
    KnowledgeGraphIngestionPipeline,
)
from sentinel_pomdp.graph.repository import (
    BaseGraphRepository,
    InMemoryGraphRepository,
    Neo4jGraphRepository,
)

logger = logging.getLogger(__name__)


def seed_graph_database(
    repo: BaseGraphRepository,
    dataset: Optional[SupplierDelayDataset] = None,
) -> IngestionReport:
    """Seed a graph repository with synthetic enterprise evidence.

    Args:
        repo: BaseGraphRepository instance (Neo4jGraphRepository or InMemoryGraphRepository).
        dataset: Optional custom dataset; defaults to generate_supplier_delay_dataset().

    Returns:
        IngestionReport detailing upsert counts and any errors.
    """
    repo.init_schema_constraints()
    if dataset is None:
        dataset = generate_supplier_delay_dataset()

    pipeline = KnowledgeGraphIngestionPipeline(repository=repo)
    report = pipeline.ingest_dataset(dataset)
    return report


def get_default_repository(
    connection_manager: Optional[Neo4jConnectionManager] = None,
    fallback_to_in_memory: bool = True,
) -> BaseGraphRepository:
    """Acquire a graph repository, falling back to in-memory if Neo4j is offline.

    Args:
        connection_manager: Optional active connection manager.
        fallback_to_in_memory: If True, returns InMemoryGraphRepository if Neo4j is unreachable.

    Returns:
        Configured BaseGraphRepository.
    """
    if connection_manager is not None:
        if connection_manager.ping():
            return Neo4jGraphRepository(connection_manager)
        elif not fallback_to_in_memory:
            raise ConnectionError("Neo4j database service is not reachable.")

    # Try default connection manager
    cm = Neo4jConnectionManager()
    if cm.ping():
        return Neo4jGraphRepository(cm)

    if fallback_to_in_memory:
        logger.info("Neo4j service offline. Utilizing InMemoryGraphRepository for deterministic execution.")
        return InMemoryGraphRepository()

    raise ConnectionError("Neo4j database service is not reachable and fallback_to_in_memory is False.")
