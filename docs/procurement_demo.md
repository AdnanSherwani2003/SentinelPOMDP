# Synthetic procurement demonstration

The procurement domain asks whether an invoice matches its purchase order. The
fixtures are explicitly synthetic and verify engineering behavior only. They do not
establish fraud, supplier intent, empirical priors or real-company accuracy.

The adapter retrieves approved invoice, purchase-order and optional goods-receipt
evidence through tenant-scoped repository methods. It compares supplier, currency,
line identifiers, quantities, unit prices and totals. Money uses `Decimal`, explicit
rounding and configured decimal-string tolerances. Duplicate lines, missing records,
multiple current versions, withdrawn sources and absent three-way-match receipts fail
closed.

Outcomes are `MATCH_SUPPORTED`, `MISMATCH_SUPPORTED`, `INSUFFICIENT_EVIDENCE`, and
`CONFLICTING_EVIDENCE`. The first two answer only the reconciliation question. A
mismatch is never labeled fraud or misconduct.

The fixture helper writes only to the repository supplied by a test or demonstration.
Acceptance tests use disposable in-memory stores and never import synthetic records
into `tenant_olist_research`.
