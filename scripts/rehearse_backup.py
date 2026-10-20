"""Quiesced restore rehearsal confined to an explicitly named synthetic demo."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from time import sleep
from uuid import uuid4

from sentinel_pomdp.operations.backup import BackupBuilder, restore_directory_archive, verify_manifest


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Controlled backup command failed ({args[0]}, code {result.returncode}); arguments withheld")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    if not args.project.startswith("sentinel-demo-") or not all(c.isalnum() or c == "-" for c in args.project):
        raise SystemExit("Only an explicitly isolated sentinel-demo- project is allowed")
    config = dict(line.split("=", 1) for line in Path(f"data/demo/{args.project}.env").read_text().splitlines() if "=" in line)
    assert config["SENTINEL_TENANT_ID"].startswith("tenant_demo_")
    neo, pg, api = [f"{args.project}-{service}-1" for service in ("neo4j", "postgres", "api")]
    workers = [f"{args.project}-worker-{i}" for i in (1, 2)]
    run_id = uuid4().hex[:12]
    root = Path("data/implementation20/backups") / run_id
    root.mkdir(parents=True)
    root = root.resolve()
    restored_volume = "sentinel-demo-restore-" + run_id
    restored_container = restored_volume
    graph_query = "MATCH (n) RETURN count(n) AS nodes; MATCH ()-[r]->() RETURN count(r) AS relationships;"
    def graph_counts(container):
        return command("docker", "exec", container, "cypher-shell", "-u", "neo4j", "-p", config["NEO4J_PASSWORD"], "--format", "plain", graph_query)
    def pg_counts(database):
        query = "SELECT (SELECT count(*) FROM operation_jobs), (SELECT count(*) FROM operation_audit), (SELECT count(*) FROM checkpoints);"
        return command("docker", "exec", pg, "psql", "-U", "sentinel", "-d", database, "-At", "-c", query)
    before_graph = graph_counts(neo)
    before_pg = pg_counts("sentinel")
    command("docker", "stop", api, *workers)
    target_started = False
    try:
        command("docker", "exec", pg, "pg_dump", "-U", "sentinel", "-d", "sentinel", "-Fc", "-f", "/tmp/i20.dump")
        command("docker", "cp", f"{pg}:/tmp/i20.dump", str(root / "operations.dump"))
        command("docker", "cp", f"{api}:/app/data/company_documents", str(root / "documents"))
        command("docker", "stop", neo)
        command("docker", "run", "--rm", "--volumes-from", neo,
                "-v", f"{root}:/backups", "neo4j:5.26-community",
                "neo4j-admin", "database", "dump", "neo4j", "--to-path=/backups")
        builder = BackupBuilder(root / "manifest", label="I20 disposable synthetic rehearsal",
            schema_versions={"operations": "1", "domain": "1.0"})
        builder.add_file("operations", "postgres-custom-dump", root / "operations.dump")
        builder.add_file("graph", "neo4j-dump", root / "neo4j.dump")
        builder.add_directory("documents", "directory", root / "documents")
        manifest = builder.finish()
        verify_manifest(manifest)
        command("docker", "volume", "create", restored_volume)
        command("docker", "run", "--rm", "-v", f"{restored_volume}:/data",
                "-v", f"{root}:/backups", "neo4j:5.26-community",
                "neo4j-admin", "database", "load", "neo4j", "--from-path=/backups")
        command("docker", "run", "-d", "--rm", "--name", restored_container,
                "-v", f"{restored_volume}:/data", "-e", "NEO4J_AUTH=" + config["NEO4J_AUTH"], "neo4j:5.26-community")
        target_started = True
        for attempt in range(60):
            try:
                after_graph = graph_counts(restored_container)
                break
            except RuntimeError:
                sleep(1)
        else:
            raise RuntimeError("Disposable restored Neo4j did not become ready")
        assert before_graph == after_graph
        database = "sentinel_restore_" + run_id
        command("docker", "exec", pg, "createdb", "-U", "sentinel", database)
        command("docker", "exec", pg, "pg_restore", "-U", "sentinel", "-d", database, "/tmp/i20.dump")
        after_pg = pg_counts(database)
        assert before_pg == after_pg
        restored = restore_directory_archive(manifest, "documents", root / "restored")
        def digest_tree(folder):
            return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in folder.rglob("*") if p.is_file()}
        original = digest_tree(root / "documents")
        assert original == digest_tree(restored)
        metadata = [json.loads(p.read_text()) for p in restored.rglob("*.json")]
        approved = sum(item.get("status") == "APPROVED" for item in metadata)
        assert approved >= 1 and any(item.get("status") == "ACTIVE" for item in metadata)
        report = {"status": "PASS", "synthetic_only": True,
            "graph_counts_before_after": before_graph, "jobs_audit_checkpoints_before_after": before_pg,
            "document_files_restored": len(original), "approved_review_records_restored": approved,
            "active_domain_version_restored": True, "source_bytes_and_metadata_sha256_equal": True,
            "manifest_verified": True, "backup_directory_local_only": str(root),
            "retained_disposable_volume": restored_volume, "retained_disposable_postgres_database": database,
            "research_volumes_mounted": False, "neo4j_community_offline_dump": True}
        Path("reports/implementation20/backup_rehearsal.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
    finally:
        if target_started: command("docker", "stop", restored_container)
        command("docker", "start", neo)
        for _ in range(60):
            try:
                graph_counts(neo)
                break
            except RuntimeError:
                sleep(1)
        command("docker", "start", api, *workers)


if __name__ == "__main__":
    main()
