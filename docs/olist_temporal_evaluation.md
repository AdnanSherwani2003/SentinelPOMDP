# Olist temporal evaluation

## Factual versus predictive mode

Historical lookup answers whether the recorded customer-delivery calendar date is after the estimated-delivery calendar date. The estimated timestamp is commonly midnight, so comparing full timestamps would incorrectly classify same-date deliveries as late. Canceled and unavailable orders are excluded; missing or inconsistent dates are unknown.

Prospective mode asks what was knowable at a decision time. PURCHASE exposes purchase time and estimate. APPROVAL adds approval time. CARRIER_HANDOFF adds carrier handoff. None exposes actual delivery, final status, final outcome, or review. DELIVERY_COMPLETED is rejected for prediction. The exported file has event timestamps but not reliable timestamps for when an investigator first saw each event; event time is an approximation of availability.

## Leakage controls

Orders are sorted by purchase time and split 60/20/20. Parameters use only training orders. The validation period chooses an answer threshold. Metrics use only the later test period. The outcome is attached only during scoring. The implemented feature channel is remaining calendar days until the estimate, bucketed as short, medium, long, or missing.

Historical seller delay features are deliberately absent from version 1. Adding them safely would require rolling, outcome-availability-aware aggregates. Review scores are excluded because they are post-delivery. This is why a correct prediction cannot be credited to future information.

## Statistics and limits

The late prior and `P(margin bucket | eventual outcome)` use Laplace smoothing. Bayesian updating yields a posterior from a recorded schedule margin. This is an empirical observational baseline, not proof that an investigation action caused an observation. The evidence-gated POMDP abstains because the margin does not prove delivery. The release has no counterfactual result for actions the agent did not take, so multi-step policy advantage is marked not estimable. The Olist delivery field is an operational proxy label, not independently audited physical-delivery ground truth.
