"""Adapters from durable jobs into existing bounded application services."""
from __future__ import annotations

from typing import Any

from sentinel_pomdp.ingestion import EnterpriseDataService, IngestionError
from sentinel_pomdp.graph.repository import BaseGraphRepository
from sentinel_pomdp.intelligence.registry import IntentValidationError, default_scenario_registry
from sentinel_pomdp.investigation.scenario import build_scenario_planner
from sentinel_pomdp.orchestration import InvestigationWorkflow
from sentinel_pomdp.olist import OlistService
from sentinel_pomdp.security import AuthenticatedPrincipal, Permission
from sentinel_pomdp.domains import DomainInvestigationService, DomainPack, DomainPackService
from dataclasses import asdict

from .models import OperationError
from .worker import OperationContext


def domain_validation_handler(service: DomainPackService):
    """Validate untrusted declarative configuration without activating or saving it."""
    def handle(context: OperationContext, payload: dict[str, Any]) -> dict[str, Any]:
        raw = payload.get("domain_pack")
        if not isinstance(raw, dict):
            raise OperationError("INVALID_DOMAIN_PACK", "domain_pack object is required")
        context.safe_boundary({"phase": "domain-validation"})
        try:
            pack = DomainPack.model_validate(raw)
            checked = service.validate(context.claim.job.tenant_id, pack)
        except ValueError as exc:
            raise OperationError("DOMAIN_VALIDATION_FAILED", str(exc)) from None
        return {"valid": True, "domain_id": checked.domain_id,
                "model_version": checked.model_version,
                "immutable_version_id": checked.immutable_version_id,
                "status": checked.status.value}
    return handle


def domain_investigation_handler(service: DomainInvestigationService):
    """Version-pinned, replay-safe factual investigation using the existing queue."""
    def handle(context: OperationContext, payload: dict[str, Any]) -> dict[str, Any]:
        domain_id = str(payload.get("domain_id", ""))
        version = str(payload.get("model_version", ""))
        subject_id = str(payload.get("subject_id", ""))
        question_type = str(payload.get("question_type", ""))
        if (not domain_id or not version or not subject_id
                or question_type not in {"historical", "prospective_purchase", "match"}):
            raise OperationError("INVALID_DOMAIN_INVESTIGATION",
                                 "domain, version, subject and supported question type are required")
        if not all(char.isalnum() or char in "_-." for char in subject_id):
            raise OperationError("INVALID_DOMAIN_SUBJECT", "subject identifier is invalid")
        question = ({"historical": f"Was order {subject_id} delivered late?",
                     "prospective_purchase": f"At purchase time, what was the risk for order {subject_id}?",
                     "match": f"Check invoice {subject_id}"})[question_type]

        def investigate() -> dict[str, Any]:
            try:
                result = service.investigate(context.claim.job.tenant_id, domain_id,
                                             question, version=version)
            except (KeyError, ValueError) as exc:
                raise OperationError("DOMAIN_INVESTIGATION_REJECTED", str(exc)) from None
            if isinstance(result, dict):
                return result
            if not hasattr(result, "model_dump"):
                raise OperationError("PROBABILISTIC_CHECKPOINT_REQUIRED",
                    "probabilistic domains must use the checkpointed investigation handler")
            return result.model_dump(mode="json")

        context.safe_boundary({"phase": "domain-investigation", "domain_id": domain_id,
                               "model_version": version})
        return context.journaled_step("domain-investigation",
            {"domain_id": domain_id, "model_version": version,
             "subject_id": subject_id, "question_type": question_type},
            investigate, resume_started=True)
    return handle


