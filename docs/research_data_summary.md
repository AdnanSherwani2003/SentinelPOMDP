# Public research-data summary

This is an aggregate-only companion to the [evaluation summary](evaluation_summary.md).
Original files and row-level operational evidence are private; see
[data attribution](data_sources_and_attribution.md).

The Olist source release has nine tables: 99,441 orders, 112,650 order items,
99,441 customer records, 3,095 sellers, 32,951 products, 103,886 payment rows,
99,224 reviews, 1,000,163 geolocation rows and 71 translation rows.

Archive SHA-256:
`967e41e04fc306fe604e2a693f488995a8b41e5047418f8a5c8e4abd6deca784`.
Orders-table SHA-256:
`8df58ef3d2d7e9944010f7beecd9b75367f5588ec6e3c91cec19ae3345ef9ecf`.
Hashes identify the locally evaluated source version, not proof of source truth
or permission to redistribute its contents.

All orders are mutually accounted for: 96,221 prediction-eligible; 2,965 missing
or invalid customer-delivery dates; 249 invalid date orderings; 6 with a
non-delivered final status. Total: 99,441. The additional exclusion difference of
255 is 249 + 6, not an unexplained loss of records.

The retained bounded research graph contained 100 orders with 545 approved review
candidates, 602 entities, 545 facts, 215 evidence nodes, 2 documents and 1,850
relationships. Read-only acceptance verified supported late and on-time historical
lookups, missing outcomes, source-row integrity, cross-tenant denial and prospective
abstention with no activated predictive model. No original order IDs or rows are
published in this summary. No further persistent import was needed for release
preparation. Evaluation measurements do not establish counterfactual POMDP value.
