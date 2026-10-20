# Implementation 8 — Graph-backed autonomous investigation

## Status and scope

Implementation 8 adds the evidence-retrieval bridge between the existing exact
finite-horizon POMDP planner and the Implementation 7 graph repositories. It does
not add an LLM, LangGraph, an API, or a user interface. The synthetic supplier
dataset remains a deterministic prototype, not evidence of real-world accuracy.

## Complete execution loop

```text
scenario + prior + authorized action map
              |
              v
       MultiStepPlanner.decide
              |
      INVESTIGATE action name
              |
              v
 typed request -> read-only graph tool -> repository
              |
       facts + provenance records
              |
              v
 observation adapter (registered token only)
              |
       MultiStepPlanner.posterior (Bayes)
              |
              v
           replan
              |
 mathematical terminal candidate + independent evidence gate
              |
       ANSWER with references / ABSTAIN
```

The planner predicts possible future observations from its likelihood model. An
executed observation is never sampled from that model: it is derived from the
actual repository result.

## Major components

### 1. Typed graph investigation tools

**What is it?** A small allowlist of Pydantic-validated, read-only operations:
fact evidence, entity relationships, and competing claims.

**Why is it necessary?** It prevents planner-generated action names from becoming
unrestricted Cypher and gives failures, missing records, conflicts, and provenance
failures distinct meanings.

**How does it work?** `GraphInvestigationTools.execute` checks the authorized tenant,
relation-type allowlist, traversal/result bounds, and then calls only methods on
`BaseGraphRepository`. Driver exceptions become `DATABASE_UNAVAILABLE`, never
negative factual evidence.

**Connection to Implementations 1–7.** It reuses the Implementation 7 repository,
tenant scope, provenance chain, SHA-256 check, and both repository backends.

**How do we know?** Tool tests cover valid evidence, conflicts, missing IDs,
authorization, invalid relation types, bounded paths, and database exceptions.

### 2. Evidence-to-observation adapter

**What is it?** A deterministic translation from a validated graph result into one
registered observation token.

**Why is it necessary?** Bayes' theorem needs a member of the declared observation
space. A timeout or malformed result must not be interpreted as evidence against a
hypothesis.

**How does it work?** Supported, conflicted, contradicted, absent, duplicate, and
hash-mismatch outcomes have explicit tokens. Authorization, invalid-request, and
database failures raise `UnsafeToolResult` and end the session conservatively.

**Connection to Implementations 1–7.** The adapter feeds the existing
`MultiStepPlanner.posterior`; it does not replace the Bayesian updater.

**How do we know?** Parameterized tests exercise every normal evidence class,
duplicate sources, hash tampering, and operational failure rejection.

### 3. Mathematical planner integration

**What is it?** `run_graph_investigation` is a bounded loop joining a planner action
to a typed request and joining the returned observation back to the planner.

**Why is it necessary?** Without this loop, a graph demo and a POMDP calculation
would remain independent demonstrations.

**How does it work?** The scenario maps each modeled action to one authorized typed
request. The planner selects the action using expected utility and Bellman
lookahead. The tool result creates the real observation, the posterior is updated,
and the planner runs again. Used actions remain in planner history, costs consume a
budget, and every step is recorded.

**Connection to Implementations 1–7.** Implementation 6's exact Bellman solver is
unchanged. Implementation 8 supplies domain configuration around it and preserves
the original security adapter and benchmarks.

**How do we know?** The integration test asserts that the action selected by the
planner invokes the mapped graph fact, retrieves its real evidence ID, changes the
posterior, and changes the next decision to ANSWER.

### 4. Evidence sufficiency gate

**What is it?** A policy independent of posterior confidence that states which
traceable facts must support each answer hypothesis.

**Why is it necessary?** A probability of 0.93 is not proof. A supported delivery
delay is also not automatically proof of causal responsibility for a production
delay.

**How does it work?** `EvidencePolicy` requires a registered fact, a supported
observation, verified provenance, a configured number of distinct documents, and
no contradiction or hash mismatch. Final results retain contradictory references
even when the mathematical planner abstains.

