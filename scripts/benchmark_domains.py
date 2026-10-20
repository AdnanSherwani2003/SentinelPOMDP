"""Small local overhead measurement; not a production capacity benchmark."""
from __future__ import annotations

from statistics import mean, median, quantiles
from tempfile import TemporaryDirectory
from time import perf_counter

from sentinel_pomdp.domains import (
    DomainInvestigationService,
    DomainPackService,
    ProcurementAdapter,
    procurement_demo_pack,
    seed_synthetic_procurement,
)
from sentinel_pomdp.graph.repository import InMemoryGraphRepository
from sentinel_pomdp.ingestion.storage import LocalDocumentStore


def summary(values: list[float]) -> dict[str, float]:
    return {"mean_ms": mean(values), "median_ms": median(values),
            "p95_ms": quantiles(values, n=20)[18]}


def main() -> None:
    with TemporaryDirectory(prefix="sentinel-domain-benchmark-") as root:
        service = DomainPackService(LocalDocumentStore(root), InMemoryGraphRepository())
        pack = procurement_demo_pack("benchmark-tenant")
        validation, persistence, lookup = [], [], []
        for index in range(100):
            candidate = pack.model_copy(update={"model_version": f"v{index}"})
            started = perf_counter(); checked = service.validate("benchmark-tenant", candidate)
            validation.append((perf_counter() - started) * 1000)
            started = perf_counter(); service.save("benchmark-tenant", checked)
            persistence.append((perf_counter() - started) * 1000)
            started = perf_counter(); service.get_version("benchmark-tenant", pack.domain_id, f"v{index}")
            lookup.append((perf_counter() - started) * 1000)
        selected = service.get_version("benchmark-tenant", pack.domain_id, "v99")
        assert selected is not None
        service.submit_for_review("benchmark-tenant", selected.domain_id, selected.model_version)
        service.approve("benchmark-tenant", selected.domain_id, selected.model_version, "benchmark-reviewer")
        service.activate("benchmark-tenant", selected.domain_id, selected.model_version)
        seed_synthetic_procurement(service.repository, "benchmark-tenant")
        runtime_started = perf_counter()
        runtime = DomainInvestigationService(service, [ProcurementAdapter(service.repository)])
        runtime_startup_ms = (perf_counter() - runtime_started) * 1000
        registry_load, selection, investigation = [], [], []
        for _ in range(100):
            started = perf_counter(); service.list("benchmark-tenant")
            registry_load.append((perf_counter() - started) * 1000)
            started = perf_counter(); service.get_version(
                "benchmark-tenant", selected.domain_id, selected.model_version)
            selection.append((perf_counter() - started) * 1000)
            started = perf_counter(); result = runtime.investigate(
                "benchmark-tenant", selected.domain_id, "Check INV-1001",
                version=selected.model_version)
            investigation.append((perf_counter() - started) * 1000)
            assert result.classification == "MATCH_SUPPORTED"
        print({"iterations": 100, "validation": summary(validation),
               "save": summary(persistence), "version_lookup": summary(lookup),
               "registry_load": summary(registry_load),
               "model_selection": summary(selection),
               "runtime_startup_ms": runtime_startup_ms,
               "factual_investigation": summary(investigation),
               "scope": "local single-process engineering measurement"})


if __name__ == "__main__":
    main()
