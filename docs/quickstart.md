# Local quickstart

Use the reviewed release candidate working tree. The remote repository will contain
it only after the owner authorizes a commit and push. Tested environment: Windows,
PowerShell, Python 3.13, uv and Docker Desktop with Linux containers. Locked package
versions are in uv.lock. Other platforms are not claimed as verified.

```powershell
uv sync --frozen --group dev
$env:RUN_LIVE_GROQ_TESTS = '0'
$env:RUN_LIVE_LLM_TESTS = '0'
uv run pytest -q -rs
powershell -NoProfile -File scripts/start_demo.ps1 -Project sentinel-demo-local -Port 18082
```

The script creates a separate Compose project, new named demo volumes and a private
ignored file at data/demo/sentinel-demo-local.env. It never resets existing data.
It starts one API process, PostgreSQL, Neo4j and two workers, then explicitly seeds
synthetic fixtures in a tenant_demo_ tenant. It is repeatable and retains its local
credentials. Do not reuse a demo project as a real business tenant.

To enter the local key without printing it, use this optional clipboard step, paste
into the localhost console, then clear the clipboard yourself:

```powershell
$demo = Get-Content data/demo/sentinel-demo-local.env -Raw | ConvertFrom-StringData
Set-Clipboard -Value $demo.SENTINEL_API_KEY
```

Open http://127.0.0.1:18082. Authenticate, ask “Was Supplier A's shipment late?”,
inspect the belief chart and source evidence. Ask the causal question to observe
abstention. Domain Management supports INV-1001 / PO-2001 matching. Operations
shows durable jobs and worker health.

```powershell
uv run python scripts/verify_demo.py --env-file data/demo/sentinel-demo-local.env
docker compose -p sentinel-demo-local --env-file data/demo/sentinel-demo-local.env -f infra/deployment.compose.yaml stop
```

Stop preserves all volumes. Do not use volume-removing cleanup on existing projects.
No external LLM or Olist archive is needed. Neo4j and PostgreSQL have no published
ports in this profile. Port 18082 must be free. Memory limits are 512 MiB for the
API, PostgreSQL and each worker and 1 GiB for Neo4j; observed usage and test hardware
are in the I20 performance report. These limits are not minimum hardware guarantees.

Node.js is optional development tooling, not an application requirement. To check
the architecture diagrams from locked dependencies, follow
[diagram verification](diagram_verification.md). For installed-wheel/sdist startup
checks and recorded results, see [release validation](release_validation.md).

An optional real Olist demonstration requires your separately obtained archive and
already authorized reviewed graph. It is not part of the synthetic bootstrap. Never
redistribute the raw archive or import more research records just to run the demo.

Troubleshooting: NOT_READY means a dependency/configuration failure; inspect health
without printing credentials. A 401 indicates the wrong local key. Model approval
requires reviewer authorization. A 403 evidence response is a denial, not a missing
authentication bypass. Docker worker heartbeat is shown in Operations; workers do
not serve HTTP. Neo4j failure never silently falls back to memory in the API.
