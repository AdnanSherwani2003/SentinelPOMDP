"""FastAPI application factory; the HTTP layer never performs POMDP reasoning."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from sentinel_pomdp.data.synthetic.supplier_delay import generate_supplier_delay_dataset
from sentinel_pomdp.calibration import (
    build_candidate_domain_pack, estimate_categorical_model, evaluate_predictions,
)
from sentinel_pomdp.domains import (
    DomainInvestigationService, DomainPack, DomainPackService, DomainPackStatus,
    OlistLogisticsAdapter, ProcurementAdapter,
)
from sentinel_pomdp.graph.connection import Neo4jConnectionManager
from sentinel_pomdp.graph.ingestion import KnowledgeGraphIngestionPipeline
from sentinel_pomdp.graph.repository import InMemoryGraphRepository, Neo4jGraphRepository
from sentinel_pomdp.graph.schemas import ProvenanceChain, ProvenanceRecord
from sentinel_pomdp.ingestion import (
    DatasetConfiguration, EnterpriseDataService, IngestionError, LocalDocumentStore,
    ReviewAction,
)
from sentinel_pomdp.pilot import (
    LabelStatus, PilotSplit, chronological_group_split, validate_dataset,
)
from sentinel_pomdp.pilot.replay import ReplayPolicy, replay_logged_policy
from sentinel_pomdp.olist import OlistDataset, OlistService, Snapshot
from sentinel_pomdp.intelligence import (
    DeterministicFakeLLM, GroqResponsesClient, InvestigationIntelligenceService,
    OpenAIResponsesClient, ResponseStatus,
)
from sentinel_pomdp.intelligence.clients import LLMClientError
from sentinel_pomdp.observability import MetricsStore
from sentinel_pomdp.operations import (
    IdempotencyConflict, OperationAuditEvent, OperationError, OperationService, OperationType,
    PostgresOperationRepository, SQLiteOperationRepository,
)
from sentinel_pomdp.security import (
    AuthenticatedPrincipal, AuthenticationError, AuthorizationError, Authorizer,
    LocalAPIKeyAuthenticator, Permission, PrivacyPolicyError,
    ProtectedInvestigationService, ProviderDataPolicy, ResourceLimitError,
    SecurityBoundaryError, SecurityLimits,
)
from sentinel_pomdp.security.audit import audit_event

from .schemas import (
    BeliefChange, ErrorBody, HealthResponse, InvestigationAPIResponse,
    InvestigationRequest, DocumentLookupResponse, MetricsResponse, ModelReviewRequest,
    PilotCalibrationRequest, ReviewRequest, DomainInvestigationRequest,
    DomainLifecycleRequest,
    OlistImportRequest, OlistPredictionRequest,
    SessionResponse, TimelineStep, JobSubmitRequest,
    TimingSummary, TracePhase, TraceResponse,
)
from .settings import AppSettings

logger = logging.getLogger("sentinel_pomdp.api")
bearer = HTTPBearer(auto_error=False)


class APIError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class _UnavailableLLM:
    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.model = "unavailable"

    def generate_structured(self, **_kwargs):
        raise LLMClientError("configured provider is unavailable")


@dataclass
class ApplicationDependencies:
    service: ProtectedInvestigationService
    authenticator: LocalAPIKeyAuthenticator
    metrics: MetricsStore
    backend_name: str
    provider_name: str
    readiness: Callable[[], bool]
    close: Callable[[], None] = lambda: None
    configuration_errors: tuple[str, ...] = ()
    company_data: EnterpriseDataService | None = None
    domain_packs: DomainPackService | None = None
    domain_runtime: DomainInvestigationService | None = None
    olist: OlistService | None = None
    operations: OperationService | None = None
    graph_repository: Any | None = None


def build_dependencies(settings: AppSettings) -> ApplicationDependencies:
    errors = settings.validate()
    manager: Neo4jConnectionManager | None = None
    if settings.backend == "neo4j":
        manager = Neo4jConnectionManager()
        repository = Neo4jGraphRepository(manager)
        readiness = manager.ping
    else:
        repository = InMemoryGraphRepository()
        report = KnowledgeGraphIngestionPipeline(repository).ingest_dataset(
            generate_supplier_delay_dataset())
        if not report.is_success:
            errors.append("in-memory dataset initialization failed")
        readiness = lambda: True

    try:
        if settings.provider == "groq":
            llm = GroqResponsesClient()
        elif settings.provider == "openai":
            llm = OpenAIResponsesClient()
        else:
            llm = DeterministicFakeLLM()
    except LLMClientError:
        llm = _UnavailableLLM(settings.provider)

    authenticator = LocalAPIKeyAuthenticator()
    if settings.api_key and len(settings.api_key) >= 32:
        authenticator.register(settings.api_key, AuthenticatedPrincipal(
            principal_id=settings.principal_id, tenant_id=settings.tenant_id,
            roles=settings.roles, permissions=settings.permissions,
        ))
    service = ProtectedInvestigationService(
        authenticator, InvestigationIntelligenceService(repository, llm),
        data_policy=ProviderDataPolicy(
            settings.external_llm_enabled, settings.allowed_external_providers),
        limits=SecurityLimits(
            max_horizon=2, max_tool_calls=4, max_budget=2.0,
            max_requests_per_minute=settings.rate_limit_per_minute,
        ),
    )
    document_store = LocalDocumentStore(settings.document_store_path)
    company_data = EnterpriseDataService(
        document_store, repository, max_upload_bytes=settings.max_upload_bytes,
        max_uncompressed_bytes=settings.max_uncompressed_bytes,
        max_documents_per_tenant=settings.max_documents_per_tenant)
    domain_packs = DomainPackService(document_store, repository)
    olist = None
    if settings.olist_data_path:
        try:
            olist = OlistService(OlistDataset(settings.olist_data_path), repository,
                                 review_service=company_data)
        except (ValueError, OSError) as exc:
            errors.append(f"Olist dataset unavailable: {exc}")
    adapters = [ProcurementAdapter(repository)]
    if olist is not None:
        adapters.append(OlistLogisticsAdapter(olist))
    domain_runtime = DomainInvestigationService(domain_packs, adapters)
    operations = None
    operations_repository = None
    if settings.operations_backend == "sqlite":
        try:
            operations_repository = SQLiteOperationRepository(settings.operations_database_path)
            operations = OperationService(operations_repository)
        except (OSError, ValueError) as exc:
            errors.append(f"operations database unavailable: {type(exc).__name__}")
    elif settings.operations_backend == "postgres":
        try:
            operations_repository = PostgresOperationRepository(
                settings.operations_database_url or "")
            operations = OperationService(operations_repository)
        except Exception as exc:
            errors.append(f"operations database unavailable: {type(exc).__name__}")

    def close_dependencies() -> None:
        if operations_repository is not None:
            operations_repository.close()
        if manager is not None:
            manager.close()

    return ApplicationDependencies(
        service=service, authenticator=authenticator, metrics=MetricsStore(),
        backend_name=settings.backend, provider_name=settings.provider,
        readiness=readiness, close=close_dependencies,
        configuration_errors=tuple(errors), company_data=company_data,
        domain_packs=domain_packs, domain_runtime=domain_runtime,
        olist=olist,
        operations=operations,
        graph_repository=repository,
    )


def _credential(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(401, "AUTHENTICATION_FAILED", "Authentication is required")
    return credentials.credentials


def _principal(deps: ApplicationDependencies, credential: str) -> AuthenticatedPrincipal:
    try:
        return deps.authenticator.authenticate(credential)
    except AuthenticationError as exc:
        deps.metrics.record_auth_failure()
        raise APIError(401, exc.code, "Authentication failed") from None


def _require(principal: AuthenticatedPrincipal, permission: Permission) -> None:
    try:
        Authorizer().require(principal, permission)
    except AuthorizationError as exc:
        raise _translate_security_error(exc) from None


def _ingestion_error(exc: IngestionError) -> APIError:
    status = 413 if exc.code in {"UPLOAD_TOO_LARGE", "EXPANSION_LIMIT"} else 422
    if exc.code in {"DOCUMENT_NOT_FOUND", "DATASET_NOT_FOUND"}:
        status = 404
    return APIError(status, exc.code, str(exc))


def _audit_company(deps: ApplicationDependencies, request: Request,
                   principal: AuthenticatedPrincipal, operation: str,
                   resource_id: str) -> None:
    correlation = request.state.correlation_id
    deps.service.audit_log.emit(audit_event(
        event_id=f"{correlation}:{operation}:{resource_id}", correlation_id=correlation,
        operation=operation, outcome="ALLOW", reason_code="COMPLETED",
        principal_id=principal.principal_id, tenant_id=principal.tenant_id,
        resource_id=resource_id))


def _translate_security_error(exc: SecurityBoundaryError) -> APIError:
    if isinstance(exc, AuthenticationError):
        return APIError(401, exc.code, "Authentication failed")
    if isinstance(exc, AuthorizationError):
        return APIError(403, exc.code, "Resource unavailable or access denied")
    if isinstance(exc, PrivacyPolicyError):
        return APIError(403, exc.code, "External model processing is not permitted")
    if isinstance(exc, ResourceLimitError):
        return APIError(429, exc.code, str(exc))
    return APIError(503, exc.code, "Protected operation failed")


def _status(response) -> str:
    if response.status == ResponseStatus.UNSUPPORTED:
        return "UNSUPPORTED_REQUEST"
    if response.status == ResponseStatus.CLARIFICATION_REQUIRED:
        return "CLARIFICATION_REQUIRED"
    if response.status == ResponseStatus.INTERPRETATION_FAILED:
        return "PROVIDER_FAILURE"
    outcome = response.investigation or {}
    reason = str(outcome.get("termination_reason", "")).lower()
    if "budget" in reason:
        return "BUDGET_EXHAUSTED"
    return response.decision or response.status.value


def _timeline(response) -> list[TimelineStep]:
    outcome = response.investigation or {}
    return [TimelineStep(
        step_number=step["step_number"], action=step["chosen_action"],
        observation=step.get("observation_token"), tool_status=step.get("tool_status"),
        belief_before=step.get("belief_before", {}), belief_after=step.get("belief_after", {}),
        evidence_ids=step.get("evidence_ids", []), document_ids=step.get("document_ids", []),
        expected_utility=step.get("expected_action_utility", 0),
        investigation_cost=step.get("investigation_cost", 0),
        latency_ms=step.get("latency_ms"), evidence_support=step.get("evidence_support", "UNKNOWN"),
    ) for step in outcome.get("steps", [])]


def _public_response(response, correlation_id: str, provider_name: str,
                     request_ms: float = 0) -> InvestigationAPIResponse:
    timeline = _timeline(response)
    initial = timeline[0].belief_before if timeline else response.final_belief
    hypotheses = sorted(set(initial) | set(response.final_belief))
    usage = response.llm_usage
    provider = usage[-1].provider if usage else provider_name
    model = usage[-1].model if usage else getattr(response, "model", "rules-v1")
    outcome = response.investigation or {}
    return InvestigationAPIResponse(
        investigation_id=response.trace_id, correlation_id=correlation_id,
        status=_status(response), original_question=response.question,
        scenario_id=response.scenario_id, decision=response.decision,
        selected_hypothesis=response.selected_hypothesis, posterior=response.final_belief,
        belief_changes=[BeliefChange(
            hypothesis=name, initial=initial.get(name, 0), final=response.final_belief.get(name, 0))
            for name in hypotheses],
        explanation=response.explanation, fact_ids=response.fact_ids,
        supporting_evidence_ids=response.supporting_evidence_ids,
        contradicting_evidence_ids=response.contradicting_evidence_ids,
        document_ids=response.document_ids, provenance_status=response.provenance_status,
        limitation=response.limitation, timeline=timeline,
        investigation_cost=outcome.get("total_cost", 0), provider=provider, model=model,
        explanation_fallback_used=response.explanation_fallback_used,
        grounding_valid=response.grounding_valid,
        trace_available=response.investigation is not None,
        timings=TimingSummary(
            planning_ms=outcome.get("planning_runtime_ms", 0),
            graph_ms=outcome.get("tool_runtime_ms", 0),
            model_ms=sum(item.latency_ms for item in usage), request_ms=request_ms),
    )


def _database_unavailable(response) -> bool:
    trace = (response.investigation or {}).get("metadata", {}).get("workflow_trace", [])
    return any(item.get("tool_status") == "DATABASE_UNAVAILABLE" for item in trace)


def _trace_response(response) -> TraceResponse:
    outcome = response.investigation or {}
    phases = [TracePhase(
        node=item.get("node_name", "unknown"), route=item.get("route"),
        tool_status=item.get("tool_status"), observation=item.get("observation"),
        duration_ms=item.get("node_runtime_ms"),
        termination_reason=item.get("termination_reason"),
    ) for item in outcome.get("metadata", {}).get("workflow_trace", [])]
    return TraceResponse(
        investigation_id=response.trace_id, scenario_id=response.scenario_id,
        decision=response.decision, timeline=_timeline(response), phases=phases)


def create_app(settings: AppSettings | None = None,
               dependencies: ApplicationDependencies | None = None) -> FastAPI:
    settings = settings or AppSettings.from_environment()
    deps = dependencies or build_dependencies(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if settings.deployment_mode == "candidate":
            if deps.configuration_errors:
                raise RuntimeError(
                    "candidate startup rejected unsafe or incomplete configuration: "
                    + "; ".join(deps.configuration_errors))
            if not await run_in_threadpool(deps.readiness):
                raise RuntimeError("candidate startup rejected unavailable required components")
        yield
        deps.close()

    app = FastAPI(
        title="SentinelPOMDP", version="12.0", docs_url="/docs", redoc_url=None,
        lifespan=lifespan,
    )
    app.state.dependencies = deps
    app.state.settings = settings

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        correlation_id = str(uuid4())
        request.state.correlation_id = correlation_id
        started = perf_counter()
        response = await call_next(request)
        duration_ms = (perf_counter() - started) * 1000
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        logger.info(json.dumps({
            "event": "http_request", "correlation_id": correlation_id,
            "method": request.method, "path": request.url.path,
            "status": response.status_code, "duration_ms": round(duration_ms, 3),
        }, sort_keys=True))
        return response

    @app.exception_handler(APIError)
    async def api_error(request: Request, exc: APIError):
        body = ErrorBody(code=exc.code, message=exc.message,
                         correlation_id=request.state.correlation_id)
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _exc: RequestValidationError):
        body = ErrorBody(code="INVALID_REQUEST", message="Request validation failed",
                         correlation_id=request.state.correlation_id)
        return JSONResponse(status_code=422, content=body.model_dump())

    @app.exception_handler(Exception)
    async def internal_error(request: Request, _exc: Exception):
        logger.exception(json.dumps({"event": "internal_error",
                                     "correlation_id": request.state.correlation_id}))
        body = ErrorBody(code="INTERNAL_ERROR", message="The request could not be completed",
                         correlation_id=request.state.correlation_id)
        return JSONResponse(status_code=500, content=body.model_dump())

    @app.get("/health/live", response_model=HealthResponse)
    def live():
        return HealthResponse(status="live", backend=deps.backend_name, provider=deps.provider_name)

    @app.get("/health/ready", response_model=HealthResponse)
    def ready():
        backend_ready = False if deps.configuration_errors else deps.readiness()
        if deps.operations is not None:
            backend_ready = backend_ready and deps.operations.repository.ping()
        if not backend_ready:
            raise APIError(503, "NOT_READY", "Required application components are unavailable")
        return HealthResponse(status="ready", backend=deps.backend_name, provider=deps.provider_name)

    @app.get("/api/v1/session", response_model=SessionResponse)
    def session(credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        return SessionResponse(
            authenticated=True, principal_id=principal.principal_id,
            tenant_id=principal.tenant_id,
            permissions=sorted(item.value for item in principal.permissions))

    def _operations() -> OperationService:
        if deps.operations is None:
            raise APIError(503, "OPERATIONS_UNAVAILABLE", "Durable operations are unavailable")
        return deps.operations

    def _operation_denied(principal: AuthenticatedPrincipal, request: Request,
                          operation: str) -> None:
        if deps.operations is None:
            return
        deps.operations.repository.emit_audit(OperationAuditEvent(
            event_id=str(uuid4()), occurred_at=datetime.now(timezone.utc),
            operation=operation, outcome="DENY", reason_code="AUTHORIZATION_FAILED",
            correlation_id=request.state.correlation_id, tenant_id=principal.tenant_id,
            principal_id=principal.principal_id))

    @app.post("/api/v1/jobs", status_code=202)
    def submit_job(payload: JobSubmitRequest, request: Request,
                   credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        try:
            job, created = _operations().submit(
                principal, operation_type=OperationType(payload.operation_type),
                correlation_id=request.state.correlation_id, payload=payload.payload,
                idempotency_key=payload.idempotency_key,
                replay_safe=payload.operation_type in {
                    "DOCUMENT_INGESTION", "INVESTIGATION", "EVALUATION"},
            )
        except IdempotencyConflict as exc:
            raise APIError(409, exc.code, str(exc)) from None
        except OperationError as exc:
            raise APIError(422, exc.code, str(exc)) from None
        except AuthorizationError as exc:
            _operation_denied(principal, request, "job.submit")
            raise _translate_security_error(exc) from None
        return {**job.public_dict(), "created": created}

    @app.get("/api/v1/jobs")
    def list_jobs(request: Request, limit: int = 100, credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        try:
            return [job.public_dict() for job in _operations().list(principal, limit=limit)]
        except AuthorizationError as exc:
            _operation_denied(principal, request, "job.list")
            raise _translate_security_error(exc) from None

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str, request: Request, credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        try:
            job = _operations().get(principal, job_id)
        except AuthorizationError as exc:
            _operation_denied(principal, request, "job.read")
            raise _translate_security_error(exc) from None
        if job is None:
            raise APIError(404, "JOB_NOT_FOUND", "Job unavailable in tenant scope")
        return job.public_dict()

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request, credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        try:
            job = _operations().cancel(principal, job_id)
        except AuthorizationError as exc:
            _operation_denied(principal, request, "job.cancel")
            raise _translate_security_error(exc) from None
        if job is None:
            raise APIError(404, "JOB_NOT_FOUND", "Job unavailable in tenant scope")
        return job.public_dict()

    @app.get("/api/v1/operations/summary")
    def operations_summary(request: Request, credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        try:
            return _operations().summary(principal)
        except AuthorizationError as exc:
            _operation_denied(principal, request, "operations.summary")
            raise _translate_security_error(exc) from None

    @app.get("/api/v1/operations/health")
    def operations_health(request: Request, credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        try:
            _require(principal, Permission.OPERATIONS_READ)
        except APIError:
            _operation_denied(principal, request, "operations.health")
            raise
        operations = _operations()
        summary = operations.summary(principal)
        document_writable = bool(
            deps.company_data and deps.company_data.store.writable())
        return {
            "tenant_id": principal.tenant_id,
            "api": "ready",
            "operational_database": "ready" if operations.repository.ping() else "unavailable",
            "neo4j": "ready" if deps.readiness() else "unavailable",
            "document_storage": "writable" if document_writable else "unavailable",
            "worker": "ready" if summary["fresh_workers"] else "stale-or-not-started",
            "queue": "healthy" if not summary["lease_expired_jobs"] else "lease-expired",
            "configuration": "valid" if not deps.configuration_errors else "invalid",
        }

    @app.post("/api/v1/investigations",
              response_model=InvestigationAPIResponse | DocumentLookupResponse)
    async def investigate(payload: InvestigationRequest, request: Request,
                          credential: str = Depends(_credential)):
        if deps.configuration_errors or not await run_in_threadpool(deps.readiness):
            raise APIError(503, "NOT_READY", "Required application components are unavailable")
        principal = _principal(deps, credential)
        if payload.mode == "document_lookup":
            _require(principal, Permission.DOCUMENT_READ)
            if deps.company_data is None:
                raise APIError(503, "NOT_READY", "Company data services are unavailable")
            try:
                result = await run_in_threadpool(
                    deps.company_data.lookup, principal.tenant_id, payload.question)
            except IngestionError as exc:
                raise _ingestion_error(exc) from None
            return DocumentLookupResponse(**result)
        if payload.mode == "domain_pomdp":
            if deps.domain_packs is None or not payload.domain_pack_id:
                raise APIError(422, "DOMAIN_PACK_REQUIRED", "An approved domain pack is required")
            try:
                scenario = await run_in_threadpool(
                    deps.domain_packs.build_scenario, principal.tenant_id,
                    payload.domain_pack_id, payload.question)
                secured = await run_in_threadpool(
                    deps.service.investigate_scenario, credential, payload.question, scenario,
                    correlation_id=request.state.correlation_id,
                    horizon=payload.planning_horizon if payload.planning_horizon is not None
                    else settings.planning_horizon,
                    max_tool_calls=settings.max_tool_calls, budget=settings.investigation_budget)
            except ValueError as exc:
                raise APIError(422, "DOMAIN_SCENARIO_UNAVAILABLE", str(exc)) from None
            except SecurityBoundaryError as exc:
                raise _translate_security_error(exc) from None
            return _public_response(
                secured.response, request.state.correlation_id, "deterministic-domain-pack")
        started = perf_counter()
        try:
            secured = await asyncio.wait_for(run_in_threadpool(
                deps.service.investigate, credential, payload.question,
                correlation_id=request.state.correlation_id,
                horizon=payload.planning_horizon if payload.planning_horizon is not None
                else settings.planning_horizon,
                max_tool_calls=settings.max_tool_calls, budget=settings.investigation_budget,
            ), timeout=settings.request_timeout_seconds)
        except asyncio.TimeoutError:
            raise APIError(504, "INVESTIGATION_TIMEOUT", "The investigation exceeded its time limit")
        except SecurityBoundaryError as exc:
            raise _translate_security_error(exc) from None
        request_ms = (perf_counter() - started) * 1000
        response = secured.response
        if _database_unavailable(response):
            deps.metrics.record(principal.tenant_id, status="DATABASE_UNAVAILABLE",
                                latency_ms=request_ms)
            raise APIError(503, "DATABASE_UNAVAILABLE", "The evidence database is unavailable")
        public = _public_response(response, request.state.correlation_id,
                                  deps.provider_name, request_ms)
        outcome = response.investigation or {}
        deps.metrics.record(
            principal.tenant_id, status=public.status, latency_ms=request_ms,
            tool_calls=outcome.get("metadata", {}).get("tool_calls", 0),
            investigation_cost=public.investigation_cost,
            planning_ms=public.timings.planning_ms, graph_ms=public.timings.graph_ms,
            model_ms=public.timings.model_ms,
            fallback=public.explanation_fallback_used,
        )
        if public.status == "PROVIDER_FAILURE":
            raise APIError(502, "PROVIDER_FAILURE", "The language provider could not interpret the request")
        return public

    @app.post("/api/v1/company-data/datasets", response_model=DatasetConfiguration)
    def configure_dataset(payload: DatasetConfiguration, request: Request,
                          credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOMAIN_PACK_MANAGE)
        assert deps.company_data is not None
        result = deps.company_data.configure_dataset(principal.tenant_id, payload)
        _audit_company(deps, request, principal, "dataset.configure", payload.dataset_id)
        return result

    @app.get("/api/v1/company-data/datasets", response_model=list[DatasetConfiguration])
    def datasets(credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_READ)
        assert deps.company_data is not None
        return deps.company_data.store.list_datasets(principal.tenant_id)

    @app.post("/api/v1/company-data/uploads")
    async def upload_document(
            request: Request, dataset_id: str = Form(...),
            source_group: str | None = Form(default=None), file: UploadFile = File(...),
            credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_UPLOAD)
        assert deps.company_data is not None
        content = await file.read(settings.max_upload_bytes + 1)
        try:
            result = await run_in_threadpool(
                deps.company_data.upload, principal.tenant_id, dataset_id=dataset_id,
                filename=file.filename or "upload", content=content,
                declared_media_type=file.content_type or "application/octet-stream",
                source_group=source_group)
            _audit_company(deps, request, principal, "document.upload", result.document.document_id)
            return result
        except IngestionError as exc:
            raise _ingestion_error(exc) from None
        finally:
            await file.close()

    @app.post("/api/v1/company-data/uploads/jobs", status_code=202)
    async def enqueue_document_upload(
            request: Request, dataset_id: str = Form(...),
            source_group: str | None = Form(default=None),
            idempotency_key: str | None = Form(default=None),
            file: UploadFile = File(...), credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_UPLOAD)
        _require(principal, Permission.JOB_SUBMIT)
        assert deps.company_data is not None
        operations = _operations()
        content = await file.read(settings.max_upload_bytes + 1)
        try:
            if len(content) > settings.max_upload_bytes:
                raise APIError(413, "UPLOAD_TOO_LARGE", "upload exceeds the configured byte limit")
            staged = deps.company_data.store.stage_upload(
                principal.tenant_id, filename=file.filename or "upload",
                content=content, declared_media_type=file.content_type or "application/octet-stream",
                dataset_id=dataset_id, source_group=source_group)
            job, created = operations.submit(
                principal, operation_type=OperationType.DOCUMENT_INGESTION,
                correlation_id=request.state.correlation_id,
                payload={"upload_id": staged["upload_id"], "sha256": staged["sha256"]},
                idempotency_key=idempotency_key, replay_safe=True)
            return {**job.public_dict(), "created": created}
        except IdempotencyConflict as exc:
            raise APIError(409, exc.code, str(exc)) from None
        except OperationError as exc:
            raise APIError(422, exc.code, str(exc)) from None
        finally:
            await file.close()

    @app.get("/api/v1/company-data/documents")
    def documents(credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_READ)
        assert deps.company_data is not None
        return deps.company_data.store.list_documents(principal.tenant_id)

    @app.get("/api/v1/company-data/documents/{document_id}/content")
    def document_content(document_id: str, credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_READ)
        assert deps.company_data is not None
        metadata = deps.company_data.store.get_document(principal.tenant_id, document_id)
        content = deps.company_data.store.get_content(principal.tenant_id, document_id)
        if metadata is None or content is None:
            raise APIError(404, "DOCUMENT_NOT_FOUND", "Document is unavailable")
        return Response(content=content, media_type=metadata.media_type, headers={
            "Content-Disposition": f'attachment; filename="{Path(metadata.source_name).name}"'})

    @app.post("/api/v1/company-data/documents/{document_id}/withdraw")
    def withdraw_document(document_id: str, request: Request,
                          credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.EVIDENCE_REVIEW)
        assert deps.company_data is not None
        try:
            result = deps.company_data.withdraw(principal.tenant_id, document_id)
            if deps.domain_packs is not None:
                deps.domain_packs.invalidate_for_dataset(
                    principal.tenant_id, result.dataset_id,
                    f"source document {document_id} was withdrawn")
            _audit_company(deps, request, principal, "document.withdraw", document_id)
            return result
        except IngestionError as exc:
            raise _ingestion_error(exc) from None

    @app.get("/api/v1/company-data/candidates")
    def candidates(credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_READ)
        assert deps.company_data is not None
        return deps.company_data.store.list_candidates(principal.tenant_id)

    @app.post("/api/v1/company-data/candidates/{candidate_id}/review")
    def review_candidate(candidate_id: str, payload: ReviewRequest, request: Request,
                         credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.EVIDENCE_REVIEW)
        if "reviewer" not in principal.roles and Permission.ADMIN not in principal.permissions:
            raise APIError(403, "AUTHORIZATION_FAILED", "Reviewer role is required")
        assert deps.company_data is not None
        try:
            result = deps.company_data.review(
                principal.tenant_id, candidate_id, ReviewAction(payload.action),
                principal.principal_id, payload.note)
            _audit_company(deps, request, principal, "evidence.review", candidate_id)
            return result
        except IngestionError as exc:
            raise _ingestion_error(exc) from None

    @app.get("/api/v1/company-data/domain-packs", response_model=list[DomainPack])
    def domain_packs(credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_READ)
        assert deps.domain_packs is not None
        return deps.domain_packs.list(principal.tenant_id)

    @app.get("/api/v1/domains", response_model=list[DomainPack])
    def domains(credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_READ)
        assert deps.domain_packs is not None
        return deps.domain_packs.list(principal.tenant_id)

    @app.get("/api/v1/domains/{domain_id}", response_model=DomainPack)
    def domain_detail(domain_id: str, version: str | None = None,
                      credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_READ)
        assert deps.domain_packs is not None
        pack = (deps.domain_packs.get_version(principal.tenant_id, domain_id, version)
                if version else deps.domain_packs.get(principal.tenant_id, domain_id))
        if pack is None:
            raise APIError(404, "DOMAIN_NOT_FOUND", "Domain unavailable in tenant scope")
        return pack

    @app.post("/api/v1/domains/validate")
    def validate_domain(payload: DomainPack, credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOMAIN_PACK_MANAGE)
        assert deps.domain_packs is not None
        try:
            checked = deps.domain_packs.validate(principal.tenant_id, payload)
        except ValueError as exc:
            raise APIError(422, "DOMAIN_VALIDATION_FAILED", str(exc)) from None
        return {"valid": True, "pack": checked.model_dump(mode="json"),
                "immutable_version_id": checked.immutable_version_id,
                "findings": ["Schema, mathematical, tool and tenant validation passed."]}

    def persist_domain_draft(payload: DomainPack, principal):
        if payload.status not in {DomainPackStatus.DRAFT, DomainPackStatus.VALIDATED}:
            raise APIError(422, "INVALID_DOMAIN_STATUS",
                           "New domain versions must enter as draft or validated")
        if payload.approved_by or (payload.governance and (
                payload.governance.reviewer or payload.governance.approved_at)):
            raise APIError(422, "MODEL_APPROVAL_REQUIRED",
                           "Reviewer metadata is assigned by the protected lifecycle endpoint")
        assert deps.domain_packs is not None
        existing = deps.domain_packs.get_version(
            principal.tenant_id, payload.domain_id, payload.model_version)
        if existing and existing.status not in {DomainPackStatus.DRAFT, DomainPackStatus.VALIDATED}:
            raise APIError(422, "IMMUTABLE_DOMAIN_VERSION",
                           "A reviewed version cannot be replaced by an uploaded draft")
        try:
            checked = deps.domain_packs.validate(principal.tenant_id, payload)
            return deps.domain_packs.save(principal.tenant_id, checked)
        except ValueError as exc:
            raise APIError(422, "DOMAIN_VALIDATION_FAILED", str(exc)) from None

    @app.post("/api/v1/domains", response_model=DomainPack)
    def create_domain(payload: DomainPack, request: Request,
                      credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOMAIN_PACK_MANAGE)
        result = persist_domain_draft(payload, principal)
        _audit_company(deps, request, principal, "domain.create",
                       f"{result.domain_id}:{result.model_version}")
        return result

    @app.post("/api/v1/domains/{domain_id}/{model_version}/lifecycle",
              response_model=DomainPack)
    def domain_lifecycle(domain_id: str, model_version: str,
                         payload: DomainLifecycleRequest, request: Request,
                         credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        assert deps.domain_packs is not None
        try:
            if payload.action == "SUBMIT":
                _require(principal, Permission.DOMAIN_PACK_MANAGE)
                result = deps.domain_packs.submit_for_review(
                    principal.tenant_id, domain_id, model_version)
            else:
                _require(principal, Permission.MODEL_APPROVE)
                if "reviewer" not in principal.roles and Permission.ADMIN not in principal.permissions:
                    raise APIError(403, "AUTHORIZATION_FAILED", "Reviewer role is required")
                if payload.action == "APPROVE":
                    result = deps.domain_packs.approve(
                        principal.tenant_id, domain_id, model_version, principal.principal_id)
                elif payload.action == "REJECT":
                    result = deps.domain_packs.reject(principal.tenant_id, domain_id, model_version)
                elif payload.action == "ACTIVATE":
                    result = deps.domain_packs.activate(principal.tenant_id, domain_id, model_version)
                elif payload.action == "RETIRE":
                    result = deps.domain_packs.retire(
                        principal.tenant_id, domain_id, model_version,
                        payload.reason or "retired by authorized reviewer")
                else:
                    result = deps.domain_packs.require_revalidation(
                        principal.tenant_id, domain_id, model_version,
                        payload.reason or "source or model revalidation requested")
        except ValueError as exc:
            raise APIError(422, "DOMAIN_LIFECYCLE_REJECTED", str(exc)) from None
        _audit_company(deps, request, principal, f"domain.{payload.action.lower()}",
                       f"{domain_id}:{model_version}")
        return result

    @app.post("/api/v1/domains/{domain_id}/investigate")
    def investigate_domain(domain_id: str, payload: DomainInvestigationRequest,
                           request: Request, credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.INVESTIGATION_EXECUTE)
        if deps.domain_runtime is None:
            raise APIError(503, "NOT_READY", "Domain runtime is unavailable")
        try:
            result = deps.domain_runtime.investigate(
                principal.tenant_id, domain_id, payload.question, version=payload.version)
        except KeyError:
            raise APIError(404, "DOMAIN_NOT_FOUND", "Domain unavailable in tenant scope") from None
        except ValueError as exc:
            raise APIError(422, "DOMAIN_INVESTIGATION_REJECTED", str(exc)) from None
        if isinstance(result, dict):
            _audit_company(deps, request, principal, "domain.investigate",
                           f"{domain_id}:{result.get('domain_version', payload.version or 'pinned')}")
            return result
        if not hasattr(result, "model_dump"):
            raise APIError(422, "PROBABILISTIC_WORKFLOW_REQUIRED",
                           "Use the protected LangGraph investigation endpoint for probabilistic domains")
        _audit_company(deps, request, principal, "domain.investigate",
                       f"{domain_id}:{result.domain_version}")
        return result.model_dump(mode="json")

    @app.post("/api/v1/company-data/domain-packs", response_model=DomainPack)
    def save_domain_pack(payload: DomainPack, request: Request,
                         credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOMAIN_PACK_MANAGE)
        result = persist_domain_draft(payload, principal)
        _audit_company(deps, request, principal, "domain-pack.save", payload.domain_id)
        return result

    @app.get("/api/v1/pilot/status")
    def pilot_status(credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.EVALUATION_READ)
        assert deps.domain_packs is not None
        packs = deps.domain_packs.list(principal.tenant_id)
        return {
            "real_world_validation_status": "PENDING",
            "reason": "No authorized independently labeled organizational dataset is bundled.",
            "model_versions": [pack.model_dump(mode="json") for pack in packs],
        }

    @app.get("/api/v1/olist/status")
    def olist_status(credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_READ)
        if deps.olist is None:
            raise APIError(503, "OLIST_NOT_CONFIGURED", "Set SENTINEL_OLIST_DATA_PATH to the validated ZIP or directory")
        overview=deps.olist.overview(principal.tenant_id)
        versions=[pack.model_version for pack in deps.domain_packs.versions(
            principal.tenant_id,"olist_delivery_risk")] if deps.domain_packs else []
        return {**overview,"license":"CC BY-NC-SA 4.0","available_model_versions":versions}

    @app.post("/api/v1/olist/import")
    async def olist_import(payload: OlistImportRequest, request: Request,
                           credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.DOCUMENT_UPLOAD)
        if "reviewer" not in principal.roles and Permission.ADMIN not in principal.permissions:
            raise APIError(403, "REVIEWER_REQUIRED", "Controlled Olist batch publication requires a reviewer")
        if deps.olist is None: raise APIError(503, "OLIST_NOT_CONFIGURED", "Olist dataset is unavailable")
        try:
            result = await run_in_threadpool(deps.olist.import_orders, principal,
                limit=payload.limit, offset=payload.offset,
                expected_archive_sha256=payload.expected_archive_sha256,review_action=payload.review_action)
        except ValueError as exc:
            raise APIError(422,"OLIST_IMPORT_REJECTED",str(exc)) from None
        _audit_company(deps, request, principal, "olist.import", deps.olist.dataset_version)
        return asdict(result)

    @app.get("/api/v1/olist/import-preview")
    def olist_import_preview(limit: int=100, offset: int=0, credential: str = Depends(_credential)):
        principal=_principal(deps,credential); _require(principal,Permission.DOCUMENT_UPLOAD)
        if "reviewer" not in principal.roles and Permission.ADMIN not in principal.permissions:
            raise APIError(403,"REVIEWER_REQUIRED","Batch preview requires a reviewer")
        if deps.olist is None: raise APIError(503,"OLIST_NOT_CONFIGURED","Olist dataset is unavailable")
        try: return deps.olist.preview_orders(principal,limit=limit,offset=offset)
        except ValueError as exc: raise APIError(422,"INVALID_BATCH",str(exc)) from None

    @app.get("/api/v1/olist/import-status")
    def olist_import_status(limit: int=100, offset: int=0, credential: str = Depends(_credential)):
        principal=_principal(deps,credential); _require(principal,Permission.DOCUMENT_UPLOAD)
        if "reviewer" not in principal.roles and Permission.ADMIN not in principal.permissions:
            raise APIError(403,"REVIEWER_REQUIRED","Batch status requires a reviewer")
        if deps.olist is None: raise APIError(503,"OLIST_NOT_CONFIGURED","Olist dataset is unavailable")
        try: return deps.olist.batch_status(principal,limit=limit,offset=offset)
        except ValueError as exc: raise APIError(422,"INVALID_BATCH",str(exc)) from None

    @app.get("/api/v1/olist/orders/{order_id}")
    def olist_order(order_id: str, credential: str = Depends(_credential)):
        principal = _principal(deps, credential); _require(principal, Permission.EVIDENCE_READ)
        if deps.olist is None: raise APIError(503, "OLIST_NOT_CONFIGURED", "Olist dataset is unavailable")
        try: return deps.olist.lookup(principal.tenant_id, order_id)
        except KeyError: raise APIError(404, "ORDER_NOT_FOUND", "Order unavailable in tenant scope") from None

    @app.get("/api/v1/olist/orders/{order_id}/source")
    def olist_order_source(order_id: str, credential: str = Depends(_credential)):
        principal = _principal(deps, credential); _require(principal, Permission.PROVENANCE_READ)
        if deps.olist is None: raise APIError(503, "OLIST_NOT_CONFIGURED", "Olist dataset is unavailable")
        try: return deps.olist.source_order_row(principal.tenant_id, order_id)
        except KeyError: raise APIError(404, "ORDER_NOT_FOUND", "Order unavailable in tenant scope") from None

    @app.post("/api/v1/olist/predictions")
    def olist_prediction(payload: OlistPredictionRequest, credential: str = Depends(_credential)):
        principal = _principal(deps, credential); _require(principal, Permission.INVESTIGATION_EXECUTE)
        if deps.olist is None: raise APIError(503, "OLIST_NOT_CONFIGURED", "Olist dataset is unavailable")
        try: return deps.olist.prospective_snapshot(principal.tenant_id,payload.order_id,Snapshot(payload.decision_time))
        except KeyError: raise APIError(404, "ORDER_NOT_FOUND", "Order unavailable in tenant scope") from None

    @app.post("/api/v1/pilot/calibrations")
    def calibrate_pilot(payload: PilotCalibrationRequest, request: Request,
                        credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.CALIBRATION_RUN)
        if payload.dataset.tenant_id != principal.tenant_id:
            raise APIError(403, "AUTHORIZATION_FAILED", "Resource unavailable or access denied")
        report = validate_dataset(payload.dataset)
        if not report.valid:
            raise APIError(422, "INVALID_PILOT_DATASET", "Pilot dataset validation failed")
        manifest = chronological_group_split(payload.dataset)
        estimate = estimate_categorical_model(
            payload.dataset, manifest,
            minimum_state_samples=payload.minimum_state_samples,
            minimum_action_state_samples=payload.minimum_action_state_samples)
        if estimate.status != "EMPIRICALLY_ESTIMATED":
            raise APIError(422, "INSUFFICIENT_CALIBRATION_DATA",
                           "Calibration sample coverage is insufficient")
        labels = {case.case_id: case.ground_truth_label for case in payload.dataset.cases
                  if manifest.assignments[case.case_id] == PilotSplit.TEST
                  and case.ground_truth_label and case.independent_ground_truth
                  and case.label_status in {LabelStatus.APPROVED, LabelStatus.ADJUDICATED}}
        predictions = replay_logged_policy(
            payload.dataset, manifest, estimate,
            ReplayPolicy("logged_holdout", True, payload.answer_threshold),
            split=PilotSplit.TEST)
        metrics = evaluate_predictions(predictions, labels)
        candidate = build_candidate_domain_pack(
            estimate=estimate, domain_id=payload.dataset.domain_id, name=payload.name,
            claim_type=payload.claim_type, model_version=payload.model_version,
            relation_hypotheses=payload.relation_hypotheses,
            action_costs=payload.action_costs,
            answer_threshold=payload.answer_threshold,
            minimum_independent_sources=payload.minimum_independent_sources,
            holdout_metrics=metrics,
            limitations=["Approval is population-specific and requires human review."])
        assert deps.domain_packs is not None
        deps.domain_packs.save(principal.tenant_id, candidate)
        _audit_company(deps, request, principal, "calibration.run",
                       f"{candidate.domain_id}:{candidate.model_version}")
        return {
            "dataset_validation": report.model_dump(mode="json"),
            "estimate": estimate.model_dump(mode="json"),
            "heldout_metrics": metrics.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "activated": False,
        }

    @app.post("/api/v1/pilot/models/{domain_id}/{model_version}/review")
    def review_model(domain_id: str, model_version: str, payload: ModelReviewRequest,
                     request: Request, credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        _require(principal, Permission.MODEL_APPROVE)
        if "reviewer" not in principal.roles and Permission.ADMIN not in principal.permissions:
            raise APIError(403, "AUTHORIZATION_FAILED", "Reviewer role is required")
        assert deps.domain_packs is not None
        try:
            if payload.action == "APPROVE":
                result = deps.domain_packs.approve(
                    principal.tenant_id, domain_id, model_version, principal.principal_id)
            elif payload.action == "REJECT":
                result = deps.domain_packs.reject(principal.tenant_id, domain_id, model_version)
            else:
                result = deps.domain_packs.rollback(principal.tenant_id, domain_id, model_version)
        except ValueError as exc:
            raise APIError(422, "MODEL_REVIEW_REJECTED", str(exc)) from None
        _audit_company(deps, request, principal, f"model.{payload.action.lower()}",
                       f"{domain_id}:{model_version}")
        return result

    @app.get("/api/v1/investigations/{investigation_id}", response_model=InvestigationAPIResponse)
    async def investigation(investigation_id: str, request: Request,
                            credential: str = Depends(_credential)):
        try:
            response = await run_in_threadpool(
                deps.service.read_trace, credential, investigation_id,
                correlation_id=request.state.correlation_id)
        except SecurityBoundaryError as exc:
            raise _translate_security_error(exc) from None
        return _public_response(response, request.state.correlation_id, deps.provider_name)

    @app.get("/api/v1/investigations/{investigation_id}/trace", response_model=TraceResponse)
    async def trace(investigation_id: str, request: Request,
                    credential: str = Depends(_credential)):
        try:
            response = await run_in_threadpool(
                deps.service.read_trace, credential, investigation_id,
                correlation_id=request.state.correlation_id)
        except SecurityBoundaryError as exc:
            raise _translate_security_error(exc) from None
        return _trace_response(response)

    @app.get("/api/v1/evidence/{evidence_id}", response_model=ProvenanceRecord)
    async def evidence(evidence_id: str, request: Request,
                       credential: str = Depends(_credential)):
        try:
            return await run_in_threadpool(
                deps.service.read_evidence, credential, evidence_id,
                correlation_id=request.state.correlation_id)
        except SecurityBoundaryError as exc:
            raise _translate_security_error(exc) from None

    @app.get("/api/v1/provenance/{fact_id}", response_model=ProvenanceChain)
    async def provenance(fact_id: str, request: Request,
                         credential: str = Depends(_credential)):
        try:
            return await run_in_threadpool(
                deps.service.read_provenance, credential, fact_id,
                correlation_id=request.state.correlation_id)
        except SecurityBoundaryError as exc:
            raise _translate_security_error(exc) from None

    @app.get("/api/v1/metrics/summary", response_model=MetricsResponse)
    def metrics(credential: str = Depends(_credential)):
        principal = _principal(deps, credential)
        try:
            Authorizer().require(principal, Permission.INVESTIGATION_EXECUTE)
        except AuthorizationError as exc:
            raise _translate_security_error(exc) from None
        return MetricsResponse(tenant_id=principal.tenant_id,
                               metrics=deps.metrics.snapshot(principal.tenant_id))

    @app.get("/api/v1/audit")
    def audit(credential: str = Depends(_credential)):
        try:
            return [asdict(item) for item in deps.service.read_audit_events(credential)]
        except SecurityBoundaryError as exc:
            raise _translate_security_error(exc) from None

    web_root = Path(__file__).resolve().parents[1] / "web"
    app.mount("/assets", StaticFiles(directory=web_root), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(web_root / "index.html")

    return app


app = create_app()
