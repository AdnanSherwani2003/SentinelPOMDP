# Domain-pack contract

Implementation 19 extends the existing `DomainPack`; it does not introduce a second
configuration system. A pack is declarative, tenant-scoped, versioned and validated
by Pydantic with unknown fields rejected.

## Modes

- `FACTUAL` compares approved records. It requires a typed `factual_policy` and must
  not contain priors, likelihoods or POMDP actions.
- `PROBABILISTIC` requires at least two hypotheses, a normalized prior, complete
  likelihood rows, registered actions, valid costs and an answer threshold.

The distinction prevents a date comparison or invoice reconciliation from being
misrepresented as a Bayesian forecast.

## Safe declarations

Mappings declare source fields, entity/relation types, data types, validation rules,
row locators, availability fields and source groups. Tools are selected from the
server allow-list. Packs cannot contain Python, shell, dynamic imports, expressions
or Cypher templates; extra fields are rejected.

Approved semantic content has a SHA-256 `immutable_version_id`. Lifecycle metadata
may change, but changing evidence rules, mappings, tools, probabilities, tolerances
or other semantics requires a new `model_version`.

## Mathematical validation

Probabilistic packs require nonnegative priors totaling one; the same hypothesis set
in all likelihood tables; complete observation distributions totaling one; known
observation tokens; unique actions; supported costs, discount and horizon; and
consistent rewards. Empirical packs still require the Implementation 15 calibration
approval. Factual packs use exact decimal tolerances and never receive synthetic
probabilities.

Numeric values must be finite. Supported reward keys are `correct_answer_reward`,
`incorrect_answer_penalty`, and `abstain_reward`; the penalty is nonnegative.
Probabilistic configuration is passed to the existing planner. Defaults retain
discount `.95`, horizon `2`, correct reward `5`, incorrect penalty `7`, and abstain
reward `0`. Approved pack parameters take precedence over a caller's planner horizon.

## Lifecycle

`DRAFT → VALIDATED → REVIEW_PENDING → APPROVED → ACTIVE`.

An active version can become `REVALIDATION_REQUIRED` or `RETIRED`. Existing
`PROVISIONAL` calibrated packs remain supported. Validation is not approval;
activation is explicit; retired or revalidation-required versions cannot start a new
investigation.
