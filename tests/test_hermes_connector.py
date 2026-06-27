from __future__ import annotations

import sqlite3
from pathlib import Path

from tokenkeeper import guard
from tokenkeeper.integrations.hermes_connector import sync_hermes_to_tokenkeeper
from tokenkeeper.ledger import Ledger


def _create_hermes_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            billing_provider TEXT,
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read_tokens INTEGER,
            cache_write_tokens INTEGER,
            reasoning_tokens INTEGER,
            estimated_cost_usd REAL,
            actual_cost_usd REAL,
            started_at REAL,
            ended_at REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            timestamp REAL NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _upsert_hermes_session(
    path: Path,
    *,
    session_id: str = "s1",
    input_tokens: int = 100,
    output_tokens: int = 20,
    cache_read_tokens: int = 5,
    cost_usd: float = 0.01,
) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO sessions (
            id, title, billing_provider, model,
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
            reasoning_tokens, estimated_cost_usd, actual_cost_usd,
            started_at, ended_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            input_tokens=excluded.input_tokens,
            output_tokens=excluded.output_tokens,
            cache_read_tokens=excluded.cache_read_tokens,
            estimated_cost_usd=excluded.estimated_cost_usd
        """,
        (
            session_id,
            "Hermes session",
            "minimax-cn",
            "MiniMax-M3",
            input_tokens,
            output_tokens,
            cache_read_tokens,
            0,
            0,
            cost_usd,
            None,
            1782540000.0,
            None,
        ),
    )
    conn.commit()
    conn.close()


def _insert_hermes_message(
    path: Path,
    *,
    session_id: str = "s1",
    timestamp: float = 1782540300.0,
) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO messages (session_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, "assistant", "ok", timestamp),
    )
    conn.commit()
    conn.close()


def test_sync_hermes_imports_session(tmp_path: Path) -> None:
    guard.uninstall()
    hermes_db = tmp_path / "state.db"
    tokenkeeper_db = tmp_path / "tokenkeeper.db"
    _create_hermes_db(hermes_db)
    _upsert_hermes_session(hermes_db)

    assert (
        sync_hermes_to_tokenkeeper(
            hermes_db_path=str(hermes_db),
            tk_db_path=str(tokenkeeper_db),
        )
        == 1
    )

    with Ledger(tokenkeeper_db) as ledger:
        rows = ledger.query(limit=10)
    assert len(rows) == 1
    assert rows[0].provider == "minimax-cn"
    assert rows[0].model == "MiniMax-M3"
    assert rows[0].prompt_tokens == 100
    assert rows[0].completion_tokens == 20
    assert rows[0].cached_tokens == 5


def test_sync_hermes_updates_existing_session_tokens(tmp_path: Path) -> None:
    guard.uninstall()
    hermes_db = tmp_path / "state.db"
    tokenkeeper_db = tmp_path / "tokenkeeper.db"
    _create_hermes_db(hermes_db)
    _upsert_hermes_session(
        hermes_db,
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=5,
        cost_usd=0.01,
    )

    assert (
        sync_hermes_to_tokenkeeper(
            hermes_db_path=str(hermes_db),
            tk_db_path=str(tokenkeeper_db),
        )
        == 1
    )

    _upsert_hermes_session(
        hermes_db,
        input_tokens=140,
        output_tokens=35,
        cache_read_tokens=12,
        cost_usd=0.03,
    )

    assert (
        sync_hermes_to_tokenkeeper(
            hermes_db_path=str(hermes_db),
            tk_db_path=str(tokenkeeper_db),
        )
        == 1
    )

    with Ledger(tokenkeeper_db) as ledger:
        rows = ledger.query(limit=10)
    assert len(rows) == 1
    assert rows[0].prompt_tokens == 140
    assert rows[0].completion_tokens == 35
    assert rows[0].cached_tokens == 12
    assert rows[0].total_tokens == 187
    assert rows[0].cost_usd == 0.03


def test_sync_hermes_uses_latest_message_timestamp(tmp_path: Path) -> None:
    guard.uninstall()
    hermes_db = tmp_path / "state.db"
    tokenkeeper_db = tmp_path / "tokenkeeper.db"
    _create_hermes_db(hermes_db)
    _upsert_hermes_session(hermes_db)
    _insert_hermes_message(hermes_db, timestamp=1782540456.0)

    assert (
        sync_hermes_to_tokenkeeper(
            hermes_db_path=str(hermes_db),
            tk_db_path=str(tokenkeeper_db),
        )
        == 1
    )

    with Ledger(tokenkeeper_db) as ledger:
        rows = ledger.query(limit=10)
    assert len(rows) == 1
    assert rows[0].timestamp == 1782540456.0


def test_sync_hermes_estimates_cost_when_hermes_cost_missing(tmp_path: Path) -> None:
    guard.uninstall()
    hermes_db = tmp_path / "state.db"
    tokenkeeper_db = tmp_path / "tokenkeeper.db"
    _create_hermes_db(hermes_db)
    _upsert_hermes_session(
        hermes_db,
        input_tokens=36_957,
        output_tokens=3_554,
        cache_read_tokens=165_164,
        cost_usd=0.0,
    )

    assert (
        sync_hermes_to_tokenkeeper(
            hermes_db_path=str(hermes_db),
            tk_db_path=str(tokenkeeper_db),
        )
        == 1
    )

    with Ledger(tokenkeeper_db) as ledger:
        rows = ledger.query(limit=10)
    assert len(rows) == 1
    assert rows[0].model == "MiniMax-M3"
    assert rows[0].cost_usd > 0
    assert rows[0].cost_cny > 0
