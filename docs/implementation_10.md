# Implementation 10 — constrained LLM intelligence adapter

## Scope and authority boundary

This implementation adds natural-language interpretation and grounded explanation
around the existing graph-backed LangGraph investigation. It does **not** make the
LLM an autonomous decision-maker.

```text
untrusted question
      |
structured intent (LLM) -> deterministic allow-list validation
      | invalid                         | registered only
      v                                 v
clarify/reject               existing LangGraph/POMDP workflow
                                         |
                              deterministic outcome
                                         |
                              structured prose (LLM)
                                         |
                              deterministic grounding check
                                 | valid      | invalid/failure
                                 v            v
                              return      template fallback
```

Tenant identity is supplied by trusted application code and is absent from the
intent schema. The model cannot create a scenario, choose a repository operation,
change a prior or likelihood, update a belief, satisfy the evidence gate, or alter
an `ANSWER`/`ABSTAIN` decision. Raw document and evidence content never enter a
prompt; only the question, public scenario catalog, outcome values, and source IDs
cross the provider boundary.

## Educational component guide

### Provider abstraction

**What?** `LLMClient.generate_structured` returns a validated Pydantic object plus
usage telemetry. **Why?** Core logic stays provider-independent and CI stays
offline. **How?** `OpenAIResponsesClient` and `GroqResponsesClient` share an
OpenAI-compatible Responses adapter. Both use `responses.parse` with a Pydantic
`text_format`, a bounded timeout and SDK retries, and no tools. OpenAI defaults to
`gpt-4o-mini`. Groq defaults to `openai/gpt-oss-120b` and targets
`https://api.groq.com/openai/v1`. Either model can be overridden with
`SENTINEL_LLM_MODEL`. Provider-specific `SENTINEL_OPENAI_MODEL` and
`SENTINEL_GROQ_MODEL` take precedence; credentials come only from `OPENAI_API_KEY`
or `GROQ_API_KEY`.
**Verification?** Mocked provider contracts check configuration, schemas, token
telemetry, failures, and absence of tools; live verification is credential-gated.

This follows the official [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
Structured shape is necessary but not sufficient, so deterministic semantic checks
still run after generation.

Groq configuration follows its official [Responses API documentation](https://console.groq.com/docs/responses-api),
which documents the OpenAI SDK base URL and Pydantic `responses.parse` support.
Groq currently labels this endpoint beta, so provider errors remain bounded and
fall back safely rather than bypassing validation.

#### Groq schema compatibility (Implementation 10.1)

Live verification found two strict-schema differences that mock tests alone did
not reveal. Nullable Pydantic fields produced ambiguous `anyOf` branches, and an
open-ended posterior dictionary violated Groq's requirement that every object use
`additionalProperties: false`. The two LLM-bound schemas therefore use explicit
empty/`NONE` sentinels and represent posterior entries as a typed list of
`{hypothesis, probability}` objects. The public response still uses the original
optional fields and posterior dictionary, and the mathematical workflow is
unchanged.

The live model also mapped an unspecified “the supplier” question to a registered
scenario. A deterministic registry check now requires an explicit registered
subject or screening-scope alias in the original question. LLM guesses for an
unstated subject become `CLARIFICATION_REQUIRED` before LangGraph can execute.

### Deterministic fake client

**What?** `DeterministicFakeLLM` is an offline rule-based test double, explicitly
labeled `deterministic-fake`; it is not a real model. **Why?** Failure, malformed
output, injection, and full scenarios remain reproducible. **How?** Rules map demo
paraphrases to registered IDs and copy trusted outcome fields into a draft; scripted
objects or exceptions exercise negative paths. **Verification?** Tests cover all
five scenarios, paraphrases, ambiguity, unsupported questions, bounded failures,
and explanation fallback.

### Intent schema and scenario registry

**What?** `ParsedInvestigationIntent` is strict (`extra="forbid"`), while
`ScenarioRegistry` is the trusted allow-list of scenario ID, subject ID, claim type,
and factory. **Why?** Model text must never become an arbitrary scenario, target,
tool, prior, or tenant. **How?** The exact registered triple is required; the
registry constructs the scenario with the caller's tenant and verifies every graph
request kept that scope. **Verification?** Tests reject extra `tenant_id`/`prior`
fields, invented IDs, and subject/claim mismatches before LangGraph runs.

### Grounded explanation and fallback

**What?** `GroundedExplanationDraft` carries prose plus the exact decision,
posterior, supporting and contradicting IDs, document IDs, provenance, and
limitation. **Why?** Schema-valid prose can still fabricate citations, omit a
contradiction, or change a conclusion. **How?** Evidence is reclassified through
the tenant-scoped repository and intersected with the evidence gate's allow-list.
The validator requires exact values and a limitation for every abstention. Failure
uses a deterministic template. **Verification?** A scripted `.99` posterior and
fabricated evidence/document are rejected; real values and citations are restored.

### Prompt-injection resistance

**What?** Defense in depth for hostile question or source text. **Why?** Prompts are
not a security boundary. **How?** Questions are marked untrusted, source content is
excluded, schemas carry no authority fields, registry validation happens before
execution, and output grounding happens after generation. **Verification?** Tests
attempt to change tenant, force an answer, claim 100%, and poison stored document
content. The causal case still abstains at posterior `.84` for `tenant_alpha`, and
poison text is absent from recorded model calls.

## Public response contract and observability

`InvestigationResponse` contains status; mapped scenario, subject, and claim; final
decision/posterior; explanation; supporting and contradicting evidence IDs; source
document IDs; provenance and limitation; fallback flags; trace ID; original
`InvestigationOutcome`; and per-call latency/token/cost telemetry. Real-provider
cost is `null` because code does not guess changing prices. The fake reports zero.

## Running it

```powershell
uv run python scripts/demo_llm_intelligence.py
uv run python scripts/demo_llm_intelligence.py --backend neo4j
uv run python scripts/demo_llm_intelligence.py --provider groq
uv run python scripts/evaluate_llm_intelligence.py
uv run pytest -q
```

For an explicitly authorized real-provider run:

```powershell
$env:OPENAI_API_KEY = "..."
$env:SENTINEL_LLM_MODEL = "gpt-4o-mini"
uv run python scripts/demo_llm_intelligence.py --provider openai --question "Was Supplier A's shipment late?"
$env:RUN_LIVE_LLM_TESTS = "1"
uv run pytest -q -m live_llm
```

For Groq Cloud, the default is `openai/gpt-oss-120b`:

```powershell
$env:GROQ_API_KEY = "..."
$env:SENTINEL_GROQ_MODEL = "openai/gpt-oss-120b"
$env:RUN_LIVE_GROQ_TESTS = "1"
uv run python scripts/demo_llm_intelligence.py --provider groq
uv run pytest -q -m live_groq
```

API keys must remain environment variables and must never be printed or committed.

## Verification matrix

| Layer | Verification |
|---|---|
| Prior implementations | Full regression suite |
| Facade | Five in-memory scenarios and paraphrases |
| Grounding | Exact outcome/citation checks and fabricated-output fallback |
| Safety | Injection, authority-field, raw-source, ambiguity tests |
| OpenAI adapter | Mocked official structured-output contract |
| Groq adapter | Mocked base URL, credentials, model, parsing, and failure contracts |
| Neo4j | Same facade against live repository when reachable |
| Real model quality | Optional paid test only; not represented by fake metrics |

Fake-client accuracy verifies application wiring only. It is not evidence of
real-model interpretation quality.
