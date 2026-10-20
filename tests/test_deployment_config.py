from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sentinel_pomdp.api import create_app
from sentinel_pomdp.api.settings import AppSettings


def test_candidate_mode_rejects_in_memory_backend(monkeypatch):
    monkeypatch.setenv("SENTINEL_API_KEY", "x" * 32)
    monkeypatch.delenv("SENTINEL_DEVELOPMENT_AUTH", raising=False)
    settings = AppSettings.from_environment()
    settings = AppSettings(**{**settings.__dict__, "deployment_mode": "candidate"})
    assert "candidate deployment requires the neo4j backend" in settings.validate()


def test_candidate_application_fails_startup_instead_of_serving_unsafe_defaults():
    app = create_app(AppSettings(
        deployment_mode="candidate", backend="memory", api_key="x" * 32))
    with pytest.raises(RuntimeError, match="candidate startup rejected"):
        with TestClient(app):
            pass


def test_neo4j_mode_requires_explicit_connection_secrets(monkeypatch):
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    settings = AppSettings(api_key="x" * 32, backend="neo4j")
    errors = settings.validate()
    assert "NEO4J_URI is not configured" in errors
    assert "NEO4J_PASSWORD is not configured" in errors


def test_external_provider_requires_consent_and_its_own_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    settings = AppSettings(api_key="x" * 32, provider="groq")
    assert settings.validate() == [
        "external LLM provider is not permitted", "GROQ_API_KEY is not configured"]


def test_deployment_files_are_fail_closed_and_secret_free():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "infra" / "deployment.compose.yaml").read_text(encoding="utf-8")
    assert "USER sentinel" in dockerfile
    assert "--reload" not in dockerfile
    assert "127.0.0.1:${SENTINEL_PORT:-8000}:8000" in compose
    assert "NEO4J_PASSWORD:?" in compose
    assert "SENTINEL_API_KEY:?" in compose
    assert "ports:" not in compose.split("  neo4j:", 1)[1].split("  api:", 1)[0]
    assert "sk-" not in dockerfile + compose
