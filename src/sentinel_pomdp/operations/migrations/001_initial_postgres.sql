CREATE TABLE IF NOT EXISTS operation_schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS operation_jobs (
    job_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    correlation_id TEXT NOT NULL,
    idempotency_key TEXT,
    input_fingerprint TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    progress_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB,
    error_code TEXT,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    fencing_token BIGINT NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 2,
    replay_safe BOOLEAN NOT NULL DEFAULT FALSE,
    cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
    not_before TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_operation_idempotency
ON operation_jobs(tenant_id, principal_id, operation_type, idempotency_key)
WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_operation_claim ON operation_jobs(state, not_before, created_at);
CREATE INDEX IF NOT EXISTS ix_operation_tenant ON operation_jobs(tenant_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS operation_journal (
    job_id UUID NOT NULL REFERENCES operation_jobs(job_id),
    step_key TEXT NOT NULL,
    state TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    result_json JSONB,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(job_id, step_key)
);
CREATE TABLE IF NOT EXISTS operation_audit (
    event_id TEXT PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    tenant_id TEXT,
    principal_id TEXT,
    resource_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_operation_audit_tenant ON operation_audit(tenant_id, occurred_at DESC);
CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    workflow_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    phase TEXT NOT NULL,
    state_json JSONB NOT NULL,
    state_fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY(workflow_id, sequence)
);
CREATE INDEX IF NOT EXISTS ix_checkpoint_scope ON workflow_checkpoints(tenant_id, workflow_id, sequence DESC);
