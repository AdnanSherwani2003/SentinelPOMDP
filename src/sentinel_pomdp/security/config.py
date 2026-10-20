"""Fail-closed security settings loaded without resolving credential values."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SecurityConfiguration:
    development_auth_enabled: bool = False
    external_llm_enabled: bool = False
    allowed_external_providers: frozenset[str] = frozenset()

    @classmethod
    def from_environment(cls) -> "SecurityConfiguration":
        allowed = frozenset(
            item.strip() for item in os.getenv("SENTINEL_ALLOWED_LLM_PROVIDERS", "").split(",")
            if item.strip()
        )
        return cls(
            development_auth_enabled=_truthy("SENTINEL_DEVELOPMENT_AUTH"),
            external_llm_enabled=_truthy("SENTINEL_EXTERNAL_LLM_ENABLED"),
            allowed_external_providers=allowed,
        )

    def validate_for_provider(self, provider: str) -> None:
        """Validate policy and credential presence without reading or returning its value."""
        if provider == "deterministic-fake":
            return
        if not self.external_llm_enabled or provider not in self.allowed_external_providers:
            raise ValueError("external provider is not enabled by security configuration")
        credential_environment = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
        if credential_environment is None:
            raise ValueError("external provider is not recognized")
        if not os.getenv(credential_environment):
            raise ValueError(f"required provider credential {credential_environment} is not configured")
