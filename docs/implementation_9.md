# Implementation 9 — LangGraph orchestration

## Scope

Implementation 9 adds a stateful `StateGraph` around the deterministic POMDP and
graph-investigation components delivered in Implementations 1–8. LangGraph decides
*when a node runs*; it does not decide which investigation is useful, calculate a
posterior, or determine whether evidence is sufficient.

The project uses `langgraph>=1.0,<2.0` (resolved to 1.2.15 during development) and
now requires Python 3.10 or later. Current LangGraph 1.x requires Python 3.10+;
pinning an obsolete pre-1.0 release merely to retain Python 3.9 support was rejected.

Official references:

- <https://reference.langchain.com/python/langgraph/graph/state/StateGraph/compile>
- <https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges>
- <https://reference.langchain.com/python/langgraph/checkpoint/memory/InMemorySaver>

## Architecture

```text
START
  |
  v
initialize --> plan --INVESTIGATE--> investigate --> adapt_observation
                |                                      |
                |                                      +-- error --> finalize
                |                                      |
                |                                      v
                |                               bayesian_update
                |                                      |
                |                                      +------> plan (cycle)
                |
                +-- ANSWER --> evidence_gate --> finalize --> END
                |
                +-- ABSTAIN/error -----------> finalize --> END
```

Runtime dependencies (`BaseGraphRepository`, `MultiStepPlanner`, tool registry,
scenario) are captured by the node collection and never placed in checkpointed
state. The state contains only JSON-compatible values and source references.

## Educational component guide

### StateGraph

**What is it?** A directed graph whose nodes read and update a shared typed state.

**Why do we need it?** It makes control flow, cycles, terminal paths, and error paths
explicit instead of hiding them inside one large loop.

**How does it work?** `InvestigationWorkflow` registers seven nodes, explicit
`START`/`END` edges, and conditional edges after planning and observation mapping.

**Connection to Implementations 1–8.** It wraps the direct session behavior without
replacing `MultiStepPlanner`, repository queries, `adapt_result`, or
`EvidencePolicy`.

**How do we verify it?** Tests inspect compiled nodes and edges and assert the
Bayesian-update-to-plan cycle exists.

### Workflow state

**What is it?** `InvestigationGraphState` is a `TypedDict` describing everything
needed to resume or audit a run.

**Why do we need it?** Nodes must exchange predictable data without serializing
database drivers, secrets, arbitrary objects, or large raw documents.

**How does it work?** It stores tenant/scenario identity, beliefs, planner history,
budgets, compact tool results, observations, unique evidence/document IDs, costs,
structured trace records, errors, and the final outcome. Evidence text is replaced
with `[omitted from workflow state]`; references and hashes remain.

**Connection to Implementations 1–8.** Its beliefs and histories use the existing
planner contracts, while final output remains the Implementation 8
`InvestigationOutcome` contract.

**How do we verify it?** Pydantic validates initial inputs and trace records; tests
exercise normalized posteriors, tenant identity, checkpoint identity, and final
contract parsing.

### Nodes

**What are they?** Small functions with one responsibility: initialize, plan,
investigate, adapt, update, gate, or finalize.

**Why do we need them?** Small boundaries make failures attributable and prevent
orchestration code from silently taking over mathematical responsibilities.

**How do they work?** The plan node calls `MultiStepPlanner.decide`; investigate
calls `GraphInvestigationTools.execute`; adapt calls `adapt_result`; update calls
`MultiStepPlanner.posterior`; the gate calls `EvidencePolicy.evaluate`.

**Connection to Implementations 1–8.** Every substantive decision delegates to an
existing deterministic component. No Bayesian formula or heuristic action chooser
was duplicated.

**How do we verify them?** Integration tests assert the planner-selected action is
the action sent to the graph tool, the resulting token changes the posterior, and
the next planner call sees that posterior.

### Edges and conditional routing

**What are they?** Edges specify legal next nodes; conditional edges select among
them from state.

**Why do we need them?** They make ANSWER, INVESTIGATE, ABSTAIN, and error handling
different, inspectable execution paths.

**How do they work?** `route_planner_decision` reads only the planner's returned
kind. `route_observation` sends operational failures to finalization without a
Bayesian update. Routers never select a supplier or tool themselves.

**Connection to Implementations 1–8.** The existing planner owns the decision;
LangGraph faithfully routes it.

**How do we verify them?** Tests cover every planner branch, invalid decisions,
unknown actions, database failure, budget and tool-call exhaustion.

### Cycles

**What are they?** A path from Bayesian update back to planning.

**Why do we need them?** Autonomous investigation requires repeated evidence
gathering, not a one-shot graph query.

**How do they work?** After a valid graph observation, the existing posterior method
updates belief, records the unique evidence IDs and cost, and returns to `plan`.
Used actions remain in history, so the planner cannot repeat them.

**Connection to Implementations 1–8.** This exposes the direct runner's loop as a
real workflow cycle while retaining Bellman selection.

