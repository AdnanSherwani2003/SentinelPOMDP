"""Environment-backed, secret-safe web application configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass

from sentinel_pomdp.security import Permission


def _truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppSettings:
    deployment_mode: str = "development"
    backend: str = "memory"
    provider: str = "fake"
    api_key: str | None = None
    principal_id: str = "local-analyst"
    tenant_id: str = "tenant_alpha"
    permissions: frozenset[Permission] = frozenset({
        Permission.INVESTIGATION_EXECUTE, Permission.EVIDENCE_READ,
        Permission.PROVENANCE_READ, Permission.TRACE_READ, Permission.WORKFLOW_RESUME,
    })
    external_llm_enabled: bool = False
    allowed_external_providers: frozenset[str] = frozenset()
    planning_horizon: int = 2
    max_tool_calls: int = 3
    investigation_budget: float = 1.0
    request_timeout_seconds: float = 45.0
    rate_limit_per_minute: int = 30
    logging_mode: str = "structured"
    checkpoint_mode: str = "memory"
    roles: frozenset[str] = frozenset({"analyst"})
    document_store_path: str = "data/company_documents"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_uncompressed_bytes: int = 50 * 1024 * 1024
    max_documents_per_tenant: int = 100
    olist_data_path: str | None = None
    operations_backend: str = "sqlite"
    operations_database_path: str = "data/operations/sentinel-operations.db"
    operations_database_url: str | None = None
    api_workers: int = 1

    @classmethod
    def from_environment(cls) -> "AppSettings":
        raw_permissions = os.getenv(
            "SENTINEL_PERMISSIONS",
            "investigation:execute,evidence:read,provenance:read,trace:read,workflow:resume",
        )
        try:
            permissions = frozenset(
                Permission(item.strip()) for item in raw_permissions.split(",") if item.strip())
        except ValueError as exc:
            raise ValueError("SENTINEL_PERMISSIONS contains an unknown permission") from exc
        return cls(
            deployment_mode=os.getenv("SENTINEL_DEPLOYMENT_MODE", "development").strip().lower(),
            backend=os.getenv("SENTINEL_BACKEND", "memory").strip().lower(),
            provider=os.getenv("SENTINEL_LLM_PROVIDER", "fake").strip().lower(),
            api_key=os.getenv("SENTINEL_API_KEY") or None,
            principal_id=os.getenv("SENTINEL_PRINCIPAL_ID", "local-analyst"),
            tenant_id=os.getenv("SENTINEL_TENANT_ID", "tenant_alpha"),
            permissions=permissions,
            external_llm_enabled=_truthy("SENTINEL_EXTERNAL_LLM_ENABLED"),
            allowed_external_providers=frozenset(
                item.strip() for item in os.getenv(
                    "SENTINEL_ALLOWED_LLM_PROVIDERS", "").split(",") if item.strip()),
            planning_horizon=int(os.getenv("SENTINEL_PLANNING_HORIZON", "2")),
            max_tool_calls=int(os.getenv("SENTINEL_MAX_TOOL_CALLS", "3")),
            investigation_budget=float(os.getenv("SENTINEL_INVESTIGATION_BUDGET", "1.0")),
            request_timeout_seconds=float(os.getenv("SENTINEL_REQUEST_TIMEOUT_SECONDS", "45")),
            rate_limit_per_minute=int(os.getenv("SENTINEL_RATE_LIMIT_PER_MINUTE", "30")),
            logging_mode=os.getenv("SENTINEL_LOGGING_MODE", "structured").strip().lower(),
            checkpoint_mode=os.getenv("SENTINEL_CHECKPOINT_MODE", "memory").strip().lower(),
            roles=frozenset(item.strip() for item in os.getenv(
                "SENTINEL_ROLES", "analyst").split(",") if item.strip()),
            document_store_path=os.getenv(
                "SENTINEL_DOCUMENT_STORE", "data/company_documents"),
            max_upload_bytes=int(os.getenv("SENTINEL_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
            max_uncompressed_bytes=int(os.getenv(
                "SENTINEL_MAX_UNCOMPRESSED_BYTES", str(50 * 1024 * 1024))),
            max_documents_per_tenant=int(os.getenv(
                "SENTINEL_MAX_DOCUMENTS_PER_TENANT", "100")),
            olist_data_path=os.getenv("SENTINEL_OLIST_DATA_PATH") or None,
            operations_backend=os.getenv("SENTINEL_OPERATIONS_BACKEND", "sqlite").strip().lower(),
            operations_database_path=os.getenv(
                "SENTINEL_OPERATIONS_DATABASE", "data/operations/sentinel-operations.db"),
            operations_database_url=os.getenv("SENTINEL_OPERATIONS_DATABASE_URL") or None,
            api_workers=max(int(os.getenv("SENTINEL_API_WORKERS", "1")),
                            int(os.getenv("WEB_CONCURRENCY", "1"))),
        )

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.deployment_mode not in {"development", "integration", "candidate"}:
            errors.append("unsupported deployment mode")
        if self.backend not in {"memory", "neo4j"}:
            errors.append("unsupported backend")
        if self.provider not in {"fake", "openai", "groq"}:
            errors.append("unsupported LLM provider")
        if self.api_key is None:
            errors.append("SENTINEL_API_KEY is not configured")
        elif len(self.api_key) < 32:
            errors.append("SENTINEL_API_KEY must contain at least 32 characters")
        if self.provider != "fake":
            if not self.external_llm_enabled or self.provider not in self.allowed_external_providers:
                errors.append("external LLM provider is not permitted")
            provider_key = "GROQ_API_KEY" if self.provider == "groq" else "OPENAI_API_KEY"
            if not os.getenv(provider_key):
                errors.append(f"{provider_key} is not configured")
        if not 0 <= self.planning_horizon <= 2:
            errors.append("planning horizon must be between 0 and 2")
        if not 0 <= self.max_tool_calls <= 4:
            errors.append("tool-call limit must be between 0 and 4")
        if not 0 <= self.investigation_budget <= 2:
            errors.append("investigation budget must be between 0 and 2")
        if not 1 <= self.request_timeout_seconds <= 120:
            errors.append("request timeout must be between 1 and 120 seconds")
        if not 1 <= self.rate_limit_per_minute <= 10_000:
            errors.append("rate limit must be between 1 and 10000 requests per minute")
        if self.logging_mode not in {"structured", "quiet"}:
            errors.append("unsupported logging mode")
        if self.checkpoint_mode not in {"memory", "postgres"}:
            errors.append("unsupported checkpoint mode")
        if self.operations_backend not in {"disabled", "sqlite", "postgres"}:
            errors.append("unsupported operations backend")
        if not 1 <= self.api_workers <= 128:
            errors.append("API worker count must be between 1 and 128")
        if self.operations_backend == "postgres" and not self.operations_database_url:
            errors.append("SENTINEL_OPERATIONS_DATABASE_URL is required for postgres")
        if self.checkpoint_mode == "postgres" and not self.operations_database_url:
            errors.append("postgres checkpoints require SENTINEL_OPERATIONS_DATABASE_URL")
        if self.api_workers > 1:
            errors.append(
                "multi-process API is disabled until authentication and rate limiting use a shared store")
        if not self.roles:
            errors.append("at least one role is required")
        if not 1 <= self.max_upload_bytes <= 100 * 1024 * 1024:
            errors.append("upload byte limit must be between 1 and 104857600")
        if self.max_uncompressed_bytes < self.max_upload_bytes:
            errors.append("uncompressed byte limit must be at least the upload byte limit")
        if not 1 <= self.max_documents_per_tenant <= 100_000:
            errors.append("document limit must be between 1 and 100000")
        if self.backend == "neo4j":
            if not os.getenv("NEO4J_PASSWORD"):
                errors.append("NEO4J_PASSWORD is not configured")
            if not os.getenv("NEO4J_URI"):
                errors.append("NEO4J_URI is not configured")
        if self.deployment_mode == "candidate":
            if self.backend != "neo4j":
                errors.append("candidate deployment requires the neo4j backend")
            if _truthy("SENTINEL_DEVELOPMENT_AUTH"):
                errors.append("candidate deployment forbids development authentication")
            if self.operations_backend != "postgres":
                errors.append("candidate deployment requires the postgres operations backend")
            if self.checkpoint_mode != "postgres":
                errors.append("candidate deployment requires postgres workflow checkpoints")
        return errors
