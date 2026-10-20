"""Prepare locked runtime dependencies before offline installed-package tests.

Run after `uv sync --frozen --group dev`. This explicit bootstrap may access the
package registry; it never starts the application or connects to a database/LLM.
The subsequent packaging tests retain their offline, isolated installations.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def prepare_cache(project: Path, cache_dir: Path | None = None) -> None:
    project = project.resolve()
    if not (project / "uv.lock").is_file() or not (project / "pyproject.toml").is_file():
        raise ValueError("Package cache bootstrap requires pyproject.toml and uv.lock")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("Package cache bootstrap requires uv")
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ("SENTINEL_", "NEO4J_", "OPENAI_", "GROQ_", "RUN_LIVE_", "LANGSMITH_"))
        and k not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    env.update(PYTHONDONTWRITEBYTECODE="1", LANGSMITH_TRACING="false", UV_PYTHON_DOWNLOADS="never")
    if cache_dir is not None:
        env["UV_CACHE_DIR"] = str(cache_dir.resolve())
    # Honor an existing UV_OFFLINE setting: never silently enable networking.
    with TemporaryDirectory(prefix="sentinel-package-cache-") as temporary:
        work = Path(temporary)
        requirements = work / "runtime-requirements.txt"
        venv = work / "seed"
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        commands = (
            ("locked export", [uv, "export", "--frozen", "--no-dev", "--no-editable", "--no-emit-project",
                               "--format", "requirements-txt", "--output-file", str(requirements)]),
            ("temporary environment", [uv, "venv", "--python", sys.executable, str(venv)]),
            ("locked runtime cache", [uv, "pip", "install", "--no-deps", "--require-hashes",
                                      "--python", str(python), "--requirement", str(requirements)]),
        )
        for phase, command in commands:
            result = subprocess.run(command, cwd=project, env=env, capture_output=True, timeout=240)
            if result.returncode:
                # Never echo inherited credentials, private index URLs or backend diagnostics.
                raise RuntimeError(f"Package cache bootstrap failed during {phase} (exit {result.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--cache-dir", type=Path, help="Optional dedicated uv cache; never cleared")
    args = parser.parse_args()
    prepare_cache(args.project, args.cache_dir)
    print("Locked runtime cache prepared; isolated package installation tests can now run offline.")


if __name__ == "__main__":
    main()
