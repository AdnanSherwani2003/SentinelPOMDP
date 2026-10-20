# Olist results

The source archive contains 99,441 orders, 112,650 items, 99,441 customer records, 3,095 sellers, 32,951 products, 103,886 payment rows, 99,224 reviews, 1,000,163 geolocation rows, and 71 translations. Purchase dates range from 2016-09-04 to 2018-10-17.

The read-only evaluator does not publish graph facts. Reviewed import acceptance
is described without original rows in the [public research summary](research_data_summary.md).
Full operational exports stay private. The separately obtained archive remains intact.

The chronological eligible-order split is 57,732 training, 19,244 validation, and 19,245 held-out test cases. The carrier-handoff model's smoothed training late prior is 0.0676551. The validation-selected answer threshold is 0.6. On test, the schedule-margin baseline has Brier score 0.042159, log loss 0.170223, coverage 0.869888, selective accuracy 0.985903, wrong-answer rate 0.012263, and abstention rate 0.130112. The simpler prior-only baseline has better probability scores: Brier 0.034771 and log loss 0.161653. Selective accuracy cannot be compared without considering the differing coverage.

The one-step POMDP with the evidence gate abstains. A schedule margin is a feature correlated with lateness, but it is not independent evidence that an order actually arrived late. The dataset does not support an honest multi-step counterfactual policy comparison. The observational likelihoods are not activated as an operational domain pack.

These numbers describe this historical dataset, split, proxy label, and small feature channel. They do not show causal seller responsibility, independently confirmed delivery, counterfactual POMDP action value, generalization to a current business, or production capacity.
