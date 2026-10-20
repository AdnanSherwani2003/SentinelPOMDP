# Portfolio demonstration walkthrough

Use the isolated full-stack quickstart. Label supplier and procurement fixtures
SYNTHETIC in a video. Use only screenshots from actual verified runs. Do not show
the local environment file, credentials, raw user documents or backup contents.

1. Authenticate at localhost:18082. Explain that the API supplies trusted tenant
   scope; the question does not choose a tenant.
2. Ask “Was Supplier A's shipment late?”. The tested result was ANSWER, posterior
   shipment_delayed .887, up from prior .55, and cost .080. Open a supporting
   evidence record and its exact location. The engine selected an evidence action
   and multiplied prior by the configured likelihood, then normalized.
3. Ask “Did Supplier A cause the entire production delay?”. It abstains because
   delivery evidence does not establish that causal conclusion. Show that confidence
   and evidence sufficiency are separate requirements.
4. In Domain Management select Procurement and ask “Does INV-1001 match PO-2001?”.
   The synthetic result matches quantity 2, unit price 10.00, and total 22.00 using
   decimal arithmetic. Explain the tests for mismatches, withdrawals and missing PO
   evidence. This factual check does not invent a probability of fraud.
5. Paste an invalid empty domain JSON object and show its validation rejection.
   An author uploads a draft; reviewer permission is required for approval/activation.
6. Run scripts/verify_demo.py. Operations shows a real worker-completed investigation
   and ready heartbeats. Existing recovery tests reopen checkpoints, reject stale
   fences and cancel at safe boundaries. A running job is never displayed as complete.
7. Optionally use an already authorized read-only Olist console with an imported
   order identifier supplied locally by the reviewer. Keep original source rows
   and identifiable operational results private. Show the historical/prospective
   distinction and purchase-time risk abstention without recording raw rows in a
   public video. Do not import more orders or activate a candidate.
8. Show the [public validation summary](release_validation.md): fresh synthetic graph restore, equal document hashes,
   reviewer metadata/domain versions, jobs/audit/checkpoints. Explain offline Neo4j
   Community backup and the absence of a production recovery guarantee.

Close with the research limits: synthetic policy utility depends on rewards;
immediate abstention won the retained synthetic utility comparison. Olist shows
historical data handling and a modest predictive baseline, not POMDP superiority.
