"""Shared, version-pinned execution for factual and probabilistic domain packs."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .models import DomainPack, DomainPackStatus, InvestigationMode
from .service import DomainPackService


class FactualInvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain_id: str
    domain_version: str
    mode: str = "HISTORICAL_FACTUAL"
    decision: str
    classification: str
    subject_id: str
    findings: list[dict] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    source_groups: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    provenance_verified: bool = False
    limitation: str | None = None


class DomainAdapter(Protocol):
    domain_id: str
    registered_tools: frozenset[str]

    def investigate(self, tenant_id: str, pack: DomainPack,
                    question: str) -> FactualInvestigationResult | dict: ...


@dataclass(frozen=True)
class DomainRegistration:
    adapter: DomainAdapter


class DomainInvestigationService:
    """One selection and governance boundary for all declarative domains."""

    def __init__(self, packs: DomainPackService, adapters: list[DomainAdapter] | None = None) -> None:
        self.packs = packs
        self._adapters = {adapter.domain_id: adapter for adapter in adapters or []}

    def register(self, adapter: DomainAdapter) -> None:
        if adapter.domain_id in self._adapters:
            raise ValueError("domain adapter is already registered")
        self._adapters[adapter.domain_id] = adapter

    def investigate(self, tenant_id: str, domain_id: str, question: str,
                    *, version: str | None = None):
        pack = (self.packs.get_version(tenant_id, domain_id, version)
                if version else self.packs.get(tenant_id, domain_id))
        if pack is None:
            raise KeyError("domain pack is unavailable in tenant scope")
        if pack.status not in {DomainPackStatus.ACTIVE, DomainPackStatus.APPROVED}:
            raise ValueError("domain pack is not active")
        if version is not None and pack.model_version != version:
            raise ValueError("investigation version pin could not be satisfied")
        if pack.investigation_mode == InvestigationMode.PROBABILISTIC:
            return self.packs.build_scenario(
                tenant_id, domain_id, question, model_version=pack.model_version)
        adapter = self._adapters.get(domain_id)
        if adapter is None:
            raise ValueError("no registered factual adapter exists for this domain")
        configured = set(pack.registered_tools)
        # Each bounded adapter uses this declared evidence bundle. A pack cannot
        # silently omit a required tool while the adapter still invokes it.
        if configured != adapter.registered_tools:
            raise ValueError("domain pack requests an unavailable or unregistered tool")
        from sentinel_pomdp.orchestration.workflow import run_factual_investigation

        return run_factual_investigation(lambda: adapter.investigate(tenant_id, pack, question))


def extract_identifier(question: str, pattern: str, label: str) -> str:
    match = re.search(pattern, question, re.IGNORECASE)
    if not match:
        raise ValueError(f"question must identify {label}")
    return match.group(0).upper()
