# Controlled company-pilot readiness

## Current assessment

Engineering readiness: **PARTIALLY COMPLETE**. The bounded intake, calibration, evaluation, approval, security, and reporting mechanisms are implemented and tested.

Real-world validation: **PENDING**. It is not blocked by a software error; it is waiting for authorized, independently labeled, sufficiently representative organizational data and defensible stakeholder costs.

## Entry criteria for a controlled pilot

- signed data-use authorization and retention/deletion rules;
- independently adjudicated outcomes with provenance;
- enough cases per state, action, time period, and claimed subgroup;
- documented action-selection bias and missingness;
- source dependency review beyond file hashes;
- pre-registered train/validation/test manifest and target metrics;
- stakeholder-approved reward/cost ranges;
- security review of storage, backup, malware scanning, and audit export;
- reviewer assignment for model activation and withdrawal impact;
- a rollback and incident-response exercise.

## Conclusions currently supported

The implementation can calculate count-based probabilities, preserve label secrecy, detect split leakage, quantify calibration/coverage, enforce evidence gates, and compare policies on identical logged cases. It safely reports when counterfactual policy effects are not identifiable.

## Conclusions not supported

It is not established that probabilities are calibrated on any organization, that POMDP investigation improves business utility, that source groups always represent true independence, or that the parser/extractor meets a production accuracy target on company documents. Causal attribution remains outside the timeliness calibration model.
