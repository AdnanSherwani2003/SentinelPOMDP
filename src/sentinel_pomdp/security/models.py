"""Small framework-neutral security contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Permission(str, Enum):
    INVESTIGATION_EXECUTE = "investigation:execute"
    EVIDENCE_READ = "evidence:read"
    PROVENANCE_READ = "provenance:read"
    TRACE_READ = "trace:read"
    WORKFLOW_RESUME = "workflow:resume"
    AUDIT_READ = "audit:read"
    DOCUMENT_UPLOAD = "document:upload"
    DOCUMENT_READ = "document:read"
    EVIDENCE_REVIEW = "evidence:review"
    DOMAIN_PACK_MANAGE = "domain-pack:manage"
    CALIBRATION_RUN = "calibration:run"
    EVALUATION_READ = "evaluation:read"
    MODEL_APPROVE = "model:approve"
    JOB_SUBMIT = "job:submit"
    JOB_READ = "job:read"
    JOB_CANCEL = "job:cancel"
    OPERATIONS_READ = "operations:read"
    ADMIN = "admin"


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    principal_id: str
    tenant_id: str
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    expires_at: datetime | None = None
    disabled: bool = False

    @property
    def active(self) -> bool:
        now = datetime.now(timezone.utc)
        return not self.disabled and (self.expires_at is None or self.expires_at > now)


@dataclass
class APIKeyRecord:
    """Stored verifier. It deliberately cannot contain the original credential."""

    key_id: str
    verifier: bytes
    salt: bytes
    principal: AuthenticatedPrincipal
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        now = datetime.now(timezone.utc)
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)


@dataclass(frozen=True)
class SecurityLimits:
    max_question_chars: int = 2_000
    max_horizon: int = 2
    max_tool_calls: int = 4
    max_budget: float = 2.0
    max_requests_per_minute: int = 30


@dataclass(frozen=True)
class ProviderDataPolicy:
    """Explicit allow-list for sending the question to an external processor."""

    external_processing_enabled: bool = False
    allowed_providers: frozenset[str] = field(default_factory=frozenset)

    def allows(self, provider: str) -> bool:
        return provider == "deterministic-fake" or (
            self.external_processing_enabled and provider in self.allowed_providers
        )
