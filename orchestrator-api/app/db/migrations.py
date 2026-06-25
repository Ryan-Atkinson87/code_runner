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


class V002_IssueMarkers:
    version = 2
    description = "Per-issue wave-loop step markers for crash recovery"

    def apply(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS issue_markers (
                run_id INTEGER NOT NULL REFERENCES runs(id),
                issue_number INTEGER NOT NULL,
                last_step TEXT NOT NULL,
                checkpoint_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (run_id, issue_number)
            );
        """)


class V003_UsagePauses:
    version = 3
    description = "Usage pause state for hard pause / automatic resume"

    def apply(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS usage_pauses (
                run_id INTEGER PRIMARY KEY REFERENCES runs(id),
                governing_meter_kind TEXT NOT NULL,
                governing_utilisation REAL NOT NULL,
                resets_at REAL,
                paused_at TEXT NOT NULL DEFAULT (datetime('now')),
                resumed_at TEXT
            );
        """)


class V004_Blockers:
    version = 4
    description = "Structured blocker records for park/list/resolve"

    def apply(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS blockers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id),
                issue_number INTEGER NOT NULL,
                blocker_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                needed_to_unblock TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'parked',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                resolved_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_blockers_run_status
                ON blockers (run_id, status);
        """)


class V005_BlockerResolutionResponse:
    version = 5
    description = "Store human response text when resolving a blocker"

    def apply(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "ALTER TABLE blockers ADD COLUMN resolution_response TEXT"
        )


class V006_RunProvider:
    version = 6
    description = "Persist provider choice on each run"

    def apply(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "ALTER TABLE runs ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude'"
        )


ALL_MIGRATIONS: list[type[Migration]] = [  # type: ignore[type-abstract]
    V001_Baseline,
    V002_IssueMarkers,
    V003_UsagePauses,
    V004_Blockers,
    V005_BlockerResolutionResponse,
    V006_RunProvider,
]
