# Pilot dataset intake specification

## Purpose and authorization

Every dataset must identify one tenant, one domain, one immutable version, its classification, the legal or organizational basis for use, and its retention policy. `authorized_use=false` is rejected. Cross-tenant pooling is not supported.

Required intake evidence for an organizational pilot:

- written authorization covering calibration and held-out evaluation;
- a data owner and retention/deletion contact;
- time-bounded source records with stable pseudonymous identifiers;
- an outcome-labeling source that is not merely the same evidence the agent sees;
- source-family and upstream-system identifiers needed to assess dependence;
- operational action availability and why an action was or was not performed;
- business costs supplied by stakeholders or documented operational proxies.

Document bodies are not part of privacy-safe evaluation output.

## Case contract

A `PilotCase` identifies the shipment/incident grouping, event time, claim type, entity, subgroup, label status, independently reviewed outcome, label provenance, and optional business costs. Definitive labels require independent ground-truth provenance. `evaluation_view()` removes labels and label sources before replay.

Factual delivery timeliness and causal attribution are distinct claim types. A late receipt can label timeliness, but cannot by itself label why a production disruption occurred.

## Observation contract

A `PilotObservation` records an action actually taken, its observed categorical outcome, observation time, whether it was available at decision time, document and source group, upstream origin, missingness reason, and action-selection mechanism. An unobserved action cannot contain a token. This prevents invented counterfactual evidence.

## Label rubric

1. Reviewers inspect authoritative operational outcomes independently of extraction review.
2. Each review records a pseudonymous reviewer reference, method, sources, timestamp, and label.
3. Disagreement becomes `DISPUTED`, never a majority label silently.
4. A distinct adjudicator may establish `ADJUDICATED`, with authoritative provenance, or `UNKNOWN`.
5. `UNLABELED`, `DISPUTED`, and `UNKNOWN` cases are excluded from metrics requiring definitive truth.

## Leakage controls

The default manifest groups records by shipment/incident and assigns whole groups chronologically. Training estimates parameters, validation selects thresholds, and test data is scored once for reporting. A manifest is rejected if any leakage group crosses splits or its dataset version differs.

Supplier or organization holdouts require enough separately authorized data and must use a new manifest strategy. Random document-level splitting is prohibited.

## Minimum statistical intake

The software reports sparse classes and action/state combinations and rejects candidates below configured counts. Numerical minimums are evaluation settings, not universal guarantees. A real pilot should justify them from the intended error tolerance, class balance, subgroup claims, and expected missingness before data collection.
