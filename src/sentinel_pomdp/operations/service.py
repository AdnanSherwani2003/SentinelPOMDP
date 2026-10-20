"""Tenant-authorized facade over durable operation records."""
from __future__ import annotations

from typing import Any

from sentinel_pomdp.security import AuthenticatedPrincipal, Authorizer, Permission

from .models import NewOperationJob, OperationJob, OperationType
from .repository import OperationRepository


class OperationService:
    def __init__(self, repository: OperationRepository) -> None:
        self.repository = repository
        self.authorizer = Authorizer()

    def submit(
        self, principal: AuthenticatedPrincipal, *, operation_type: OperationType,
        correlation_id: str, payload: dict[str, Any], idempotency_key: str | None,
        max_retries: int = 2, replay_safe: bool = False,
    ) -> tuple[OperationJob, bool]:
        self.authorizer.require(principal, Permission.JOB_SUBMIT)
        required = {
            OperationType.DOCUMENT_INGESTION: Permission.DOCUMENT_UPLOAD,
            OperationType.INVESTIGATION: Permission.INVESTIGATION_EXECUTE,
            OperationType.EVALUATION: Permission.CALIBRATION_RUN,
            OperationType.OLIST_BATCH: Permission.DOCUMENT_UPLOAD,
            OperationType.DOMAIN_VALIDATION: Permission.DOMAIN_PACK_MANAGE,
            OperationType.DOMAIN_INVESTIGATION: Permission.INVESTIGATION_EXECUTE,
        }[operation_type]
        self.authorizer.require(principal, required)
        if operation_type is OperationType.OLIST_BATCH:
            self.authorizer.require(principal, Permission.EVIDENCE_REVIEW)
            if "reviewer" not in principal.roles and Permission.ADMIN not in principal.permissions:
                from sentinel_pomdp.security import AuthorizationError
                raise AuthorizationError("reviewer role is required for Olist batch work")
        return self.repository.create_job(NewOperationJob(
            tenant_id=principal.tenant_id, principal_id=principal.principal_id,
            operation_type=operation_type, correlation_id=correlation_id,
            payload=payload, idempotency_key=idempotency_key,
            max_retries=max_retries, replay_safe=replay_safe,
        ))

    def get(self, principal: AuthenticatedPrincipal, job_id: str) -> OperationJob | None:
        self.authorizer.require(principal, Permission.JOB_READ)
        return self.repository.get_job(principal.tenant_id, job_id)

    def list(self, principal: AuthenticatedPrincipal, *, limit: int = 100) -> list[OperationJob]:
        self.authorizer.require(principal, Permission.JOB_READ)
        return self.repository.list_jobs(principal.tenant_id, limit=limit)

    def cancel(self, principal: AuthenticatedPrincipal, job_id: str) -> OperationJob | None:
        self.authorizer.require(principal, Permission.JOB_CANCEL)
        return self.repository.request_cancel(principal.tenant_id, job_id)

    def summary(self, principal: AuthenticatedPrincipal) -> dict[str, Any]:
        self.authorizer.require(principal, Permission.OPERATIONS_READ)
        return self.repository.summary(principal.tenant_id)
