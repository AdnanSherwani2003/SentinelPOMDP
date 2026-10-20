# SentinelPOMDP technical case study

SentinelPOMDP investigates whether a claim has enough support to answer. Its central
engineering problem is connecting uncertain decisions to actual evidence while
keeping language generation outside the decision authority.

## Reasoning and orchestration

A belief distribution represents uncertain hidden conditions. Given an approved
likelihood model, Bayes' rule multiplies prior probability by the likelihood of an
observation and normalizes the result. Information gain measures expected reduction
in uncertainty. Finite-horizon Bellman lookahead compares permitted actions, their
costs and terminal rewards. The chosen policy can legitimately stop and abstain.
The independent I20 reference case reproduces posterior 6/7 and 1/7 for a two-state
example; existing tests cover normalization, entropy, costs and deterministic parity.

LangGraph orchestrates the investigate/update/replan loop. It does not replace the
planner's authority. Checkpoints retain tenant, scenario and model version; resume
must match those identifiers. The LLM can interpret an input into a registered
schema or explain returned evidence. Invalid/malformed/ungrounded output falls back
to deterministic handling; no model-controlled tools are available.

## Evidence, ingestion and governance

Neo4j stores tenant-scoped entities, facts, documents, evidence and support/conflict
links. Ingestion records original bytes, hashes, locations and candidate facts.
An authenticated reviewer approves or rejects candidates before publication.
Withdrawn or superseded sources stop qualifying as active evidence. A hash verifies
consistency, not truth; independent source groups must not be inferred from copies.

The reusable domain pack separates factual checks from probabilistic models.
Olist uses reviewed historical delivery rows and temporally restricted snapshots.
Synthetic procurement compares invoices and purchase orders with exact decimal
rules. Both use common registry/version/auth/evidence/orchestration boundaries;
reviewed adapters hold domain-specific interpretation.

## Reliability and security

PostgreSQL stores durable jobs, journals, operational audit and LangGraph
checkpoints. Workers atomically claim leases with fencing tokens, retry only safe
operations, detect changed idempotent input and honor cancellation at safe points.
Uncertain effects require reconciliation. Backup rehearsal restores graph/source
metadata and operational/checkpoint records into disposable storage.

The final audit found and corrected a legacy model activation bypass and an
inapplicable HTTP worker health check. API tenant scope, reviewer permission,
protected source access, payload limits and fake-provider defaults are verified
boundaries. One API process remains the supported deployment restriction because
authentication and throttling are process-local.

## Research findings

The retained synthetic benchmark gives immediate abstention better mean utility
than the investigated policies under its reward assumptions. Horizon-2 improves on
one-step utility within that simulator, not on the abstention baseline. Olist
purchase-time Brier improvement over prior-only is very small; carrier handoff uses
later information. No counterfactual investigation outcomes exist in the archive,
so real-world POMDP advantage remains NOT EVALUABLE. Procurement is synthetic and
has no validated business-accuracy estimate.

Engineering results and exact I20 test counts are recorded in the final acceptance
report. This is a published portfolio/research system, not a production
certification. Lessons include treating abstention as a valid outcome, separating
probability from evidence sufficiency, exercising actual startup/restore commands,
and preserving inconvenient benchmark findings.

## Resume bullets (drafts)

- Built a modular investigation engine with Bayesian belief updates, finite-horizon
  POMDP planning and deterministic evidence-aware ANSWER/ABSTAIN decisions.
- Integrated Neo4j provenance, LangGraph workflows, tenant-scoped document ingestion
  and authenticated human review through FastAPI and a browser console.
- Implemented PostgreSQL durable jobs with leases, fencing, idempotency,
  cooperative cancellation and version-checked checkpoint recovery.
- Evaluated historical e-commerce delivery data using chronological splits and
  temporal leakage controls, documenting the limits of counterfactual policy evaluation.
- Extended reusable domain configurations to Olist logistics and exact-decimal
  synthetic procurement, with reviewer approval and source-withdrawal safeguards.

No customer adoption, revenue, production rollout or benchmark improvement is
asserted. Future work follows the observed gaps in limitations_and_future_work.md.
