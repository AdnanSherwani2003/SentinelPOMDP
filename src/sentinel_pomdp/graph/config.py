"""Neo4j configuration and environment management.

Reads database connection settings from environment variables. Credentials have no default.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Neo4jConfig:
    """Connection and authentication configuration for Neo4j database."""

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = ""
    database: str = "neo4j"
    max_connection_lifetime: float = 3600.0
    max_connection_pool_size: int = 50
    connection_timeout: float = 5.0

    @classmethod
    def from_env(cls) -> "Neo4jConfig":
        """Load configuration from environment variables or safe local defaults."""
        return cls(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", os.getenv("NEO4J_USERNAME", "neo4j")),
            password=os.getenv("NEO4J_PASSWORD", ""),
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
            max_connection_lifetime=float(os.getenv("NEO4J_MAX_CONNECTION_LIFETIME", "3600.0")),
            max_connection_pool_size=int(os.getenv("NEO4J_MAX_CONNECTION_POOL_SIZE", "50")),
            connection_timeout=float(os.getenv("NEO4J_CONNECTION_TIMEOUT", "5.0")),
        )
