"""Single-instance persistent document metadata and byte storage."""
from __future__ import annotations

import json
import os
import tempfile
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Iterable

from .models import CompanyDocument, DatasetConfiguration, FactCandidate, NormalizedDocument


class LocalDocumentStore:
    """Tenant-partitioned local store; callers never receive filesystem paths."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        self._lock = RLock()

    @staticmethod
    def _tenant_key(tenant_id: str) -> str:
        return sha256(tenant_id.encode("utf-8")).hexdigest()[:32]

    def _tenant_root(self, tenant_id: str) -> Path:
        path = self.root / self._tenant_key(tenant_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def writable(self) -> bool:
        """Verify document storage with a short-lived file, without exposing paths."""
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, delete=True) as handle:
                handle.write(b"health")
                handle.flush()
            return True
        except OSError:
            return False

    def _path(self, tenant_id: str, category: str, identifier: str, suffix: str = ".json") -> Path:
        if not identifier or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.:" for char in identifier):
            raise ValueError("unsafe storage identifier")
        folder = self._tenant_root(tenant_id) / category
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{identifier}{suffix}"

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            handle.write(data)
            temporary = Path(handle.name)
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _put_model(self, tenant_id: str, category: str, identifier: str, model) -> None:
        path = self._path(tenant_id, category, identifier)
        self._atomic_write(path, model.model_dump_json(indent=2).encode("utf-8"))

    def _models(self, tenant_id: str, category: str, model_type) -> list:
        folder = self._tenant_root(tenant_id) / category
        if not folder.exists():
            return []
        result = []
        for path in sorted(folder.glob("*.json")):
            result.append(model_type.model_validate_json(path.read_text(encoding="utf-8")))
        return result

    def put_document(self, document: CompanyDocument, content: bytes, normalized: NormalizedDocument) -> None:
        with self._lock:
            self._put_model(document.tenant_id, "documents", document.document_id, document)
            self._put_model(document.tenant_id, "normalized", document.document_id, normalized)
            self._atomic_write(self._path(document.tenant_id, "content", document.document_id, ".bin"), content)

    def stage_upload(self, tenant_id: str, *, filename: str, content: bytes,
                     declared_media_type: str, dataset_id: str,
                     source_group: str | None = None) -> dict[str, str | int | None]:
        """Persist bytes before enqueueing; jobs carry only an opaque tenant-scoped reference."""
        digest = sha256(content).hexdigest()
        identity = sha256(
            f"{tenant_id}\0{dataset_id}\0{Path(filename).name}\0{source_group or ''}\0{digest}"
            .encode("utf-8")).hexdigest()[:32]
        upload_id = f"upload_{identity}"
        metadata = {
            "upload_id": upload_id, "filename": Path(filename).name,
            "declared_media_type": declared_media_type, "dataset_id": dataset_id,
            "source_group": source_group, "sha256": digest, "byte_size": len(content),
        }
        with self._lock:
            self._atomic_write(
                self._path(tenant_id, "staged", upload_id, ".bin"), content)
            self._atomic_write(
                self._path(tenant_id, "staged", upload_id, ".json"),
                json.dumps(metadata, sort_keys=True).encode("utf-8"))
        return metadata

    def get_staged_upload(self, tenant_id: str, upload_id: str) -> tuple[dict, bytes] | None:
        metadata_path = self._path(tenant_id, "staged", upload_id, ".json")
        content_path = self._path(tenant_id, "staged", upload_id, ".bin")
        if not metadata_path.exists() or not content_path.exists():
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        content = content_path.read_bytes()
        if sha256(content).hexdigest() != metadata.get("sha256"):
            raise ValueError("staged upload integrity check failed")
        return metadata, content

    def put_document_reference(self, document: CompanyDocument) -> None:
        """Register an immutable external source by hash without copying its bytes."""
        with self._lock:
            existing = self.get_document(document.tenant_id, document.document_id)
            if existing is not None:
                if existing.source_hash != document.source_hash or not existing.active:
                    raise ValueError("source reference is changed or inactive")
                return
            self._put_model(document.tenant_id, "documents", document.document_id, document)

    def update_document(self, document: CompanyDocument) -> None:
        with self._lock:
            self._put_model(document.tenant_id, "documents", document.document_id, document)

    def get_document(self, tenant_id: str, document_id: str) -> CompanyDocument | None:
        path = self._path(tenant_id, "documents", document_id)
        return CompanyDocument.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def list_documents(self, tenant_id: str) -> list[CompanyDocument]:
        return sorted(self._models(tenant_id, "documents", CompanyDocument),
                      key=lambda item: item.imported_at, reverse=True)

    def get_content(self, tenant_id: str, document_id: str) -> bytes | None:
        if self.get_document(tenant_id, document_id) is None:
            return None
        path = self._path(tenant_id, "content", document_id, ".bin")
        return path.read_bytes() if path.exists() else None

    def get_normalized(self, tenant_id: str, document_id: str) -> NormalizedDocument | None:
        path = self._path(tenant_id, "normalized", document_id)
        return NormalizedDocument.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def list_normalized(self, tenant_id: str) -> list[NormalizedDocument]:
        return self._models(tenant_id, "normalized", NormalizedDocument)

    def put_candidate(self, candidate: FactCandidate) -> None:
        with self._lock:
            self._put_model(candidate.tenant_id, "candidates", candidate.candidate_id, candidate)

    def get_candidate(self, tenant_id: str, candidate_id: str) -> FactCandidate | None:
        path = self._path(tenant_id, "candidates", candidate_id)
        return FactCandidate.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def list_candidates(self, tenant_id: str) -> list[FactCandidate]:
        return sorted(self._models(tenant_id, "candidates", FactCandidate),
                      key=lambda item: item.created_at, reverse=True)

    def put_dataset(self, tenant_id: str, dataset: DatasetConfiguration) -> None:
        self._put_model(tenant_id, "datasets", dataset.dataset_id, dataset)

    def get_dataset(self, tenant_id: str, dataset_id: str) -> DatasetConfiguration | None:
        path = self._path(tenant_id, "datasets", dataset_id)
        return DatasetConfiguration.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def list_datasets(self, tenant_id: str) -> list[DatasetConfiguration]:
        return self._models(tenant_id, "datasets", DatasetConfiguration)

    def put_domain_pack(self, tenant_id: str, pack, *, activate: bool = True) -> None:
        revision = sha256(pack.model_version.encode("utf-8")).hexdigest()[:16]
        self._put_model(tenant_id, "domain_packs", f"{pack.domain_id}--{revision}", pack)
        if activate:
            self._put_model(tenant_id, "domain_packs", pack.domain_id, pack)

    def get_domain_pack(self, tenant_id: str, domain_id: str, model_type):
        path = self._path(tenant_id, "domain_packs", domain_id)
        return model_type.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def list_domain_packs(self, tenant_id: str, model_type) -> list:
        return self._models(tenant_id, "domain_packs", model_type)
