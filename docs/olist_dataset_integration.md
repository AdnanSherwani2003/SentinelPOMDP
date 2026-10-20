# Olist dataset integration

## What and why

The release is a relational dataset: separate CSV tables use primary keys (unique row identities) and foreign keys (references to another table). Keeping these distinctions prevents one order with several items or payments from being counted several times.

The separately obtained ZIP has nine standard files. The
[public research summary](research_data_summary.md) gives aggregate counts and
source hashes. Detailed local inventory outputs include filesystem metadata and
remain private. See [dataset attribution](data_sources_and_attribution.md).

## Safe ingestion

The reader validates ZIP paths and schemas and never extracts, renames, or overwrites the source. The batch importer uses deterministic identifiers, making repeated imports idempotent. An authenticated reviewer previews the bounded order set and source archive hash, then sends an explicit `APPROVE` action through the API. The default first stage imports 100 orders; the hard per-call maximum is 10,000. The read-only evaluator never publishes evidence.

The order table is the single source for delivery outcome. Order-items is not treated as independent delivery confirmation. Customer geography and review text are not placed in evaluation reports. Public/anonymized data still receives tenant and access controls.

## Provenance

Every delivery fact links to the Olist orders document and exact CSV row. It records dataset version, file hash, comparison convention, and reviewer. Item relationships record the source item row. All files belong to one published Olist release and therefore one dependent source group.

The source row API verifies the current file hash against the approved graph document before showing the projected original row. The graph repository retains document deactivation semantics. An Olist-specific source version replacement and revocation workflow still needs explicit testing before using updated releases.
