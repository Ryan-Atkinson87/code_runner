import sqlite3
from typing import Protocol


class Migration(Protocol):
    version: int
    description: str

    def apply(self, conn: sqlite3.Connection) -> None: ...


class V001_Baseline:
    version = 1
    description = "Initial schema: runs, issue_states, schema_version"

    def apply(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                milestone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                started_at TEXT,
                finished_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS issue_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id),
                issue_number INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                branch TEXT,
                pr_number INTEGER,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(run_id, issue_number)
            );
        """)


ALL_MIGRATIONS: list[type[Migration]] = [V001_Baseline]  # type: ignore[type-abstract]
