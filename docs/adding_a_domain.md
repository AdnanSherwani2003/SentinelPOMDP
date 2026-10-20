# Adding a domain

1. Define a bounded business question and supported outcomes.
2. Decide whether it is a factual check or a genuinely uncertain prediction.
3. Identify required and optional evidence, source dependencies and provenance.
4. Add typed source-to-graph mappings; do not add arbitrary Cypher.
5. Choose only server-registered evidence tools.
6. Define the deterministic evidence-sufficiency policy.
7. Add priors and likelihoods only when defensible calibration data exists.
8. Validate the draft, inspect findings, and submit it for review.
9. Have an authorized reviewer approve and explicitly activate a version.
10. Run a version-pinned investigation and inspect evidence and audit records.

A hidden state is the uncertain condition that a probabilistic investigation tries to
infer. An investigation action is useful to a POMDP only when its possible
observations, observation model and cost are known. Ordinary database retrieval is a
factual tool, not automatically an information-gathering POMDP action.

Source independence matters because a CSV and a report copied from that CSV are not
two witnesses. Sentinel retains source groups and deduplicates them; where dependence
cannot be resolved, a probabilistic pack must use a combined model or abstain.

The shared runtime selects an approved tenant pack, pins its version, checks its tool
allow-list, and invokes its registered adapter. A factual adapter returns a typed
evidence verdict. A probabilistic pack enters the existing LangGraph/POMDP workflow;
the mathematical engine remains unchanged.
