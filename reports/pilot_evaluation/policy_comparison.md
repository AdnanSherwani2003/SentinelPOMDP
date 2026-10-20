# Pilot policy comparison

Dataset classification: **SYNTHETIC_REPRESENTATIVE**

| Policy | Coverage | Selective accuracy | Brier | Mean action cost |
|---|---:|---:|---:|---:|
| immediate_abstention | 0.0000 | 0.0000 | 0.5000 | 0.0000 |
| logged_fixed_order | 0.5000 | 0.8333 | 0.2820 | 0.0800 |
| logged_greedy_information_gain | 0.5000 | 0.8333 | 0.2820 | 0.0800 |
| logged_expected_utility_h1 | 0.5000 | 0.8333 | 0.2820 | 0.0800 |
| logged_pomdp_h2 | 0.5000 | 0.8333 | 0.2820 | 0.0800 |

The one-action logged fixture cannot identify differences among investigation policies. No counterfactual observations were generated.
