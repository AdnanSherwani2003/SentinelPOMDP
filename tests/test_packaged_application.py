"""Build/install real artifacts without relying on editable source or local data.

Run `uv sync --frozen --group dev` first. Dependencies/build requirements must be
available in uv's cache; these regressions do not contact an LLM or existing DB.
Optional PostgreSQL checks require a separately provisioned disposable database.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from urllib.parse import urlsplit
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = (
    "operations/migrations/001_initial_sqlite.sql",
    "operations/migrations/001_initial_postgres.sql",
    "web/index.html", "web/app.js", "web/styles.css",
)


def clean_environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ("SENTINEL_", "NEO4J_", "OPENAI_", "GROQ_", "RUN_LIVE_"))
        and k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    env.update(PYTHONDONTWRITEBYTECODE="1", UV_OFFLINE="1", LANGSMITH_TRACING="false")
    return env


def run(*args, cwd, env=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd,
        env=env or clean_environment(), capture_output=True, text=True, timeout=240)
    # Child commands contain no credentials. Do not expose inherited environment
    # values or potentially sensitive backend diagnostics through test failures.
    assert result.returncode == 0, f"Isolated package command failed: {Path(str(args[0])).name} (exit {result.returncode})"
    return result.stdout


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("packaging regression requires uv; install the documented developer tool")
    work = tmp_path_factory.mktemp("sentinel-package")
    source = work / "source"
    source.mkdir()
    for name in ("pyproject.toml", "uv.lock", "README.md", "LICENSE", "NOTICE"):
        shutil.copy2(ROOT / name, source / name)
    # No existing egg-info/SOURCES cache, Git index, private data or environment.
    shutil.copytree(ROOT / "src" / "sentinel_pomdp", source / "src" / "sentinel_pomdp",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    dist = work / "dist"
    run(uv, "build", "--offline", "--out-dir", dist, cwd=source)
    wheel = next(dist.glob("*.whl"))
    sdist = next(dist.glob("*.tar.gz"))
    rebuilt = work / "rebuilt"
    run(uv, "build", sdist, "--wheel", "--offline", "--out-dir", rebuilt, cwd=work)
    requirements = work / "runtime-requirements.txt"
    run(uv, "export", "--frozen", "--no-dev", "--no-editable", "--no-emit-project",
        "--format", "requirements-txt", "--output-file", requirements, cwd=source)
    return {"uv": uv, "work": work, "wheel": wheel, "sdist": sdist,
            "sdist_wheel": next(rebuilt.glob("*.whl")), "requirements": requirements}


def test_wheel_contains_exact_runtime_resources_and_license(artifacts):
    for key in ("wheel", "sdist_wheel"):
        with zipfile.ZipFile(artifacts[key]) as archive:
            for name in RESOURCES:
                assert archive.read("sentinel_pomdp/" + name) == (ROOT / "src/sentinel_pomdp" / name).read_bytes()
            license_path = next(n for n in archive.namelist() if n.endswith(".dist-info/licenses/LICENSE"))
            assert archive.read(license_path) == (ROOT / "LICENSE").read_bytes()
            notice_path = next(n for n in archive.namelist() if n.endswith(".dist-info/licenses/NOTICE"))
            assert archive.read(notice_path) == (ROOT / "NOTICE").read_bytes()
            assert not any("__pycache__" in n or n.endswith((".pyc", ".env", ".db", ".dump", ".zip"))
                           for n in archive.namelist())


def test_sdist_contains_exact_runtime_resources(artifacts):
    with tarfile.open(artifacts["sdist"]) as archive:
        prefix = archive.getnames()[0].split("/")[0]
        for name in RESOURCES:
            assert archive.extractfile(prefix + "/src/sentinel_pomdp/" + name).read() == (ROOT / "src/sentinel_pomdp" / name).read_bytes()
        assert archive.extractfile(prefix + "/LICENSE").read() == (ROOT / "LICENSE").read_bytes()
        assert archive.extractfile(prefix + "/NOTICE").read() == (ROOT / "NOTICE").read_bytes()


def test_confirmed_project_notice_is_scoped_and_consistent():
    identifier = "AdnanSherwani2003"
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert f"Copyright 2026 {identifier}" in notice
    assert "only to original SentinelPOMDP material" in notice
    assert "not to\nthird-party code, dependencies, or datasets" in notice
    assert "CC BY-NC-SA 4.0" in notice
    assert "not redistributed" in notice
    assert identifier not in (ROOT / "LICENSE").read_text(encoding="utf-8")
    for path in ("README.md", "docs/data_sources_and_attribution.md", "docs/release_validation.md"):
        content = (ROOT / path).read_text(encoding="utf-8")
        assert identifier in content
        assert "identification remains pending" not in content


@pytest.fixture(scope="module", params=("wheel", "sdist_wheel"))
def installed(request, artifacts):
    work = artifacts["work"] / request.param
    work.mkdir()
    venv = work / "venv"
    run(artifacts["uv"], "venv", "--python", sys.executable, venv, cwd=work)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run(artifacts["uv"], "pip", "install", "--offline", "--no-deps", "--python", python,
        "--requirement", artifacts["requirements"], artifacts[request.param], cwd=work)
    return python, work


SQLITE_AND_API_PROBE = r'''
import hashlib, json, secrets, sys
from pathlib import Path
import sentinel_pomdp
from sentinel_pomdp.operations.models import NewOperationJob, OperationType
from sentinel_pomdp.operations.repository import SQLiteOperationRepository
from sentinel_pomdp.api.app import create_app
from sentinel_pomdp.api.settings import AppSettings
from fastapi.testclient import TestClient

package = Path(sentinel_pomdp.__file__).resolve().parent
assert package.is_relative_to(Path(sys.prefix).resolve())
for name, digest in json.loads(sys.argv[1]).items():
    assert hashlib.sha256((package / name).read_bytes()).hexdigest() == digest
path = Path.cwd() / "isolated-operations.db"
repo = SQLiteOperationRepository(path)
request = NewOperationJob(tenant_id="synthetic-package", principal_id="synthetic-reviewer",
    operation_type=OperationType.INVESTIGATION, correlation_id="package-smoke",
    payload={"scenario_id":"supplier_a_shipment_delay"}, idempotency_key="package-smoke")
job, created = repo.create_job(request)
assert created
assert repo.create_job(request)[0].job_id == job.job_id
assert repo.get_job("other-tenant", job.job_id) is None
repo.close()
repo = SQLiteOperationRepository(path)
assert repo.get_job(request.tenant_id, job.job_id).job_id == job.job_id
repo.close()
key = secrets.token_urlsafe(32)
settings = AppSettings(api_key=key, provider="fake", backend="memory",
    document_store_path=str(Path.cwd()/"synthetic-documents"),
    operations_database_path=str(Path.cwd()/"api-operations.db"))
with TestClient(create_app(settings)) as client:
    assert client.get("/health/live").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/api/v1/session").status_code == 401
    response = client.post("/api/v1/investigations", json={"question":"Was Supplier A's shipment late?"},
        headers={"Authorization":"Bearer "+key})
    assert response.status_code == 200 and response.json()["decision"] == "ANSWER"
print("isolated installed SQLite initialization/reopen, resources, tenant denial and fake-provider API: PASS")
'''


def test_installed_application_initializes_sqlite_and_serves_api(installed):
    python, work = installed
    digests = {name: hashlib.sha256((ROOT / "src/sentinel_pomdp" / name).read_bytes()).hexdigest()
               for name in RESOURCES}
    assert "PASS" in run(python, "-I", "-B", "-c", SQLITE_AND_API_PROBE, json.dumps(digests), cwd=work)


@pytest.mark.live_operations
def test_installed_application_initializes_disposable_postgres(installed):
    url = os.getenv("SENTINEL_PACKAGE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("SENTINEL_PACKAGE_TEST_POSTGRES_URL requires an explicitly disposable sentinel_package_test database")
    assert urlsplit(url).path.removeprefix("/").startswith("sentinel_package_test"), "Refusing a non-disposable database"
    python, work = installed
    env = clean_environment()
    env["SENTINEL_PACKAGE_TEST_POSTGRES_URL"] = url
    probe = r'''
import os, sys
from pathlib import Path
from uuid import uuid4
import sentinel_pomdp
from sentinel_pomdp.operations.postgres import PostgresOperationRepository
from sentinel_pomdp.operations.models import NewOperationJob, OperationType
assert Path(sentinel_pomdp.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
url = os.environ["SENTINEL_PACKAGE_TEST_POSTGRES_URL"]
tenant = "synthetic-package-" + uuid4().hex
repo = PostgresOperationRepository(url)
request = NewOperationJob(tenant_id=tenant, principal_id="synthetic-reviewer",
    operation_type=OperationType.INVESTIGATION, correlation_id="package-smoke",
    payload={}, idempotency_key="package-smoke")
job, created = repo.create_job(request)
assert created and repo.create_job(request)[0].job_id == job.job_id
assert repo.get_job("other-tenant", job.job_id) is None
repo.close()
repo = PostgresOperationRepository(url)
assert repo.get_job(tenant, job.job_id).job_id == job.job_id
repo.close()
print("isolated installed PostgreSQL initialization/reopen/idempotency/tenant denial: PASS")
'''
    assert "PASS" in run(python, "-I", "-B", "-c", probe, cwd=work, env=env)
