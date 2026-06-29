from __future__ import annotations

import logging
import shutil
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_BYTES_PER_GB = 1024**3


@dataclass
class RetentionPolicy:
    """Retention windows and storage cap for the observability store (Spec §11.2).

    Langfuse trace retention is enforced by setting LANGFUSE_DEFAULT_PROJECT_RETENTION_DAYS
    in the Langfuse service environment (see .env.example), not by this pruner.
    Rollups (session_rollups SQLite table) are never pruned — indefinite by design.
    """

    cap_bytes: int = 50 * _BYTES_PER_GB
    raw_days: int = 90
    traces_days: int = 180


@dataclass
class PruneResult:
    months_deleted: list[str] = field(default_factory=list)
    files_deleted: int = 0
    bytes_freed: int = 0
    errors: list[str] = field(default_factory=list)


def _month_last_day(yyyy_mm: str) -> date:
    year, month = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    last = monthrange(year, month)[1]
    return date(year, month, last)


def _captures_size(captures_dir: Path) -> int:
    return sum(f.stat().st_size for f in captures_dir.rglob("*") if f.is_file())


class ObservabilityPruner:
    """Deterministic, idempotent pruner for Layer 1 raw captures (Spec §11.2).

    Prune order:
    1. Age-based: delete capture month-dirs where every capture is older than raw_days.
    2. Cap-based: if the captures directory still exceeds cap_bytes, delete oldest
       remaining months first until under the cap.

    Only captures/<YYYY-MM>/ directories are ever removed. SQLite rollups and git
    working copies are not touched.
    """

    def prune(
        self,
        base_dir: Path,
        policy: RetentionPolicy,
        now: datetime | None = None,
    ) -> PruneResult:
        """Prune Layer 1 raw captures under base_dir/captures/.

        Safe to re-run after a partial pass — already-deleted month-dirs are skipped.
        """
        effective_now = now or datetime.now(UTC)
        today = effective_now.date()
        result = PruneResult()
        captures_dir = base_dir / "captures"

        if not captures_dir.exists():
            return result

        # Step 1: age-based pruning — delete months whose every capture is beyond raw_days.
        # A capture stored in YYYY-MM is at most as recent as the last day of that month,
        # so the whole month is expired once (today - last_day_of_month) > raw_days.
        for month in self._sorted_months(captures_dir):
            last_day = _month_last_day(month)
            if (today - last_day).days > policy.raw_days:
                result = self._delete_month(captures_dir, month, result)

        if not captures_dir.exists():
            return result

        # Step 2: cap-based pruning — delete oldest remaining months until under cap.
        for month in self._sorted_months(captures_dir):
            if _captures_size(captures_dir) <= policy.cap_bytes:
                break
            result = self._delete_month(captures_dir, month, result)

        return result

    def _sorted_months(self, captures_dir: Path) -> list[str]:
        """YYYY-MM subdirectory names, oldest first."""
        return sorted(
            d.name
            for d in captures_dir.iterdir()
            if d.is_dir() and len(d.name) == 7 and d.name[4] == "-"
        )

    def _delete_month(self, captures_dir: Path, month: str, result: PruneResult) -> PruneResult:
        month_dir = captures_dir / month
        if not month_dir.exists():
            return result
        try:
            files = list(month_dir.glob("*.json.gz"))
            size = sum(f.stat().st_size for f in files)
            shutil.rmtree(month_dir)
            result.months_deleted.append(month)
            result.files_deleted += len(files)
            result.bytes_freed += size
        except OSError as exc:
            msg = f"Failed to prune month {month}: {exc}"
            logger.warning(msg)
            result.errors.append(msg)
        return result
