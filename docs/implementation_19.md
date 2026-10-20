# Implementation 19 — reusable multi-domain investigations

## What was built

The Implementation 14/15 domain pack was extended into one contract that supports
both evidence-backed factual checks and approved probabilistic investigations. The
shared `DomainInvestigationService` selects an exact tenant/version, enforces
lifecycle and tool registration, and then routes to a registered adapter or the
existing POMDP scenario builder.

Olist remains the real-data logistics domain. Historical delivery is a factual date
comparison; prospective risk still hides future outcomes and abstains when no
approved model exists. The importer and predictive mathematics were not changed.

Procurement is a bounded synthetic second domain. It uses exact-decimal invoice/PO
reconciliation and the same domain registry, provenance repository, authorization,
versioning and durable-validation infrastructure. It does not contain a probability
model.

Both factual adapters execute through the LangGraph workflow package and its terminal
provenance gate. Probabilistic packs retain the existing Bayesian nodes and planner;
approved horizon, discount and supported reward parameters now reach that planner.
The existing worker also supports journaled, version-pinned factual investigations.

## Why

Previously, `DomainPack` was probabilistic-only and its scenario builder parsed a
purchase-order identifier directly. The new contract separates reusable governance
from domain-specific record interpretation. This demonstrates reuse without changing
Bayesian updates, Bellman planning, LangGraph orchestration, authentication or graph
provenance.

## API and UI

The API adds tenant-scoped registry, detail, validation, creation, lifecycle and
factual-investigation routes under `/api/v1/domains`. The browser adds Domain
Management for validation findings, review actions, activation, domain switching and
version-pinned factual execution. Backend rules remain authoritative.

## Scientific boundary

Synthetic procurement tests verify software behavior, not real procurement accuracy.
The Olist result that autonomous multi-step advantage is not evaluable remains
unchanged. No synthetic priors were invented, no Olist probability model was
activated, and no paid LLM was called.

See `domain_pack_schema.md`, `adding_a_domain.md`, `procurement_demo.md`, and
`multidomain_security.md` for the contract and operating guidance.

The [public validation summary](release_validation.md) describes the later integrated
acceptance scope. Full historical operational reports and local file inventories
remain private; they are not required to reproduce the synthetic quickstart.
