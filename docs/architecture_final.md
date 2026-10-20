# Final architecture

Historical Implementation 13 architecture snapshot. For the integrated I20 system,
including PostgreSQL jobs/checkpoints and multi-domain governance, see architecture.md.
The process-local state descriptions below refer to that earlier milestone.

## Authority boundary

SentinelPOMDP separates language convenience from decision authority. The model may interpret a question into a Pydantic schema and propose an explanation. A trusted registry validates the scenario, subject and claim type. Deterministic code chooses graph queries, updates the belief, selects actions, verifies evidence and decides whether answering is allowed.

```text
Question
  -> API-key authentication -> principal and tenant
  -> provider privacy gate
  -> structured intent -> trusted scenario registry
  -> LangGraph state machine
       -> finite-horizon POMDP planner
       -> typed graph action (no arbitrary Cypher)
       -> tenant-scoped repository
       -> observation adapter
       -> exact Bayesian update
       -> evidence/provenance gate
  -> deterministic ANSWER or ABSTAIN
  -> candidate explanation -> grounding validator
       -> accepted text OR deterministic fallback
```

The LLM cannot change a prior, likelihood, cost, decision threshold, tenant, tool parameters, or final decision.

## How the 13 milestones connect

1. Belief distributions represent uncertainty.
2. Bayesian updates incorporate observations.
3. Information gain values uncertainty reduction.
4. Costs and terminal rewards make investigation a decision problem.
5. Finite-horizon Bellman lookahead evaluates future evidence paths.
6. Simulation measures selective decisions and calibration under known synthetic truth.
7. Neo4j stores tenant-scoped entities, facts, evidence, documents and provenance.
8. Typed investigation tools turn verified graph results into observation tokens.
9. LangGraph runs the bounded investigate/update/replan loop.
10. The intelligence adapter maps language to registered scenarios and validates explanations.
11. Authentication, authorization, privacy controls, budgets and audit events form the security boundary.
12. FastAPI and the same-origin browser UI expose that protected service.
13. Deployment packaging, CI, evaluation, reliability tests and readiness documentation make limitations reproducible.

## Data and state lifetimes

Neo4j evidence persists in its volume. API keys, rate-limit counters, idempotency bindings, traces, metrics, audit events and LangGraph `InMemorySaver` checkpoints are process-local. An application restart loses all of those process-local records. A multi-worker deployment would give each worker separate copies; the provided deployment deliberately runs one worker.

## Evidence semantics

A source hash detects content changes but does not prove that a source is truthful or authentic. Multiple records may be correlated. Missing records mean only that the configured graph query found no qualifying record; missing certification evidence is not proof of non-certification. Causal attribution requires claim-specific causal evidence and is not inferred from shipment lateness.

The legacy ID `fact_sup_a_caused_delay` is retained for compatibility. Its actual relation is `EXPERIENCED_DELAY` between Supplier A and a shipment; the synthetic record now contains an explicit narrow presentation label. The causal scenario uses separate incident-attribution facts and still abstains without its required causal evidence.

## Deployment modes

- Offline development: memory graph and deterministic fake provider.
- Local integration: live Neo4j and fake provider.
- Explicit real model: Neo4j plus separately authorized Groq or OpenAI processing.
- Deployment candidate: fail-closed candidate mode, one worker, localhost exposure, controlled trusted evaluation only.

The last mode is packaging for a pilot environment, not a declaration of enterprise production safety.
