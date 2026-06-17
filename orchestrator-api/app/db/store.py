import sqlite3
from pathlib import Path

from app.db.migrations import ALL_MIGRATIONS


class StateStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_version_table()
        self._apply_migrations()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("StateStore is not open")
        return self._conn

    def _ensure_version_table(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        self.conn.commit()

    def current_version(self) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM schema_version"
        ).fetchone()
        return row["v"]  # type: ignore[index]

    def _apply_migrations(self) -> None:
        current = self.current_version()
        for migration_cls in ALL_MIGRATIONS:
            migration = migration_cls()
            if migration.version <= current:
                continue
            migration.apply(self.conn)
            self.conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (migration.version, migration.description),
            )
            self.conn.commit()
