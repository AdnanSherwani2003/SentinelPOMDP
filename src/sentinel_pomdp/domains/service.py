"""Bind approved probability packs to approved graph facts."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.ingestion.storage import LocalDocumentStore
from sentinel_pomdp.investigation.evidence_policy import EvidencePolicy
from sentinel_pomdp.investigation.scenario import InvestigationScenario
from sentinel_pomdp.investigation.schemas import GraphInvestigationRequest, InvestigationAction
from sentinel_pomdp.multistep import PlanningConfig

from .models import (
    CalibrationStatus, DomainPack, DomainPackStatus,
    InvestigationMode, ParameterSource,
)


class DomainPackService:
    def __init__(self, store: LocalDocumentStore, repository: BaseGraphRepository) -> None:
        self.store = store
        self.repository = repository

    def save(self, tenant_id: str, pack: DomainPack) -> DomainPack:
        if pack.tenant_owner is not None and pack.tenant_owner != tenant_id:
            raise ValueError("domain-pack tenant owner does not match authenticated tenant")
        existing = self.get_version(tenant_id, pack.domain_id, pack.model_version)
        current = self.get(tenant_id, pack.domain_id)
        immutable_statuses = {
            DomainPackStatus.APPROVED, DomainPackStatus.ACTIVE,
            DomainPackStatus.RETIRED, DomainPackStatus.REVALIDATION_REQUIRED,
        }
        if existing is not None and existing.status in immutable_statuses:
            if existing.semantic_payload() != pack.semantic_payload():
                raise ValueError("an existing model version cannot be rewritten")
        activate = pack.status in {DomainPackStatus.APPROVED, DomainPackStatus.ACTIVE}
        self.store.put_domain_pack(tenant_id, pack, activate=activate)
        return pack

    def validate(self, tenant_id: str, pack: DomainPack) -> DomainPack:
        if pack.tenant_owner is not None and pack.tenant_owner != tenant_id:
            raise ValueError("domain-pack tenant owner does not match authenticated tenant")
        checked = DomainPack.model_validate(pack.model_dump())
        if checked.status == DomainPackStatus.DRAFT:
            checked = checked.model_copy(update={"status": DomainPackStatus.VALIDATED})
        return checked

    def submit_for_review(self, tenant_id: str, domain_id: str, model_version: str) -> DomainPack:
        pack = self.get_version(tenant_id, domain_id, model_version)
        if pack is None or pack.status not in {DomainPackStatus.DRAFT, DomainPackStatus.VALIDATED}:
            raise ValueError("only a validated draft can be submitted for review")
        submitted = pack.model_copy(update={"status": DomainPackStatus.REVIEW_PENDING})
        self.save(tenant_id, submitted)
        return submitted

    def list(self, tenant_id: str) -> list[DomainPack]:
        packs = self.store.list_domain_packs(tenant_id, DomainPack)
        unique = {(pack.domain_id, pack.model_version): pack for pack in packs}
        return sorted(unique.values(), key=lambda item: (item.domain_id, item.model_version))

    def versions(self, tenant_id: str, domain_id: str) -> list[DomainPack]:
        return [pack for pack in self.list(tenant_id) if pack.domain_id == domain_id]

    def get_version(self, tenant_id: str, domain_id: str, model_version: str) -> DomainPack | None:
        return next((pack for pack in self.versions(tenant_id, domain_id)
                     if pack.model_version == model_version), None)

    def get(self, tenant_id: str, domain_id: str) -> DomainPack | None:
        return self.store.get_domain_pack(tenant_id, domain_id, DomainPack)

    def approve(self, tenant_id: str, domain_id: str, model_version: str,
                reviewer_id: str) -> DomainPack:
        pack = self.get_version(tenant_id, domain_id, model_version)
        if pack is None:
            raise ValueError("domain-pack version is unavailable")
        if (pack.investigation_mode == InvestigationMode.FACTUAL
                and pack.status != DomainPackStatus.REVIEW_PENDING):
            raise ValueError("factual domain packs must be submitted for review before approval")
        calibration = pack.calibration
        if pack.parameter_source == ParameterSource.EMPIRICALLY_ESTIMATED:
            if calibration is None or calibration.status != CalibrationStatus.VALIDATED_ON_HOLDOUT:
                raise ValueError("candidate calibration is not eligible for pilot approval")
            calibration = calibration.model_copy(update={
                "status": CalibrationStatus.APPROVED_FOR_PILOT,
                "effective_at": datetime.now(timezone.utc)})
        governance = pack.governance
        if governance is not None:
            governance = governance.model_copy(update={
                "reviewer": reviewer_id, "approved_at": datetime.now(timezone.utc)})
        approved = pack.model_copy(update={"status": DomainPackStatus.APPROVED,
            "approved_by": reviewer_id, "calibration": calibration, "governance": governance})
        approved = DomainPack.model_validate(approved.model_dump())
        self.save(tenant_id, approved)
        return approved

    def activate(self, tenant_id: str, domain_id: str, model_version: str) -> DomainPack:
        pack = self.get_version(tenant_id, domain_id, model_version)
        if pack is None or pack.status not in {DomainPackStatus.APPROVED, DomainPackStatus.ACTIVE}:
            raise ValueError("activation requires an approved immutable version")
        active = pack.model_copy(update={"status": DomainPackStatus.ACTIVE})
        active = DomainPack.model_validate(active.model_dump())
        self.store.put_domain_pack(tenant_id, active, activate=True)
        return active

    def retire(self, tenant_id: str, domain_id: str, model_version: str,
               reason: str) -> DomainPack:
        pack = self.get_version(tenant_id, domain_id, model_version)
        if pack is None:
            raise ValueError("domain-pack version is unavailable")
        governance = pack.governance
        if governance is not None:
            governance = governance.model_copy(update={
                "retired_at": datetime.now(timezone.utc), "retirement_reason": reason})
        retired = pack.model_copy(update={
            "status": DomainPackStatus.RETIRED, "governance": governance})
        self.save(tenant_id, retired)
        current = self.get(tenant_id, domain_id)
        if current is not None and current.model_version == model_version:
            self.store.put_domain_pack(tenant_id, retired, activate=True)
        return retired

    def require_revalidation(self, tenant_id: str, domain_id: str,
                             model_version: str, reason: str) -> DomainPack:
        pack = self.get_version(tenant_id, domain_id, model_version)
        if pack is None:
            raise ValueError("domain-pack version is unavailable")
        governance = pack.governance
        if governance is not None:
            governance = governance.model_copy(update={
                "validation_findings": [*governance.validation_findings,
                                        f"REVALIDATION_REQUIRED:{reason}"]})
        result = pack.model_copy(update={
            "status": DomainPackStatus.REVALIDATION_REQUIRED, "governance": governance})
        self.save(tenant_id, result)
        current = self.get(tenant_id, domain_id)
        if current is not None and current.model_version == model_version:
            self.store.put_domain_pack(tenant_id, result, activate=True)
        return result

    def reject(self, tenant_id: str, domain_id: str, model_version: str) -> DomainPack:
        pack = self.get_version(tenant_id, domain_id, model_version)
        if pack is None:
            raise ValueError("domain-pack version is unavailable")
        calibration = (pack.calibration.model_copy(update={"status": CalibrationStatus.REJECTED})
                       if pack.calibration else None)
        rejected = pack.model_copy(update={
            "status": DomainPackStatus.RETIRED, "calibration": calibration})
        self.save(tenant_id, rejected)
        current = self.get(tenant_id, domain_id)
        if current is not None and current.model_version == model_version:
            self.store.put_domain_pack(tenant_id, rejected, activate=True)
        return rejected

    def rollback(self, tenant_id: str, domain_id: str, model_version: str) -> DomainPack:
        pack = self.get_version(tenant_id, domain_id, model_version)
        if pack is None or pack.status != DomainPackStatus.APPROVED:
            raise ValueError("rollback requires a previously approved version")
        self.store.put_domain_pack(tenant_id, pack, activate=True)
        return pack

    def invalidate_for_dataset(self, tenant_id: str, dataset_id: str, reason: str) -> list[DomainPack]:
        """Retire active empirical packs when calibration-source governance changes."""
        invalidated = []
        active = {pack.domain_id: self.get(tenant_id, pack.domain_id) for pack in self.list(tenant_id)}
        for pack in self.list(tenant_id):
            calibration = pack.calibration
            if (calibration is None or calibration.training_dataset_id != dataset_id
                    or pack.status == DomainPackStatus.RETIRED):
                continue
            updated_calibration = calibration.model_copy(update={
                "status": CalibrationStatus.REJECTED,
                "limitations": [*calibration.limitations, f"REVALIDATION_REQUIRED:{reason}"]})
            updated = pack.model_copy(update={
                "status": DomainPackStatus.RETIRED, "calibration": updated_calibration})
            self.save(tenant_id, updated)
            if (active.get(pack.domain_id) is not None
                    and active[pack.domain_id].model_version == pack.model_version):
                self.store.put_domain_pack(tenant_id, updated, activate=True)
            invalidated.append(updated)
        return invalidated

    def build_scenario(self, tenant_id: str, domain_id: str, question: str,
                       *, model_version: str | None = None) -> InvestigationScenario:
        pack = (self.get_version(tenant_id, domain_id, model_version)
                if model_version else self.get(tenant_id, domain_id))
        if pack is None or pack.status not in {DomainPackStatus.APPROVED, DomainPackStatus.ACTIVE}:
            raise ValueError("an approved domain pack is required")
        if pack.investigation_mode != InvestigationMode.PROBABILISTIC:
            raise ValueError("factual domain packs do not use the POMDP scenario builder")
        match = re.search(r"\bPO-[A-Za-z0-9_-]+\b", question, re.IGNORECASE)
        if not match:
            raise ValueError("question must identify a purchase order")
        subject_id = match.group(0).upper()
        facts = self.repository.find_facts(tenant_id, subject_id=subject_id)
        requests = {}
        targets = {}
        required = {}
        source_groups = {}
        for configured in pack.actions:
            matches = [fact for fact in facts if fact.relation_type in configured.relation_hypotheses]
            if not matches:
                continue
            fact = sorted(matches, key=lambda item: item.observed_at)[-1]
            action_id = configured.action_id
            requests[action_id] = GraphInvestigationRequest(
                tenant_id=tenant_id, action_name=InvestigationAction.FACT_EVIDENCE,
                target_id=fact.fact_id)
            hypothesis = configured.relation_hypotheses[fact.relation_type]
            targets[action_id] = hypothesis
            required.setdefault(hypothesis, set()).add(fact.fact_id)
        if not requests:
            raise ValueError("no approved graph evidence matches this question")
        return InvestigationScenario(
            name=f"{pack.name}: {subject_id}", prior=pack.prior, requests=requests,
            action_targets=targets,
            evidence_policy=EvidencePolicy(
                required_fact_ids=required,
                minimum_independent_sources=pack.minimum_independent_sources),
            answer_threshold=pack.answer_threshold or .75,
            scenario_id=f"{pack.domain_id}:{subject_id}",
            observation_model=pack.observation_model,
            action_costs={action.action_id: action.cost for action in pack.actions
                          if action.action_id in requests},
            model_version=pack.model_version,
            planning_config=PlanningConfig(
                horizon=pack.planning_horizon, gamma=pack.discount_factor,
                correct_answer_reward=pack.rewards.get("correct_answer_reward", 5),
                incorrect_answer_penalty=pack.rewards.get("incorrect_answer_penalty", 7),
                abstain_reward=pack.rewards.get("abstain_reward", 0),
                answer_threshold=pack.answer_threshold or .75, min_observations=1,
                information_gain_weight=.15),
        )
