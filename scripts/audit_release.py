"""Read-only release inventory and redacted working-tree/Git-history secret scan.

Writes only generated reports. Does not stage, delete, or rewrite Git objects.
This is a bounded pattern/known-current-secret scan, not proof that no secret exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
PATTERNS = {
    "openai_key_shape": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "groq_key_shape": re.compile(rb"\bgsk_[A-Za-z0-9_-]{20,}\b"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def hits(content: bytes) -> list[str]:
    found = [label for label, pattern in PATTERNS.items() if pattern.search(content)]
    for name in ("GROQ_API_KEY", "OPENAI_API_KEY", "SENTINEL_API_KEY", "NEO4J_PASSWORD", "POSTGRES_PASSWORD"):
        value = os.getenv(name, "")
        if len(value) >= 20 and not value.startswith("<") and value.encode() in content:
            found.append("configured_secret_value:" + name)
    return found


def local_only(name: str) -> bool:
    parts = Path(name).parts
    return (any(part in SKIP_DIRS or part.endswith(".egg-info") for part in parts)
            or name.startswith(("data/", "private-backups/"))
            or "/browser_store" in name or "/quarantine" in name
            or name.endswith((".pyc", ".db", ".db-wal", ".db-shm", ".dump", ".backup", ".zip"))
            or (Path(name).name.endswith(".env") and not name.endswith(".example")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/implementation20/local/release-audit")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tracked = git("ls-files", "-z").decode().split("\0")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    tracked = [p for p in tracked if p]
    untracked = [p for p in untracked if p]
    findings, inventory = [], []
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in files:
            path = Path(directory) / filename
            name = path.relative_to(ROOT).as_posix()
            size = path.stat().st_size
            inventory.append({"path": name, "bytes": size, "tracked": name in tracked,
                              "local_only": local_only(name)})
            if size <= 10_000_000 and path.suffix.lower() not in {".zip", ".db", ".png", ".pyc", ".whl"}:
                for kind in hits(path.read_bytes()):
                    findings.append({"scope": "working_tree", "path": name, "kind": kind})
    history_blobs = 0
    for line in git("rev-list", "--objects", "--all").decode().splitlines():
        object_id, _, name = line.partition(" ")
        if git("cat-file", "-t", object_id).strip() != b"blob":
            continue
        history_blobs += 1
        for kind in hits(git("cat-file", "blob", object_id)):
            findings.append({"scope": "git_history", "object": object_id, "path": name, "kind": kind})
    manifest = {
        "branch": git("branch", "--show-current").decode().strip(),
        "tracked_count": len(tracked), "untracked_count": len(untracked),
        "history_blobs_scanned": history_blobs,
        "credential_findings_redacted": findings,
        "tracked_local_only": [p for p in tracked if local_only(p)],
        "files": sorted(inventory, key=lambda item: item["path"]),
        "scope": "Current files (<=10 MB for text scan) and all reachable Git blobs; no secret values emitted",
    }
    (args.output_dir / "repository_inventory.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    safe = [p for p in tracked + untracked if not local_only(p) and not p.startswith("reports/")]
    review = [p for p in tracked + untracked if not local_only(p) and p.startswith("reports/")]
    staging = {"proposed_include": sorted(set(safe)), "manual_review_reports": sorted(set(review)),
        "proposed_untrack_preserve_local": manifest["tracked_local_only"],
        "never_stage": [".env and private environment files", "data/", "raw Olist CSV/ZIP",
                        "database files/dumps", "browser stores", "quarantined/temp fixtures"],
        "action_taken": "None; this is a proposal, not a staging operation"}
    (args.output_dir / "proposed_staging_manifest.json").write_text(json.dumps(staging, indent=2), encoding="utf-8")
    archive = ROOT / "archive (2).zip"
    print(json.dumps({"tracked": len(tracked), "untracked": len(untracked),
        "history_blobs_scanned": history_blobs, "findings": findings,
        "tracked_generated_files": len(manifest["tracked_local_only"]),
        "olist_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest() if archive.exists() else None}))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
