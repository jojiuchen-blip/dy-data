from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CollectionWindow:
    start: datetime
    end: datetime
    timezone_name: str

    def as_metadata(self) -> dict[str, str]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "timezone": self.timezone_name,
        }


@dataclass
class PhaseStats:
    name: str
    fetched: int = 0
    upserted: int = 0
    skipped: int = 0
    failed: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0

    def record_upsert(self, outcome: str) -> None:
        """Record a raw-row outcome without conflating it with a write.

        ``upserted`` remains the number of rows that created or changed
        business data.  Replays and stale observations are reported
        separately so a successful collection cannot be mistaken for a set of
        accepted updates.
        """

        if outcome == "inserted":
            self.inserted += 1
            self.upserted += 1
        elif outcome == "updated":
            self.updated += 1
            self.upserted += 1
        elif outcome == "unchanged":
            self.unchanged += 1
        elif outcome == "rejected":
            self.rejected += 1
        else:
            raise ValueError(f"unknown upsert outcome: {outcome!r}")

    @property
    def success_count(self) -> int:
        return self.upserted

    @property
    def failed_count(self) -> int:
        return self.failed

    def as_metadata(self) -> dict[str, int | str]:
        return {
            "name": self.name,
            "fetched": self.fetched,
            "upserted": self.upserted,
            "skipped": self.skipped,
            "failed": self.failed,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "rejected": self.rejected,
        }


@dataclass
class CollectionStats:
    run_id: str
    source_window: CollectionWindow
    phases: list[PhaseStats] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_phase(self, phase: PhaseStats) -> PhaseStats:
        self.phases.append(phase)
        return phase

    @property
    def success_count(self) -> int:
        return sum(phase.success_count for phase in self.phases)

    @property
    def failed_count(self) -> int:
        return sum(phase.failed_count for phase in self.phases)

    def as_metadata(self) -> dict[str, Any]:
        return {
            **self.metadata,
            "run_id": self.run_id,
            "source_window": self.source_window.as_metadata(),
            "phases": {phase.name: phase.as_metadata() for phase in self.phases},
        }
