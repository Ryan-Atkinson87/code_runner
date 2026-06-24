from __future__ import annotations

import pytest

from app.blockers.models import Blocker, BlockerStatus, BlockerType
from app.blockers.store import BlockerStore, BlockerStoreError
from app.db.store import StateStore


@pytest.fixture()
def store(tmp_path: object) -> StateStore:
    from pathlib import Path

    db_path = Path(str(tmp_path)) / "test.db"
    s = StateStore(db_path)
    s.open()
    s.conn.execute(
        "INSERT INTO runs (project, milestone, status) VALUES (?, ?, ?)",
        ("test-project", "Phase 5", "running"),
    )
    s.conn.commit()
    yield s  # type: ignore[misc]
    s.close()


@pytest.fixture()
def blocker_store(store: StateStore) -> BlockerStore:
    return BlockerStore(store.conn)


def _make_blocker(
    run_id: int = 1,
    issue_number: int = 42,
    blocker_type: BlockerType = BlockerType.MISSING_SPEC,
    reason: str = "Spec section 12 is ambiguous",
    needed: str = "Clarification from stakeholder",
) -> Blocker:
    return Blocker(
        run_id=run_id,
        issue_number=issue_number,
        blocker_type=blocker_type,
        reason=reason,
        needed_to_unblock=needed,
    )


class TestBlockerRecord:
    def test_record_creates_blocker(self, blocker_store: BlockerStore) -> None:
        blocker = _make_blocker()
        result = blocker_store.record(blocker)
        assert result.id is not None
        assert result.run_id == 1
        assert result.issue_number == 42
        assert result.blocker_type == BlockerType.MISSING_SPEC
        assert result.status == BlockerStatus.PARKED
        assert result.created_at != ""

    def test_record_idempotent_same_issue(self, blocker_store: BlockerStore) -> None:
        b1 = blocker_store.record(_make_blocker())
        b2 = blocker_store.record(_make_blocker(reason="Different reason"))
        assert b1.id == b2.id
        assert b1.reason == b2.reason

    def test_record_different_issues_not_idempotent(self, blocker_store: BlockerStore) -> None:
        b1 = blocker_store.record(_make_blocker(issue_number=42))
        b2 = blocker_store.record(_make_blocker(issue_number=43))
        assert b1.id != b2.id

    def test_record_after_resolve_creates_new(self, blocker_store: BlockerStore) -> None:
        b1 = blocker_store.record(_make_blocker())
        blocker_store.resolve(1, 42)
        b2 = blocker_store.record(_make_blocker(reason="New blocker"))
        assert b2.id != b1.id
        assert b2.reason == "New blocker"
        assert b2.status == BlockerStatus.PARKED


class TestBlockerList:
    def test_list_parked_returns_only_parked(self, blocker_store: BlockerStore) -> None:
        blocker_store.record(_make_blocker(issue_number=42))
        blocker_store.record(_make_blocker(issue_number=43))
        blocker_store.resolve(1, 42)
        parked = blocker_store.list_parked(1)
        assert len(parked) == 1
        assert parked[0].issue_number == 43

    def test_list_parked_empty(self, blocker_store: BlockerStore) -> None:
        parked = blocker_store.list_parked(1)
        assert parked == []

    def test_list_parked_filters_by_run(
        self, blocker_store: BlockerStore, store: StateStore
    ) -> None:
        store.conn.execute(
            "INSERT INTO runs (project, milestone, status) VALUES (?, ?, ?)",
            ("test-project", "Phase 6", "running"),
        )
        store.conn.commit()
        blocker_store.record(_make_blocker(run_id=1, issue_number=42))
        blocker_store.record(_make_blocker(run_id=2, issue_number=43))
        parked_run1 = blocker_store.list_parked(1)
        parked_run2 = blocker_store.list_parked(2)
        assert len(parked_run1) == 1
        assert parked_run1[0].issue_number == 42
        assert len(parked_run2) == 1
        assert parked_run2[0].issue_number == 43

    def test_list_all_includes_resolved(self, blocker_store: BlockerStore) -> None:
        blocker_store.record(_make_blocker(issue_number=42))
        blocker_store.record(_make_blocker(issue_number=43))
        blocker_store.resolve(1, 42)
        all_blockers = blocker_store.list_all(1)
        assert len(all_blockers) == 2
        statuses = {b.issue_number: b.status for b in all_blockers}
        assert statuses[42] == BlockerStatus.RESOLVED
        assert statuses[43] == BlockerStatus.PARKED


class TestBlockerResolve:
    def test_resolve_sets_status_and_timestamp(self, blocker_store: BlockerStore) -> None:
        blocker_store.record(_make_blocker())
        resolved = blocker_store.resolve(1, 42)
        assert resolved.status == BlockerStatus.RESOLVED
        assert resolved.resolved_at is not None

    def test_resolve_stores_response_text(self, blocker_store: BlockerStore) -> None:
        blocker_store.record(_make_blocker())
        resolved = blocker_store.resolve(1, 42, resolution_response="The answer is X")
        assert resolved.resolution_response == "The answer is X"

    def test_resolve_without_response_leaves_null(self, blocker_store: BlockerStore) -> None:
        blocker_store.record(_make_blocker())
        resolved = blocker_store.resolve(1, 42)
        assert resolved.resolution_response is None

    def test_resolve_nonexistent_raises(self, blocker_store: BlockerStore) -> None:
        with pytest.raises(BlockerStoreError, match="No parked blocker"):
            blocker_store.resolve(1, 99)

    def test_resolve_already_resolved_raises(self, blocker_store: BlockerStore) -> None:
        blocker_store.record(_make_blocker())
        blocker_store.resolve(1, 42)
        with pytest.raises(BlockerStoreError, match="No parked blocker"):
            blocker_store.resolve(1, 42)


class TestBlockerTypes:
    @pytest.mark.parametrize(
        "bt",
        [
            BlockerType.MISSING_SPEC,
            BlockerType.CONTRACT_CONFLICT,
            BlockerType.UNMET_DEPENDENCY,
            BlockerType.STUCK_AGENT,
            BlockerType.OTHER,
        ],
    )
    def test_all_types_round_trip(self, blocker_store: BlockerStore, bt: BlockerType) -> None:
        blocker = _make_blocker(blocker_type=bt)
        result = blocker_store.record(blocker)
        assert result.blocker_type == bt


class TestMigration:
    def test_blockers_table_created_by_migration(self, store: StateStore) -> None:
        assert store.current_version() >= 4
        tables = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='blockers'"
        ).fetchall()
        assert len(tables) == 1
