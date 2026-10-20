# Controlled deployment runbook

Supported validation profile: one local API process, private Neo4j and PostgreSQL,
two separate durable workers, and a shared private document volume. Start with
scripts/start_demo.ps1 and docs/quickstart.md. The project name must start with
sentinel-demo- and the synthetic setup tenant with tenant_demo_. Other application
volumes are not mounted into the demo.

Compose publishes only 127.0.0.1:18082 by default. API/worker images run as UID 999.
Candidate startup requires Neo4j, PostgreSQL operations/checkpoints, explicit local
credentials and disabled development authentication. Source dependencies must be
ready before API/worker startup. The API has live/ready HTTP endpoints. Workers
have no HTTP server: /api/v1/operations/health checks their durable heartbeat.

Authentication and rate limits remain process-local. Do not scale API replicas or
override the documented command with multi-worker flags. Background worker leases
and PostgreSQL fencing support multiple workers; this does not imply API identity
state is shared. The supplied settings reject known concurrency environment values
above one. Public exposure, TLS termination and managed identity are outside the
validated profile.

Stop with the exact Compose project and its private env file; use stop, not volume
deletion. SIGTERM tells workers to stop polling; cancellation is cooperative at
safe boundaries and cannot interrupt an atomic database commit. A long synchronous
request can outlive the HTTP timeout, so do not blindly repeat external processing.

For backups, quiesce writers and workers. Use pg_dump, offline Community Neo4j dump,
document bytes/metadata and a verified manifest. Rehearse into fresh isolated
storage; never overwrite the research tenant. I20's executable controlled rehearsal:

```powershell
uv run python scripts/verify_demo.py --env-file data/demo/sentinel-demo-local.env
uv run python scripts/rehearse_backup.py --project sentinel-demo-local
```

The rehearsal preserves its local dumps and disposable restore volume/database for
review. It never mounts research volumes. Treat backup data like source evidence;
keep data/ and all dumps outside Git. See backup_restore.md for maintenance and
consistency assumptions. Continuous external alert delivery and production HA have
not been implemented/verified.
