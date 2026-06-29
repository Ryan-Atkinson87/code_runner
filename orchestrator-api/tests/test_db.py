import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.db.store import StateStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[StateStore]:
    s = StateStore(tmp_path / "test.db")
    s.open()
    yield s
    s.close()


def test_init_creates_tables(store: StateStore) -> None:
    tables = {
        row[0]
        for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "runs" in tables
    assert "issue_states" in tables
    assert "schema_version" in tables


def test_wal_mode_enabled(store: StateStore) -> None:
    mode = store.conn.execute("PRAGMA journal_mode").fetchone()
    assert mode[0] == "wal"  # type: ignore[index]


def test_schema_version_recorded(store: StateStore) -> None:
    assert store.current_version() == 7


def test_run_write_read_roundtrip(store: StateStore) -> None:
    store.conn.execute(
        "INSERT INTO runs (project, milestone, status) VALUES (?, ?, ?)",
        ("test-project", "Foundations", "running"),
    )
    store.conn.commit()

    row = store.conn.execute("SELECT * FROM runs WHERE project = ?", ("test-project",)).fetchone()
    assert row is not None
    assert row["milestone"] == "Foundations"
    assert row["status"] == "running"


def test_issue_state_write_read_roundtrip(store: StateStore) -> None:
    store.conn.execute(
        "INSERT INTO runs (id, project, milestone, status) VALUES (1, 'proj', 'M1', 'running')"
    )
    store.conn.execute(
        "INSERT INTO issue_states (run_id, issue_number, status) VALUES (1, 42, 'in_progress')"
    )
    store.conn.commit()

    row = store.conn.execute(
        "SELECT * FROM issue_states WHERE run_id = 1 AND issue_number = 42"
    ).fetchone()
    assert row is not None
    assert row["status"] == "in_progress"


def test_issue_state_unique_constraint(store: StateStore) -> None:
    store.conn.execute(
        "INSERT INTO runs (id, project, milestone, status) VALUES (1, 'proj', 'M1', 'running')"
    )
    store.conn.execute(
        "INSERT INTO issue_states (run_id, issue_number, status) VALUES (1, 10, 'pending')"
    )
    store.conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO issue_states (run_id, issue_number, status) VALUES (1, 10, 'done')"
        )


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "idem.db"
    s1 = StateStore(db_path)
    s1.open()
    assert s1.current_version() == 7
    s1.close()

    s2 = StateStore(db_path)
    s2.open()
    assert s2.current_version() == 7
    s2.close()


def test_conn_raises_when_not_open() -> None:
    store = StateStore(":memory:")
    with pytest.raises(RuntimeError, match="not open"):
        _ = store.conn
