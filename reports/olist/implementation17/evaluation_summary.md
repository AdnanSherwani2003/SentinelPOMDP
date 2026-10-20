# Implementation 17 predictive evaluation

Dataset: Olist 2018; archive SHA-256 `967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784`. Eligible orders: 96221 of 99441.

## Result

The purchase-time logistic candidate achieved Brier 0.033894 and log loss 0.153764, versus prior-only Brier 0.033944 and log loss 0.154293. The candidate is **not activated**. These are held-out predictive measurements, not historical facts.

The preserved Implementation 16 schedule-margin result has Brier 0.042159 and log loss 0.170223; its prior-only comparator has Brier 0.034771 and log loss 0.161653.

## POMDP value

One-step and horizon-2 policy value are **NOT EVALUABLE**: Olist does not log outcomes for investigations that were not performed. Free attributes are features, not autonomous actions. Immediate abstention has zero coverage, N/A selective accuracy, zero cost, and zero realized utility under the fixed reward specification.

## Temporal safeguards

Seller history contains only eligible deliveries completed before each decision timestamp. Training fitting and validation tuning exclude labels not knowable by the following split boundary. Actual delivery, final status, outcome, post-delivery reviews, and future seller performance are prohibited before outcome revelation.

## Limitations

The public archive lacks operational access timestamps, so availability is reconstructed conservatively from event times. No additional persistent Neo4j orders were imported. Disposable scale measurements are local engineering measurements only.
