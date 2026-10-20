"""Offline end-to-end company-data pilot; it performs no external model calls."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.ingestion import DatasetConfiguration, EnterpriseDataService, LocalDocumentStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--tenant", default="pilot-tenant")
    parser.add_argument("--store")
    args = parser.parse_args()
    root = Path(args.store) if args.store else Path(tempfile.mkdtemp(prefix="sentinel-company-"))
    service = EnterpriseDataService(LocalDocumentStore(root), InMemoryGraphRepository())
    service.configure_dataset(args.tenant, DatasetConfiguration(
        dataset_id="delivery", name="Delivery records",
        field_mapping={"purchase_order": "po", "supplier": "supplier",
                       "expected_date": "expected", "actual_date": "actual"}))
    results = []
    for source in args.files:
        result = service.upload(
            args.tenant, dataset_id="delivery", filename=source.name,
            content=source.read_bytes())
        results.append({
            "document_id": result.document.document_id,
            "status": result.document.status.value,
            "version": result.document.version,
            "candidates_created": result.candidates_created,
        })
    print(json.dumps({"documents": results, "review_required": True}, indent=2))


if __name__ == "__main__":
    main()
