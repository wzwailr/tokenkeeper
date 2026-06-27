from __future__ import annotations

import importlib.metadata as metadata
import subprocess
import sys
import zipfile
from pathlib import Path

import tokenkeeper


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_version_matches_distribution_metadata() -> None:
    assert tokenkeeper.__version__ == metadata.version("tokenkeeper-ai")


def test_dashboard_package_is_in_built_wheel() -> None:
    subprocess.run([sys.executable, "-m", "build", "--wheel"], cwd=ROOT, check=True)
    wheel = sorted((ROOT / "dist").glob("tokenkeeper_ai-*.whl"))[-1]
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
    assert "tokenkeeper/dashboard/app.py" in names
    assert "tokenkeeper/dashboard/__init__.py" in names


def test_cli_version_uses_runtime_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tokenkeeper.cli", "version"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert result.stdout.strip() == f"tokenkeeper {tokenkeeper.__version__}"
