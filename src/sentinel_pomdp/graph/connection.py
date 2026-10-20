"""Neo4j driver connection manager and session lifecycle.

Manages connection pooling, verification, session creation, and clean teardown
using the official Neo4j Python driver.
"""
from __future__ import annotations

import logging
from typing import Generator
from contextlib import contextmanager

from neo4j import (
    Driver,
    GraphDatabase,
    Session,
    exceptions as neo4j_exceptions,
)

from sentinel_pomdp.graph.config import Neo4jConfig

logger = logging.getLogger(__name__)


class Neo4jConnectionError(Exception):
    """Raised when connecting to Neo4j fails or the database is unavailable."""


class Neo4jConnectionManager:
    """Manages lifecycle of Neo4j driver and sessions."""

    def __init__(self, config: Neo4jConfig | None = None) -> None:
        self.config = config or Neo4jConfig.from_env()
        self._driver: Driver | None = None

    @property
    def driver(self) -> Driver:
        """Return cached driver or initialize a new connection pool."""
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    self.config.uri,
                    auth=(self.config.user, self.config.password),
                    max_connection_lifetime=self.config.max_connection_lifetime,
                    max_connection_pool_size=self.config.max_connection_pool_size,
                    connection_timeout=self.config.connection_timeout,
                )
            except Exception as e:
                raise Neo4jConnectionError(
                    f"Failed to initialize Neo4j driver at {self.config.uri}: {e}"
                ) from e
        return self._driver

    def verify_connectivity(self) -> bool:
        """Ping the database to verify active connection and credentials."""
        try:
            self.driver.verify_connectivity()
            return True
        except neo4j_exceptions.ServiceUnavailable:
            logger.warning("Neo4j database service is unavailable at %s", self.config.uri)
            return False
        except neo4j_exceptions.AuthError:
            logger.error("Authentication failed for Neo4j user %s", self.config.user)
            return False
        except Exception as e:
            logger.warning("Neo4j connectivity check failed: %s", e)
            return False

    def ping(self) -> bool:
        """Convenience alias for verify_connectivity."""
        return self.verify_connectivity()

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Context manager yielding a thread-safe Neo4j session with auto-close."""
        sess = self.driver.session(database=self.config.database)
        try:
            yield sess
        finally:
            sess.close()

    def close(self) -> None:
        """Close driver connection pool and release socket resources."""
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception as e:
                logger.warning("Error closing Neo4j driver: %s", e)
            finally:
                self._driver = None

    def __enter__(self) -> "Neo4jConnectionManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
