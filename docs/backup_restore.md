# Backup and restore runbook

These steps require a maintenance window: stop API writes and workers, wait for
active jobs to reach a safe boundary, and record the boundary in the manifest.
Never copy a live PostgreSQL or Neo4j data directory.

## Backup set

The recovery set contains:

- a PostgreSQL custom-format dump from `pg_dump` (jobs, audit, and LangGraph tables);
- a Neo4j dump produced by `neo4j-admin database dump` while Community Edition is stopped;
- a quiesced document-store archive (bytes, metadata, candidates, review status, domain packs);
- an allow-listed, non-secret configuration summary; and
- `sentinel-backup-v1` manifest with timestamp, schema/model versions, sizes, and SHA-256 values.

`BackupBuilder` refuses credential-like configuration keys. Store backup media with
the same or stronger access controls and retention limits as source evidence.

## PowerShell outline

Set private variables in the current shell or secret manager. Do not place their
values in source files.

```powershell
# 1. Quiesce the worker and API writes.
docker compose -f infra/deployment.compose.yaml stop worker api

# 2. Make a transaction-consistent PostgreSQL dump.
docker compose -f infra/deployment.compose.yaml exec -T postgres `
  pg_dump -U sentinel -d sentinel -Fc -f /tmp/sentinel-operations.dump
docker compose -f infra/deployment.compose.yaml cp `
  postgres:/tmp/sentinel-operations.dump .\private-backups\sentinel-operations.dump

# 3. Neo4j Community dump requires the database to be offline.
docker compose -f infra/deployment.compose.yaml stop neo4j
docker compose -f infra/deployment.compose.yaml run --rm `
  -v "${PWD}\private-backups:/backups" neo4j `
  neo4j-admin database dump neo4j --to-path=/backups --overwrite-destination=true

# 4. Archive the quiesced document volume through a controlled helper container,
# then use BackupBuilder to copy the dumps/archive and create checksums + manifest.
```

Restart only after all commands succeed. A backup is incomplete until
`verify_manifest()` succeeds and the database dumps are present.

## Restore (disposable rehearsal first)

1. Create new empty PostgreSQL, Neo4j, and document storage. Never point at an
   existing volume.
2. Run `verify_manifest()` before extracting anything.
3. Restore PostgreSQL with `createdb` and `pg_restore`.
4. With fresh Neo4j stopped, run
   `neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true`.
5. Restore the document archive with `restore_directory_archive()`; it rejects path traversal.
6. Start the disposable services and verify tenant counts, document hashes, review
   status, graph relationships, domain/model versions, and deterministic outcomes.
7. Record restore time and verification output. Restore production only with a
   reviewed change plan and explicit authorization.

## Implementation 20 integrated rehearsal

The newer integrated rehearsal is summarized in
[public release validation](release_validation.md). Original local operational
exports remain private. It restored 57 graph
nodes, 56 relationships, one PostgreSQL job, three audit rows, ten checkpoint rows,
seven byte-identical document files, one review decision and an active domain
version into new synthetic storage. Research volumes were never mounted.
The restored storage is retained; no existing database or volume was overwritten.
The procedure requires quiescing writers and offline Neo4j Community dumping.

## Historical Implementation 18 rehearsal (2026-10-20 report date)

A disposable Neo4j 5.26 Community source was seeded with an approved document,
approved fact, tenant-scoped `SUPPORTS` relationship, and `test-v1` model marker.
An offline `neo4j-admin dump` was loaded into a fresh volume; all fields and one
relationship were recovered and Tenant B returned zero records. The dump SHA-256
was `1a592f3651f62e10459908ed1a1bb9594a137841df6ff5d8bc513611c4c8e949`.

A PostgreSQL 17 custom dump was restored into a fresh disposable database. The
known job returned `COMPLETED|ABSTAIN|test-v1`. Document-manifest tests restored
bytes and approval metadata, verified checksums, rejected tampering, and rejected
credential-like configuration. Existing Olist volumes were never mounted.