**How do we verify it?** `multi_investigation_screening` executes two distinct graph
tools. The first supported observation moves `supplier_signal` from 0.55 to about
0.887; replanning selects the internal signal; its supported observation moves the
belief back to 0.55; the workflow then abstains. Horizon 1 performs no tool call in
this fixture, while horizon 2 sees value in the two-step sequence.

### Evidence gate and terminal states

**What are they?** The gate checks source-backed relevance independently of
posterior confidence; terminal state freezes either ANSWER or ABSTAIN.

**Why do we need them?** High probability cannot turn evidence about shipment
lateness into proof of production-delay causation.

**How do they work?** The broad causal scenario now requires an explicit causal
evidence ID absent from the dataset and therefore abstains with
`IRRELEVANT_SUPPORT`. A separate narrow shipment-delay scenario requires the two
independent warehouse/telematics documents and can answer.

**Connection to Implementations 1–8.** This extends the Implementation 8 policy
with optional claim-specific evidence IDs; fact IDs alone are no longer always
sufficient.

**How do we verify it?** Tests show posterior 0.84 for Supplier A still abstains,
while the narrow delayed-shipment posterior of about 0.887 answers with two source
references. Conflicted, missing, tampered, and missing-source cases abstain.

### Checkpointing

**What is it?** Optional `InMemorySaver` snapshots keyed by a stable `thread_id`.

**Why do we need it?** It demonstrates resumable state and protects a completed run
from accidental duplicate tool execution.

**How does it work?** Before invocation, `InvestigationWorkflow.run` checks the
latest checkpoint. A completed outcome is returned directly after tenant and
scenario identity validation, so evidence, costs, and tool calls are not repeated.

**Connection to Implementations 1–8.** Checkpointing stores the orchestration state;
it does not change planner or repository behavior.

**How do we verify it?** Running a completed thread twice returns identical belief,
trace length, cost, and one tool call. Reusing the thread for another tenant raises
an error.

This is process-local test/demo memory, not durable persistence. Restarting the
process loses checkpoints. No Redis, database, or cloud checkpoint service was
introduced.

## State schema summary

| Category | Fields |
|---|---|
| Identity | `tenant_id`, `scenario_id` |
| Mathematical state | `hypotheses`, `current_belief`, `planning_horizon`, `action_history` |
| Current transition | `pending_action`, `planner_decision`, `latest_tool_result`, `latest_observation` |
| Evidence references | `observations`, `seen_evidence_ids`, `seen_document_ids` |
| Limits | `max_tool_calls`, `investigation_count`, `remaining_budget`, `total_cost` |
| Terminal state | `terminal_decision`, `final_hypothesis`, `evidence_verdict`, `termination_reason` |
| Observability | `investigation_steps`, `workflow_trace`, planning/tool runtime |

## Error handling

- Database and driver failures become `DATABASE_UNAVAILABLE`, route directly to
  safe abstention, and never enter Bayes.
- Unknown actions and invalid planner decisions terminate before tool execution.
- Unauthorized tenant/scenario combinations fail initialization.
- Unsupported or impossible observations terminate without modifying belief.
- Hash mismatch and missing-source outcomes fail evidence sufficiency.
- Budget and tool-call limits turn the next investigation into deterministic
  abstention without charging another cost.
- No automatic node retry policy is configured, avoiding duplicate tool charges or
  updates. The read-only tools remain safe for a future deliberately scoped retry.

## Neo4j optional temporal fields

`valid_from` and `valid_to` are intentionally optional. Neo4j removes properties
assigned `null`, so statically returning `f.valid_from` caused unknown-property
notifications on graph snapshots where no fact had that property. Repository reads
now return `properties(f)` and use `.get(...)`, preserving `None` without inventing
dates or globally suppressing notifications.

## Direct runner comparison

The deterministic comparison covers four scenarios at horizons 1 and 2. It checks
decisions, selected hypotheses, posteriors, action sequences, evidence IDs, and
costs. All eight matched in the implementation run. LangGraph is slower on this
tiny in-process workload because compilation/state transitions dominate; its value
is explicit control, traceability, and extension points—not improved Bayesian
accuracy.

## Reproduction

```powershell
# From the repository root.

uv sync
uv run pytest -q

uv run python scripts\demo_langgraph.py --backend in-memory --horizon 2
uv run python scripts\demo_langgraph.py --backend neo4j --horizon 2
uv run python scripts\evaluate_langgraph.py
```

The Neo4j command fails explicitly when the requested live service is unavailable;
it never falls back to memory.

## Limitations and Implementation 10 readiness

- Observation probabilities remain hand-designed synthetic assumptions.
- Conditional independence is still approximated conservatively through duplicate
  source suppression.
- The multi-step fixture is deterministic and not a statistical benchmark.
- In-memory checkpoints are non-durable and intended only for tests/demos.
- Tenant scope is an application boundary, not a production identity system.
- Hashes provide integrity checking, not authenticity or truth.
- LangGraph adds measurable overhead for these tiny local scenarios.

Implementation 10 can add a natural-language/LLM adapter before initialization and
an explanation renderer after finalization. It must treat the compiled workflow as
the decision authority: the LLM may translate inputs and explain structured output,
but may not choose tools, update beliefs, override the evidence gate, or invent
terminal decisions.
