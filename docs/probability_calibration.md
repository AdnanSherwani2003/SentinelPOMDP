# Probability calibration, in plain language

## Ground truth

Ground truth is the independently reviewed answer used only for scoring. For shipment `PO-42`, an authoritative receiving reconciliation might establish `delayed`. The POMDP sees the warehouse observation, not that hidden label. Keeping them separate prevents circular evaluation.

## Priors

A prior is the delayed/on-time rate before this investigation's evidence. The estimator counts approved training cases only and applies symmetric Dirichlet smoothing, so a zero count does not become impossible probability. Wilson intervals show that estimates from small samples are uncertain. A historical rate is population-specific; it is not automatically transferable to another supplier, period, or organization.

## Observation likelihoods

A likelihood answers questions such as: “Among shipments independently known to be delayed, how often did `inspect_delivery` return `EVIDENCE_SUPPORTED`?” Counts are conditioned on action and hidden state. Missing actions remain missing. The estimator records selection mechanisms because inspections triggered only by suspected problems are biased observations.

## Held-out calibration

- Multiclass Brier score averages the squared distance between the full predicted distribution and the true one-hot outcome. Lower is better.
- Log loss heavily penalizes assigning tiny probability to what happened. Lower is better.
- Reliability bins compare confidence with observed accuracy. ECE summarizes bin gaps but is not sufficient by itself.
- Coverage is the fraction answered.
- Selective accuracy is accuracy among answered cases.
- Unsupported-answer rate is the fraction answered without satisfying the deterministic evidence gate.

Thresholds are selected on validation data. The test split reports final performance and is not used to tune the threshold.

## Source correlation

Three files can repeat one warehouse observation. Source groups and upstream origins represent that dependency. Hashes detect exact duplicates, not genuine independence. Unknown dependency is a warning; it is not assumed independent. Correlated sources cannot satisfy a multi-source gate merely by being separate files.

## Governance

An empirical estimate creates a `PROVISIONAL` pack with dataset version, method, counts, intervals, validation results, limitations, and model version. It is inactive until a principal with `model:approve` and the reviewer role approves it. Mathematical parameters cannot be rewritten under the same version. Withdrawal of calibration-source data retires affected empirical models for revalidation. Historical traces retain the model version used.
