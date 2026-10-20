# Implementation 16 — Olist real-data integration

## Status and scope

Implementation 16 adds a bounded, tenant-scoped research integration for the Olist Brazilian E-Commerce Public Dataset. It extends the existing graph, security, provenance, calibration, API, and browser layers. It does not replace the mathematical engine and does not send Olist records to an LLM.

The separately obtained original archive is read in place and excluded by Git.
Configure its local path rather than assuming the developer's filesystem layout.
See [data attribution](data_sources_and_attribution.md) for Olist's separate
CC BY-NC-SA 4.0 terms. This historical implementation is not a production-readiness claim.

## What was added

- Safe nested-directory and ZIP discovery, path traversal rejection, schema checks, hashes, missingness, duplicate-key and foreign-key inventory.
- Explicit calendar-day delivery outcome rules and unknown/excluded states.
- Reviewer-authorized, idempotent batches of at most 10,000 orders.
- Tenant-scoped order, item, seller, product, and delivery entities using the existing graph repository.
- Source file, row, dataset version, content hash, reviewer, and source-group provenance.
- Historical factual lookup and a separate prospective snapshot API.
- A chronological train/validation/test evaluator that hides delivery and review outcomes.
- A non-activated observational model and privacy-minimized reports. Its proposed domain pack is explicitly marked ineligible for approval because the source cannot verify an eventual outcome before delivery.

## Run

    # From the repository root; configure your separately obtained archive locally.
    $env:RUN_LIVE_GROQ_TESTS = "0"
    $env:RUN_LIVE_LLM_TESTS = "0"
    uv run python scripts\inspect_olist.py --data-path "archive (2).zip"
    uv run python scripts\evaluate_olist.py --data-path "archive (2).zip" --import-limit 100
    uv run pytest -q -rs

For the web application, set SENTINEL_OLIST_DATA_PATH to the absolute ZIP path and use a dedicated principal with tenant tenant_olist_research. Import requires document:upload plus reviewer role (or admin), a preview of the exact order IDs and archive hash, and explicit APPROVE action. The evaluation command is read-only. The reviewed live acceptance command is `uv run python scripts\verify_olist_live.py --authorize-reviewed-import --limit 100`; it requires Neo4j environment settings and changes only the dedicated tenant.
