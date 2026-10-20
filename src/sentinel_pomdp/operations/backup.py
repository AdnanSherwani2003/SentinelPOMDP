"""Checksum manifests for quiesced document and supported database backups."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tarfile
from typing import Any
from uuid import uuid4


class BackupError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


@dataclass(frozen=True)
class BackupArtifact:
    name: str
    kind: str
    filename: str
    sha256: str
    byte_size: int


class BackupBuilder:
    """Build a manifest around snapshots made at an explicit quiesced boundary."""

    def __init__(self, parent: str | Path, *, label: str,
                 schema_versions: dict[str, str]) -> None:
        parent_path = Path(parent).resolve()
        parent_path.mkdir(parents=True, exist_ok=True)
        self.backup_id = f"backup-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
        self.root = parent_path / self.backup_id
        self.root.mkdir(mode=0o700)
        self.label = label
        self.schema_versions = dict(schema_versions)
        self.artifacts: list[BackupArtifact] = []

    def add_file(self, name: str, kind: str, source: str | Path) -> BackupArtifact:
        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise BackupError(f"backup source is not a file: {name}")
        suffix = "".join(source_path.suffixes)
        destination = self.root / f"{name}{suffix}"
        if destination.exists():
            raise BackupError(f"duplicate backup artifact: {name}")
        shutil.copy2(source_path, destination)
        return self._record(name, kind, destination)

    def add_directory(self, name: str, kind: str, source: str | Path) -> BackupArtifact:
        source_path = Path(source).resolve()
        if not source_path.is_dir():
            raise BackupError(f"backup source is not a directory: {name}")
        destination = self.root / f"{name}.tar.gz"
        with tarfile.open(destination, "w:gz") as archive:
            archive.add(source_path, arcname=name, recursive=True)
        return self._record(name, kind, destination)

    def add_public_configuration(self, values: dict[str, Any]) -> BackupArtifact:
        forbidden = ("password", "secret", "token", "api_key", "connection", "credential")
        if any(any(term in str(key).lower() for term in forbidden) for key in values):
            raise BackupError("configuration contains a credential-like key")
        destination = self.root / "configuration.json"
        destination.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
        return self._record("configuration", "configuration", destination)

    def _record(self, name: str, kind: str, destination: Path) -> BackupArtifact:
        artifact = BackupArtifact(name, kind, destination.name, _digest(destination), destination.stat().st_size)
        self.artifacts.append(artifact)
        return artifact

    def finish(self) -> Path:
        manifest = {
            "format": "sentinel-backup-v1", "backup_id": self.backup_id,
            "created_at": datetime.now(timezone.utc).isoformat(), "label": self.label,
            "consistency_boundary": "worker-quiesced",
            "schema_versions": self.schema_versions,
            "artifacts": [artifact.__dict__ for artifact in self.artifacts],
        }
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return path


def verify_manifest(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format") != "sentinel-backup-v1":
        raise BackupError("unsupported backup manifest")
    for artifact in manifest.get("artifacts", []):
        candidate = (path.parent / artifact["filename"]).resolve()
        if candidate.parent != path.parent or not candidate.is_file():
            raise BackupError("backup artifact is missing or outside its backup directory")
        if _digest(candidate) != artifact["sha256"]:
            raise BackupError(f"checksum mismatch: {artifact['name']}")
    return manifest


def restore_directory_archive(manifest_path: str | Path, artifact_name: str,
                              destination_parent: str | Path) -> Path:
    manifest = verify_manifest(manifest_path)
    artifact = next((item for item in manifest["artifacts"] if item["name"] == artifact_name), None)
    if artifact is None or artifact["kind"] != "directory":
        raise BackupError("directory artifact is unavailable")
    destination = Path(destination_parent).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = Path(manifest_path).resolve().parent / artifact["filename"]
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if destination not in target.parents and target != destination:
                raise BackupError("unsafe archive member")
        archive.extractall(destination, members=members, filter="data")
    return destination / artifact_name