def document_ingestion_handler(service: EnterpriseDataService):
    def handle(context: OperationContext, payload: dict[str, Any]) -> dict[str, Any]:
        upload_id = str(payload.get("upload_id", ""))
        if not upload_id:
            raise OperationError("INVALID_UPLOAD_REFERENCE", "upload_id is required")
        try:
            staged = service.store.get_staged_upload(context.claim.job.tenant_id, upload_id)
        except ValueError as exc:
            raise OperationError("STAGED_UPLOAD_CORRUPT", str(exc)) from None
        if staged is None:
            raise OperationError("STAGED_UPLOAD_NOT_FOUND", "staged upload is unavailable")
        metadata, content = staged
        if payload.get("sha256") != metadata["sha256"]:
            raise OperationError("STAGED_UPLOAD_MISMATCH", "staged upload reference changed")

        def ingest() -> dict[str, Any]:
            try:
                result = service.upload(
                    context.claim.job.tenant_id,
                    dataset_id=metadata["dataset_id"], filename=metadata["filename"],
                    content=content, declared_media_type=metadata["declared_media_type"],
                    source_group=metadata.get("source_group"),
                )
            except IngestionError as exc:
                raise OperationError(exc.code, str(exc)) from None
            return {
                "ingestion_id": result.ingestion_id,
                "document_id": result.document.document_id,
                "duplicate": result.duplicate,
                "candidates_created": result.candidates_created,
            }

        return context.journaled_step(
            "document_ingestion", {"upload_id": upload_id, "sha256": metadata["sha256"]},
            ingest, resume_started=True)
    return handle


def investigation_handler(repository: BaseGraphRepository, checkpointer):
    """Run only an explicitly registered deterministic scenario; no model tools or LLM."""
    registry = default_scenario_registry()

    def handle(context: OperationContext, payload: dict[str, Any]) -> dict[str, Any]:
        scenario_id = str(payload.get("scenario_id", ""))
        try:
            scenario = registry.resolve(scenario_id, context.claim.job.tenant_id)
        except IntentValidationError as exc:
            raise OperationError("UNREGISTERED_SCENARIO", str(exc)) from None
        horizon = int(payload.get("horizon", 2)); max_tool_calls = int(payload.get("max_tool_calls", 3))
        budget = float(payload.get("budget", 1.0))
        if not 0 <= horizon <= 2 or not 0 <= max_tool_calls <= 4 or not 0 <= budget <= 2:
            raise OperationError("INVALID_INVESTIGATION_LIMIT", "investigation limits are out of bounds")
        context.safe_boundary({"phase": "investigation", "scenario_id": scenario_id})
        workflow = InvestigationWorkflow(
            repository, scenario, build_scenario_planner(scenario, horizon),
            checkpointer=checkpointer)
        outcome = workflow.run(
            context.claim.job.tenant_id, thread_id=context.claim.job.job_id,
            max_tool_calls=max_tool_calls, budget=budget)
        context.safe_boundary({"phase": "grounded", "scenario_id": scenario_id})
        return {
            "scenario_id": scenario_id, "model_version": scenario.model_version,
            "decision": outcome.decision, "selected_hypothesis": outcome.selected_hypothesis,
            "final_belief": outcome.final_belief,
            "evidence_status": outcome.evidence_verdict.provenance_status,
            "termination_reason": outcome.termination_reason,
            "fact_ids": outcome.evidence_verdict.fact_ids,
            "evidence_ids": outcome.evidence_verdict.evidence_ids,
            "document_ids": outcome.evidence_verdict.document_ids,
        }
    return handle


def olist_batch_handler(service: OlistService):
    """Resume the existing idempotent review-service importer after authorized enqueue."""
    def handle(context: OperationContext, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            limit = int(payload["limit"]); offset = int(payload.get("offset", 0))
            archive_hash = str(payload["expected_archive_sha256"])
            review_action = str(payload["review_action"])
        except (KeyError, TypeError, ValueError) as exc:
            raise OperationError("INVALID_OLIST_BATCH", "bounded Olist batch fields are required") from exc
        if not 1 <= limit <= 10_000 or offset < 0 or review_action not in {"APPROVE", "REJECT"}:
            raise OperationError("INVALID_OLIST_BATCH", "Olist batch bounds or review action are invalid")
        principal = AuthenticatedPrincipal(
            principal_id=context.claim.job.principal_id,
            tenant_id=context.claim.job.tenant_id,
            roles=frozenset({"reviewer"}),
            permissions=frozenset({Permission.DOCUMENT_UPLOAD, Permission.EVIDENCE_REVIEW}))

        def import_batch() -> dict[str, Any]:
            try:
                return asdict(service.import_orders(
                    principal, limit=limit, offset=offset,
                    expected_archive_sha256=archive_hash,
                    review_action=review_action))
            except ValueError as exc:
                raise OperationError("OLIST_IMPORT_REJECTED", str(exc)) from None

        return context.journaled_step(
            "olist_reviewed_batch",
            {"limit": limit, "offset": offset, "archive_hash": archive_hash,
             "review_action": review_action},
            import_batch, resume_started=True)
    return handle
