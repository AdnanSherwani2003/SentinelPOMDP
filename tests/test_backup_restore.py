import json

import pytest

from sentinel_pomdp.operations.backup import (
    BackupBuilder, BackupError, restore_directory_archive, verify_manifest,
)


def test_document_backup_manifest_and_disposable_restore(tmp_path):
    documents = tmp_path / "documents"
    (documents / "tenant-a" / "candidates").mkdir(parents=True)
    (documents / "tenant-a" / "source.bin").write_bytes(b"approved source bytes")
    (documents / "tenant-a" / "candidates" / "review.json").write_text(
        '{"status":"APPROVED","reviewed_by":"reviewer-a"}', encoding="utf-8")
    builder = BackupBuilder(
        tmp_path / "backups", label="disposable-rehearsal",
        schema_versions={"operations": "1", "graph": "implementation-18"})
    builder.add_directory("documents", "directory", documents)
    builder.add_public_configuration({"backend": "neo4j", "provider": "fake"})
    manifest = builder.finish()
    verified = verify_manifest(manifest)
    assert verified["consistency_boundary"] == "worker-quiesced"

    restored = restore_directory_archive(manifest, "documents", tmp_path / "restore")
    assert (restored / "tenant-a" / "source.bin").read_bytes() == b"approved source bytes"
    review = json.loads((restored / "tenant-a" / "candidates" / "review.json").read_text())
    assert review["status"] == "APPROVED"
    assert not (restored / "tenant-b").exists()


def test_backup_detects_tampering_and_rejects_secret_configuration(tmp_path):
    source = tmp_path / "operations.dump"
    source.write_bytes(b"database snapshot")
    builder = BackupBuilder(tmp_path / "backups", label="test", schema_versions={"operations": "1"})
    artifact = builder.add_file("operations", "postgres-custom-dump", source)
    manifest = builder.finish()
    (manifest.parent / artifact.filename).write_bytes(b"tampered")
    with pytest.raises(BackupError, match="checksum"):
        verify_manifest(manifest)
    with pytest.raises(BackupError, match="credential"):
        builder.add_public_configuration({"api_key": "must-not-be-backed-up"})
