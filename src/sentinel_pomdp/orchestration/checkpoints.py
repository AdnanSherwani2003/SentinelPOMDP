"""Owned lifecycle for the supported durable LangGraph checkpointer."""
from __future__ import annotations

from psycopg import Connection
from langgraph.checkpoint.postgres import PostgresSaver


class PostgresCheckpointStore:
    """A synchronous PostgresSaver whose database connection is explicitly closed."""

    def __init__(self, connection_string: str) -> None:
        if not connection_string:
            raise ValueError("PostgreSQL checkpoint connection string is required")
        self.connection = Connection.connect(
            connection_string, autocommit=True, prepare_threshold=0)
        self.saver = PostgresSaver(self.connection)
        self.saver.setup()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "PostgresCheckpointStore":
        return self

    def __exit__(self, *_args) -> None:
        self.close()
