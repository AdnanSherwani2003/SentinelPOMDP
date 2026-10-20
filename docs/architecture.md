# Verified system architecture

Current scope: Implementations 1–20. Earlier architecture reports describe their
historical milestone; this is the current integration map.

The API authenticates a principal and derives its tenant. A registered scenario or
approved domain defines permitted evidence operations. LangGraph owns workflow
execution; deterministic mathematics owns probability updates and decisions.
Historical facts and document matching take a factual branch with a provenance
gate. PostgreSQL jobs and checkpoints provide durable background execution.

## 1. System

```mermaid
flowchart TD
  UI[Browser and HTTP clients] --> API[FastAPI authentication and tenant scope]
  API --> Registry[Scenario and domain registry]
  API --> Jobs[PostgreSQL jobs and audit]
  Jobs --> Workers[Independent workers]
  Registry --> Workflow[LangGraph]
  Workers --> Workflow
  Workflow --> Math[Bayesian update and POMDP planner]
  Workflow --> Tools[Registered tenant-scoped tools]
  Tools --> Graph[Neo4j evidence graph]
  Graph --> Gate[Source and evidence gate]
  Math --> Gate
  Gate --> Result[ANSWER or ABSTAIN]
  Result --> Explain[Grounding validation and deterministic fallback]
```

## 2. Investigation loop

```mermaid
flowchart LR
  Prior[Validated prior] --> Plan[Bellman expected utility]
  Plan -->|Investigate| Act[Permitted action and cost]
  Act --> Obs[Verified observation token]
  Obs --> Bayes[Normalize prior times likelihood]
  Bayes --> Plan
  Plan -->|Stop| Gate[Evidence sufficiency]
  Gate --> Answer[ANSWER or ABSTAIN]
```

The hidden state stays fixed in the bounded investigation model. Distinct modeled
observations assume conditional independence; source groups prevent treating copied
evidence as fresh support. A prediction is not a verified historical outcome.

## 3. Provenance

```mermaid
flowchart LR
  Source[Original bytes and hash] --> Parse[Bounded typed parser]
  Parse --> Candidate[Candidate with exact location]
  Candidate --> Review[Authorized human review]
  Review --> Fact[Published graph fact and evidence]
  Fact --> Check[Active version and hash checks]
  Check --> Gate[Claim-specific evidence gate]
```

## 4. Durable jobs

```mermaid
stateDiagram-v2
  [*] --> QUEUED
  QUEUED --> RUNNING: atomic lease and fence
  QUEUED --> CANCELLED
  RUNNING --> COMPLETED
  RUNNING --> RETRY_WAIT: bounded replay-safe failure
  RETRY_WAIT --> RUNNING
  RUNNING --> FAILED
  RUNNING --> CANCEL_REQUESTED
  CANCEL_REQUESTED --> CANCELLED: safe boundary
  RUNNING --> NEEDS_RECONCILIATION: uncertain effect
```

## 5. Domain governance

```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> VALIDATED
  VALIDATED --> REVIEW_PENDING
  REVIEW_PENDING --> APPROVED: reviewer permission
  APPROVED --> ACTIVE: explicit activation
  ACTIVE --> RETIRED
  ACTIVE --> REVALIDATION_REQUIRED
```

The service retains legacy PROVISIONAL calibrated candidates and exact-version
rollback. Upload endpoints cannot grant approval or overwrite reviewed metadata.

## 6. Supported deployment

```mermaid
flowchart TD
  Local[Local browser] -->|localhost port| API[One non-root API process]
  API --> PG[Private PostgreSQL service]
  API --> Neo[Private Neo4j service]
  API --> Docs[Private document volume]
  W1[Worker 1] --> PG
  W2[Worker 2] --> PG
  W1 --> Neo
  W2 --> Neo
  W1 --> Docs
  W2 --> Docs
```

Only the API is published, on loopback. The worker has no HTTP health endpoint;
operations health checks its durable heartbeat. Authentication, throttling and
synchronous traces are process-local. Jobs, operational audit and PostgreSQL
workflow checkpoints persist independently. Filesystem metadata uses atomic writes,
not a distributed document database.

## 7. Human review

```mermaid
sequenceDiagram
  participant Author
  participant API
  participant Store
  participant Reviewer
  participant Graph
  Author->>API: Upload validated source
  API->>Store: Bytes, hash and candidate locations
  Reviewer->>API: Approve or reject with authorization
  API->>Store: Reviewer identity and decision
  API->>Graph: Publish approved fact and evidence
  Note over Store,Graph: Interrupted publication fails closed for reconciliation
```

No component shown here certifies source truth. A hash verifies byte consistency;
review and provenance establish the recorded support, not universal factual truth.
