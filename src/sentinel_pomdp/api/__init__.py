"""FastAPI integration layer for the protected SentinelPOMDP service."""

from .app import create_app

__all__ = ["create_app"]
