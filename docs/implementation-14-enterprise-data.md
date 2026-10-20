# Implementation 14: enterprise data onboarding

SentinelPOMDP accepts tenant-scoped CSV, PDF, XLSX, DOCX, and UTF-8 text files through the authenticated API. Uploaded bytes are stored in a private local volume, separated by a hash of the trusted tenant identity. The API never accepts a tenant identifier from an upload request and never returns a filesystem path.

## Trust boundary

- Parsers are deterministic and bounded. Office macros, links, embedded programs, arbitrary URLs, and model-controlled tools are not executed.
- PDF input must contain extractable text. Image-only documents receive `OCR_REQUIRED`; the system does not silently trust OCR.
- Every normalized value retains a document version, exact source text, and page, sheet/row, paragraph, or line locator.
- Extracted facts remain `NEEDS_REVIEW`. Only a principal with `evidence:review` and the `reviewer` role can publish them.
- Replacement files supersede the prior version. Withdrawal deactivates the document and its evidence; subsequent investigations cannot count it.
- A source group represents one independently generated information source. Multiple files from the same export do not satisfy a multi-source evidence rule.

## Reasoning modes

`document_lookup` returns approved records and citations without a probabilistic claim. It is explicitly marked `calibrated: false`.

`domain_pomdp` accepts only a stored, approved domain pack. Packs contain reviewer-authored hypotheses, priors, observation likelihoods, action costs, answer threshold, independent-source requirement, model version, and calibration note. Validation requires normalized probability rows and a named approver. The LLM cannot alter any of these values or select POMDP actions.

`registered_pomdp` remains the Implementation 10–13 demonstration path.

## Local reproduction (PowerShell)

```powershell
$env:SENTINEL_API_KEY = '<32+-character-local-key>'
$env:SENTINEL_ROLES = 'analyst,reviewer'
$env:SENTINEL_PERMISSIONS = 'investigation:execute,evidence:read,provenance:read,trace:read,workflow:resume,document:upload,document:read,evidence:review,domain-pack:manage'
$env:SENTINEL_DOCUMENT_STORE = 'data/company_documents'
uv run python scripts/run_api.py
```

Open `http://127.0.0.1:8000`, authenticate, create the standard delivery mapping, and upload an expected-date file plus an actual-date file. Review the generated candidate before using document lookup or a separately approved domain pack.

Run offline tests with `uv run pytest -q`. Live Neo4j tests run automatically when `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` point to a reachable service. External LLM tests remain separately opt-in and are not required for document-derived deterministic reasoning.

## Operational limitations

The bundled document store is appropriate for a single application instance. A production multi-instance deployment should replace it with encrypted object storage plus transactional metadata storage, malware scanning, retention jobs, centralized audit export, backup/restore, and key management. Domain probabilities remain reviewer-authored assumptions until calibrated and validated against representative data; this implementation does not claim benchmark improvement.
