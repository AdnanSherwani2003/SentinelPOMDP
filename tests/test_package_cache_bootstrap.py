"""Command/environment boundaries of the explicit package-cache bootstrap."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


def load_bootstrap():
    path = Path(__file__).resolve().parents[1] / "scripts/prepare_package_test_cache.py"
    spec = importlib.util.spec_from_file_location("package_cache_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_uses_locked_hashed_runtime_and_strips_application_credentials(tmp_path, monkeypatch):
    bootstrap = load_bootstrap()
    (tmp_path / "uv.lock").touch()
    (tmp_path / "pyproject.toml").touch()
    calls = []
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "uv")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-do-not-forward")
    monkeypatch.setenv("SENTINEL_OPERATIONS_DATABASE_URL", "synthetic-do-not-forward")
    monkeypatch.setenv("VIRTUAL_ENV", "synthetic-original-environment")
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda args, **kw:
        calls.append((args, kw)) or subprocess.CompletedProcess(args, 0))
    bootstrap.prepare_cache(tmp_path, tmp_path / "explicit-cache")
    assert len(calls) == 3
    assert calls[0][0][1:6] == ["export", "--frozen", "--no-dev", "--no-editable", "--no-emit-project"]
    assert calls[1][0][1] == "venv"
    assert calls[2][0][1:5] == ["pip", "install", "--no-deps", "--require-hashes"]
    for _, options in calls:
        assert options["cwd"] == tmp_path.resolve()
        assert options["env"]["UV_CACHE_DIR"] == str((tmp_path / "explicit-cache").resolve())
        assert options["env"]["UV_OFFLINE"] == "1"
        assert "GROQ_API_KEY" not in options["env"]
        assert "SENTINEL_OPERATIONS_DATABASE_URL" not in options["env"]
        assert "VIRTUAL_ENV" not in options["env"]


def test_bootstrap_failure_is_not_suppressed_or_logged_with_sensitive_stderr(tmp_path, monkeypatch):
    bootstrap = load_bootstrap()
    (tmp_path / "uv.lock").touch()
    (tmp_path / "pyproject.toml").touch()
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "uv")
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda args, **kw:
        subprocess.CompletedProcess(args, 1, stderr=b"synthetic-private-index-credential"))
    with pytest.raises(RuntimeError, match="locked export.*exit 1") as error:
        bootstrap.prepare_cache(tmp_path)
    assert "synthetic-private-index-credential" not in str(error.value)


def test_ci_always_runs_bootstrap_and_the_opted_in_cold_cache_regression():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text()
    assert workflow.index("uv sync --frozen --group dev") < workflow.index("scripts/prepare_package_test_cache.py")
    assert workflow.index("scripts/prepare_package_test_cache.py") < workflow.index("Cold-cache packaging regression")
    assert 'RUN_COLD_CACHE_PACKAGING_TESTS: "1"' in workflow
    assert "tests/test_packaged_application.py::test_fresh_cache_bootstrap_and_offline_artifact_install" in workflow
    assert "Offline regression including isolated installed-package tests" in workflow
