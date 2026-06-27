from __future__ import annotations

import importlib
import sys

import tokenkeeper


def test_dashboard_module_imports_without_unloading_tokenkeeper() -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    assert callable(module._get_db_path)
    assert sys.modules["tokenkeeper"] is tokenkeeper
