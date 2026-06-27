from __future__ import annotations

import importlib
import sys

import tokenkeeper


def test_dashboard_module_imports_without_unloading_tokenkeeper() -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    assert callable(module._get_db_path)
    assert sys.modules["tokenkeeper"] is tokenkeeper


def test_dashboard_hermes_sync_uses_selected_db(monkeypatch, tmp_path) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    selected_db = tmp_path / "selected-dashboard.db"
    captured = {}

    def fake_sync(*, tk_db_path: str) -> int:
        captured["tk_db_path"] = tk_db_path
        return 3

    monkeypatch.setattr(module, "_get_db_path", lambda: str(selected_db))
    monkeypatch.setattr(
        "tokenkeeper.integrations.hermes_connector.sync_hermes_to_tokenkeeper",
        fake_sync,
    )

    assert module._sync_hermes_for_dashboard() == 3
    assert captured["tk_db_path"] == str(selected_db)


def test_dashboard_hermes_sync_skips_postgres(monkeypatch) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")

    def fail_sync(*, tk_db_path: str) -> int:
        raise AssertionError("postgres dashboards should not use Hermes SQLite sync")

    monkeypatch.setattr(
        "tokenkeeper.integrations.hermes_connector.sync_hermes_to_tokenkeeper",
        fail_sync,
    )

    assert module._sync_hermes_for_dashboard("postgresql://localhost/tokenkeeper") == 0
