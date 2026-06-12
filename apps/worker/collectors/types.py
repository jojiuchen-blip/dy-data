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