**Connection to Implementations 1–7.** It builds on Implementation 7 provenance
status while keeping probability and evidentiary support separate.

**How do we know?** Tests show that a high prior cannot bypass the gate and that
conflicted and unevidenced cases abstain.

### 5. Structured trace and evaluation

**What is it?** Pydantic step/outcome records, a text formatter, and a deterministic
three-scenario policy comparison.

**Why is it necessary?** Decisions must be reproducible and auditable before a later
orchestration layer is added.

**How does it work?** Each step records beliefs, utility scores, selected action,
tool/status, references, token, posterior, cost, latency, and evidence verdict. The
evaluation runs a fixed sequence, horizon 1, and horizon 2 on the same graph and
policies.

**Connection to Implementations 1–7.** It exposes the values already produced by
the mathematical and graph layers; it does not synthesize a narrative with an LLM.

**How do we know?** The demo prints dynamically executed traces and the policy test
checks supported answers, unsupported answers, abstentions, and conflict handling.

## Mathematical assumptions

The supplier likelihood table is deliberately hand-designed for the synthetic
demonstration and is **not empirically calibrated**. For each action and hidden
hypothesis it defines a normalized distribution over:

- `EVIDENCE_SUPPORTED`
- `EVIDENCE_CONFLICTED`
- `EVIDENCE_CONTRADICTED`
- `EVIDENCE_NOT_FOUND`
- `DUPLICATE_INFORMATION`
- `SOURCE_HASH_MISMATCH`

When an action targets the true hypothesis, the illustrative probabilities are
`(.77, .08, .03, .10, .01, .01)`; otherwise they are
`(.12, .10, .24, .52, .01, .01)` in the order above.

The existing static-state planner assumes observations from distinct tools are
conditionally independent given the hidden hypothesis. The graph can contain
correlated records, so Implementation 8 does not claim to solve general evidence
correlation. The conservative policy tracks evidence and document IDs across an
episode. If another action overlaps either set, it emits `DUPLICATE_INFORMATION`,
whose equal likelihood across hypotheses leaves the posterior unchanged. This
prevents a reused source from becoming a second independent confirmation.

Document hashes detect changes relative to the ingested bytes. They do not prove
authenticity, authorship, truth, or trustworthiness of the source.

## Synthetic scenarios

1. Supplier A attribution: graph evidence supports the incident-attribution fact;
   the evidence gate can permit an answer.
2. Supplier B delivery: supplier and dock records conflict; the result preserves
   both records and abstains.
3. Component certification: the fact exists without linked evidence; the result
   abstains.

These are three deterministic cases from one small static graph. Repeated queries
are not treated as independent benchmark episodes, and the evaluation makes no
real-world accuracy claim.

## Reproduction (PowerShell)

```powershell
# From the repository root.

# All tests (live tests skip if Neo4j is unavailable)
uv run pytest -q

# Deterministic reference-backend demo
uv run python scripts\demo_graph_investigation.py --backend in-memory

# Live backend: explicitly fails instead of falling back
docker compose -f infra\compose.yaml up -d
uv run python scripts\demo_graph_investigation.py --backend neo4j

# Policy comparison only
uv run python scripts\evaluate_graph_investigation.py
```

## Known limitations and Implementation 9 readiness

- The graph and likelihoods are synthetic and small.
- The likelihoods are assumptions, not learned calibration.
- Duplicate suppression is conservative; a richer model would represent source
  dependence rather than vetoing overlapping updates.
- Tenant authorization is a caller-supplied session boundary, not a production
  identity platform.
- Hash validation is integrity checking, not source authentication.
- The deterministic comparison is a functional policy comparison, not a
  statistically powered benchmark.

A future LangGraph layer can call `run_graph_investigation` as one typed node and
render its structured outcome. It must not move belief updates, expected utility,
Bellman recursion, evidence gating, or stopping decisions into an LLM.
