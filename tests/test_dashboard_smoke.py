from __future__ import annotations

import importlib
import json
import sys
import tempfile

import tokenkeeper


def test_dashboard_module_imports_without_unloading_tokenkeeper() -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    assert callable(module._get_db_path)
    assert sys.modules["tokenkeeper"] is tokenkeeper


def test_dashboard_hermes_sync_uses_selected_db(monkeypatch, tmp_path) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    selected_db = tmp_path / "selected-dashboard.db"
    captured = {}

    def fake_sync(*, tk_db_path: str, since: float | None = None) -> int:
        captured["tk_db_path"] = tk_db_path
        captured["since"] = since
        return 3

    monkeypatch.setattr(module, "_get_db_path", lambda: str(selected_db))
    monkeypatch.delenv("TOKENKEEPER_HERMES_SYNC_SINCE", raising=False)
    monkeypatch.setattr(
        "tokenkeeper.integrations.hermes_connector.sync_hermes_to_tokenkeeper",
        fake_sync,
    )

    assert module._sync_hermes_for_dashboard() == 3
    assert captured["tk_db_path"] == str(selected_db)
    assert captured["since"] is None


def test_dashboard_hermes_sync_passes_since(monkeypatch, tmp_path) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    selected_db = tmp_path / "selected-dashboard.db"
    captured = {}

    def fake_sync(*, tk_db_path: str, since: float | None = None) -> int:
        captured["tk_db_path"] = tk_db_path
        captured["since"] = since
        return 1

    monkeypatch.setattr(module, "_get_db_path", lambda: str(selected_db))
    monkeypatch.setenv("TOKENKEEPER_HERMES_SYNC_SINCE", "1782543000.5")
    monkeypatch.setattr(
        "tokenkeeper.integrations.hermes_connector.sync_hermes_to_tokenkeeper",
        fake_sync,
    )

    assert module._sync_hermes_for_dashboard() == 1
    assert captured == {"tk_db_path": str(selected_db), "since": 1782543000.5}


def test_dashboard_hermes_sync_skips_postgres(monkeypatch) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")

    def fail_sync(*, tk_db_path: str) -> int:
        raise AssertionError("postgres dashboards should not use Hermes SQLite sync")

    monkeypatch.setattr(
        "tokenkeeper.integrations.hermes_connector.sync_hermes_to_tokenkeeper",
        fail_sync,
    )

    assert module._sync_hermes_for_dashboard("postgresql://localhost/tokenkeeper") == 0


def test_dashboard_normalizes_relative_db_path(monkeypatch, tmp_path) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    monkeypatch.chdir(tmp_path)

    assert module._normalize_db_path("ledger.db") == str(
        (tmp_path / "ledger.db").resolve()
    )


def test_dashboard_cli_arg_takes_priority_over_legacy_temp_config(
    monkeypatch,
    tmp_path,
) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    selected_db = tmp_path / "selected.db"
    legacy_db = tmp_path / "legacy.db"

    monkeypatch.setattr(
        module.sys,
        "argv",
        ["app.py", "--db", str(selected_db)],
    )
    monkeypatch.setenv("TOKENKEEPER_DB", str(legacy_db))

    assert module._get_db_path() == str(selected_db.resolve())


def test_dashboard_ignores_legacy_temp_config_without_explicit_db(
    monkeypatch,
    tmp_path,
) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    legacy_db = tmp_path / "legacy.db"
    cfg_path = tmp_path / "tokenkeeper_dashboard.json"
    cfg_path.write_text(json.dumps({"db_path": str(legacy_db)}), encoding="utf-8")

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(module.sys, "argv", ["app.py"])
    monkeypatch.delenv("TOKENKEEPER_DB", raising=False)
    monkeypatch.chdir(tmp_path)

    assert module._get_db_path() == str((tmp_path / "tokenkeeper.db").resolve())


def test_dashboard_sync_clears_cache_when_hermes_changes(monkeypatch) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")

    class FakeCacheData:
        cleared = False

        def clear(self) -> None:
            self.cleared = True

    fake_cache = FakeCacheData()
    fake_session_state = {}

    monkeypatch.setattr(module, "_sync_hermes_for_dashboard", lambda: 2)
    monkeypatch.setattr(module.st, "cache_data", fake_cache)
    monkeypatch.setattr(module.st, "session_state", fake_session_state)

    assert module._sync_and_clear_dashboard_cache() == 2
    assert fake_cache.cleared is True
    assert fake_session_state["last_hermes_sync_changed"] == 2


def test_dashboard_auto_refresh_uses_streamlit_fragment(monkeypatch) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    captured = {}

    def fake_fragment(*, run_every: str | None = None):
        captured["run_every"] = run_every

        def decorate(fn):
            captured["function"] = fn.__name__

            def wrapper(filters):
                captured["filters"] = filters

            return wrapper

        return decorate

    monkeypatch.setattr(module.st, "fragment", fake_fragment)

    module.render_live_dashboard({"auto_refresh": True})

    assert captured == {
        "run_every": "15s",
        "function": "render_dashboard_body",
        "filters": {"auto_refresh": True},
    }


def test_dashboard_manual_refresh_disables_fragment_interval(monkeypatch) -> None:
    module = importlib.import_module("tokenkeeper.dashboard.app")
    captured = {}

    def fake_fragment(*, run_every: str | None = None):
        captured["run_every"] = run_every

        def decorate(fn):
            def wrapper(filters):
                captured["filters"] = filters

            return wrapper

        return decorate

    monkeypatch.setattr(module.st, "fragment", fake_fragment)

    module.render_live_dashboard({"auto_refresh": False})

    assert captured == {
        "run_every": None,
        "filters": {"auto_refresh": False},
    }
