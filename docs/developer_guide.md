# Developer guide

Install the locked development group with `uv sync --frozen --group dev`. The dev
group now includes pytest, so tests do not rely on an earlier global installation.
Python 3.13 is the tested interpreter. Build a package with `uv build`; the wheel
includes browser assets, both SQL migrations, LICENSE and the scoped project NOTICE.
Raw data and local credentials do
not belong in the wheel, source archive or Git index.

Core mathematics lives in belief/information/decision/planner/multistep modules.
Investigation schemas and evidence policy bind those calculations to approved graph
observations. LangGraph wraps the execution loop. Ingestion separates candidates
from publication. Domains extend the existing typed pack and registered adapters.
The API derives tenant scope from a verified principal. Operations provides the
durable job/journal interface for independent workers.

Before changes, run the tests for the affected boundary. Use fake providers and
disposable stores. For a full offline run, use `uv run pytest -q -rs`. For isolated
installation without your archive or credentials:

```powershell
powershell -NoProfile -File scripts/verify_clean_install.ps1
powershell -NoProfile -File scripts/verify_multidomain_live.ps1
uv run python scripts/audit_release.py
uv run pytest -q -rs tests/test_packaged_application.py
```

The clean-install script exports source files into a new ignored directory and
installs a fresh environment. It does not alter the Git index. The live script
creates its own containers on test ports and stops only containers it created.
Never point destructive live fixtures at the research database: some test modules
truncate their explicitly disposable PostgreSQL tables.
Clean-install output defaults to a new ignored local report directory; an optional
`-JUnitXml` chooses a new report path. Existing reports are not overwritten.

The packaged-application regressions build from a clean source copy, inspect the
wheel/sdist, rebuild a wheel from the sdist, then install each wheel into a separate
virtual environment. They verify runtime hashes, SQLite schema initialization and
reopen, tenant denial, static assets and a fake-provider API answer without
editable-source fallback. They use uv's offline cache: run the locked sync above
first. The optional PostgreSQL cases require an explicitly disposable database
whose name starts with `sentinel_package_test`; never use research/production
credentials. Missing opt-in is a reported skip, not proof of PostgreSQL startup.

For the retained, lockfile-based Mermaid checker, see [diagram verification](diagram_verification.md).

An idempotent operation returns the original logical result for the same key/input;
changed input under that key is a conflict. A checkpoint records workflow progress.
A lease/fence proves which worker currently owns a job. An uncertain external effect
requires reconciliation instead of blind retry. Test these properties when adding
a handler. Do not duplicate Bayesian updates or use outcome labels as features.

Domain uploads enter as drafts on both API routes. Approval and activation use the
protected lifecycle endpoints. See domain_pack_schema.md and adding_a_domain.md.

Release preparation is manual: review a locally generated exact-path manifest,
exclude generated files already tracked, inspect reports for source content, then ask the
owner before staging uncertain files, committing, tagging or publishing. Git ignore
rules do not remove tracked files. Remote CI is configured but has not been
triggered in I20; no push was made to create a green badge.
Local audit inventories, original-row evidence and raw test logs are ignored, not
public developer prerequisites. See [public validation](release_validation.md).
