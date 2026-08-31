"""Test-only runner for exact candidate daily-sync children.

The runner supports only the credential-free materialization targets used by the
T5.2 test gate. It never drains the generic queue: every child is executed by
the deterministic job id returned by its own plan.

The CLI intentionally accepts only an explicit disposable loopback PostgreSQL
environment variable. It never falls back to the application's generic database
variables, and it never performs deployment or container control.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy.engine import URL, make_url


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.dy_api.db import (  # noqa: E402
    make_engine,
    make_session_factory,
    normalize_database_url,
)
from apps.worker.daily_windows import (  # noqa: E402
    DEFAULT_CONFIG_VERSION as DAILY_DEFAULT_CONFIG_VERSION,
    iter_shanghai_daily_windows,
    plan_daily_sync,
)
from apps.worker.scheduler import run_daily_child  # noqa: E402
from apps.worker.subprocess_supervisor import (  # noqa: E402
    ChildRunResult,
    ChildRunStatus,
)


PROTOCOL = "dydata-daily-candidate-acceptance-v1"
ALLOWED_TARGETS = frozenset({"clue_center", "settlement"})
DEFAULT_CONFIG_VERSION = DAILY_DEFAULT_CONFIG_VERSION
TEST_DATABASE_ENV_NAMES = (
    "DYDATA_T52_TEST_DATABASE_URL",
    "DYDATA_T12_TEST_DATABASE_URL",
)
TEST_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost"})
TEST_DATABASE_PORTS = frozenset({15432, 55432})
REJECTED_DATABASE_NAMES = frozenset({"postgres", "dy_dashboard", "production", "prod"})
REJECTED_DATABASE_USERS = frozenset({"postgres", "dy_dashboard", "production", "prod"})


@dataclass(frozen=True)
class CandidateChildReport:
    job_id: str
    status: str
    attempts: int
    exit_code: int | None
    rss_peak_bytes: int | None
    heartbeat_seen: bool
    lease_seen: bool
    timed_out: bool
    termination_reason: str | None


@dataclass(frozen=True)
class CandidateAcceptanceReport:
    protocol: str
    status: str
    release_blocker: bool
    start: str
    end: str
    targets: tuple[str, ...]
    planned_parent_job_ids: tuple[str, ...]
    child_count: int
    rss_peak_bytes: int
    elapsed_seconds: float
    children: tuple[CandidateChildReport, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_candidate_targets(raw: str | Sequence[str]) -> tuple[str, ...]:
    values = raw.split(",") if isinstance(raw, str) else list(raw)
    normalized = tuple(value.strip() for value in values if value.strip())
    if (
        not normalized
        or len(set(normalized)) != len(normalized)
        or not set(normalized).issubset(ALLOWED_TARGETS)
    ):
        raise ValueError("targets must be clue_center and/or settlement")
    return normalized


def validated_test_database_url(raw_url: str) -> URL:
    """Validate the only database URL shape the CLI is allowed to use."""

    if not isinstance(raw_url, str) or not raw_url.strip():
        raise RuntimeError("an explicit T5.2 test database URL is required")
    try:
        url = make_url(normalize_database_url(raw_url.strip()))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("the explicit T5.2 test database URL is invalid") from exc
    if not url.drivername.startswith("postgresql+"):
        raise RuntimeError("T5.2 database evidence requires a PostgreSQL driver")
    if (url.host or "").lower() not in TEST_DATABASE_HOSTS:
        raise RuntimeError("T5.2 test database must use a loopback host")
    if url.port not in TEST_DATABASE_PORTS:
        raise RuntimeError("T5.2 test database must use a dedicated local port")
    database_name = (url.database or "").lower()
    if not database_name or database_name in REJECTED_DATABASE_NAMES:
        raise RuntimeError("T5.2 test database name is not disposable")
    username = (url.username or "").lower()
    if not username or username in REJECTED_DATABASE_USERS:
        raise RuntimeError("T5.2 test database role is not disposable")
    return url


def get_test_database_url(env: Mapping[str, str] | None = None) -> str:
    """Read only explicit test variables; generic app variables are ignored."""

    source = os.environ if env is None else env
    for name in TEST_DATABASE_ENV_NAMES:
        raw_url = source.get(name)
        if raw_url is not None and raw_url.strip():
            return raw_url.strip()
    names = " or ".join(TEST_DATABASE_ENV_NAMES)
    raise RuntimeError(
        f"set an explicit T5.2 test database URL in {names}"
    )


def get_test_session_factory() -> tuple[Any, str]:
    """Create a factory from a validated test URL without touching app globals."""

    raw_url = get_test_database_url()
    validated_url = validated_test_database_url(raw_url)
    normalized_url = validated_url.render_as_string(hide_password=False)
    return make_session_factory(make_engine(normalized_url)), normalized_url


def _child_report(result: ChildRunResult) -> CandidateChildReport:
    return CandidateChildReport(
        job_id=result.job_id,
        status=result.status.value,
        attempts=result.attempts,
        exit_code=result.exit_code,
        rss_peak_bytes=result.rss_peak_bytes,
        heartbeat_seen=result.heartbeat_seen,
        lease_seen=result.lease_seen,
        timed_out=result.timed_out,
        termination_reason=(
            result.termination_reason.value if result.termination_reason is not None else None
        ),
    )


@contextmanager
def _credential_free_child_environment():
    """Keep the local acceptance child offline without leaking env changes."""

    name = "DY_WORKER_FAKE_DOUYIN"
    previous = os.environ.get(name)
    os.environ[name] = "true"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def run_candidate_acceptance(
    factory: Callable[[], Any],
    *,
    start: str,
    end: str,
    targets: Sequence[str],
    max_children: int,
    report_path: str | Path,
    plan_fn: Callable[..., Any] = plan_daily_sync,
    run_fn: Callable[..., ChildRunResult] = run_daily_child,
    config_version: str = DEFAULT_CONFIG_VERSION,
) -> CandidateAcceptanceReport:
    normalized_targets = parse_candidate_targets(targets)
    if isinstance(max_children, bool) or max_children <= 0:
        raise ValueError("max_children must be positive")
    if not isinstance(config_version, str) or not config_version.strip():
        raise ValueError("config_version must be nonblank")

    windows = iter_shanghai_daily_windows(start, end)
    started_at = time.monotonic()
    parent_job_ids: list[str] = []
    child_job_ids: list[str] = []
    incomplete_plans = False

    for target in normalized_targets:
        session = factory()
        if session is None:
            raise RuntimeError("candidate acceptance requires a test database session")
        try:
            plan = plan_fn(
                session,
                start=start,
                end=end,
                target=target,
                requested_by="t52-test-server",
                trigger_source="authorized_test_acceptance",
                config_version=config_version,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        parent_job_ids.append(str(plan.parent_job_id))
        plan_children = tuple(plan.daily_jobs)
        ready_children = tuple(
            str(child.job_id)
            for child in plan_children
            if str(child.disposition) == "ready"
        )
        if len(ready_children) != len(plan_children):
            incomplete_plans = True
        child_job_ids.extend(ready_children)

    expected_children = len(windows) * len(normalized_targets)
    if len(child_job_ids) > max_children:
        raise ValueError(
            f"planned child count {len(child_job_ids)} exceeds max_children {max_children}"
        )

    with _credential_free_child_environment():
        results = tuple(run_fn(factory, job_id=job_id) for job_id in child_job_ids)
    children = tuple(_child_report(result) for result in results)
    all_success = (
        not incomplete_plans
        and len(children) == expected_children
        and all(result.status is ChildRunStatus.SUCCESS for result in results)
    )
    status = "GREEN" if all_success else "FAILED"
    rss_peak_bytes = max(
        (child.rss_peak_bytes or 0 for child in children),
        default=0,
    )
    report = CandidateAcceptanceReport(
        protocol=PROTOCOL,
        status=status,
        release_blocker=not all_success,
        start=windows[0].start.date().isoformat(),
        end=windows[-1].end.date().isoformat(),
        targets=normalized_targets,
        planned_parent_job_ids=tuple(parent_job_ids),
        child_count=len(children),
        rss_peak_bytes=rss_peak_bytes,
        elapsed_seconds=round(time.monotonic() - started_at, 6),
        children=children,
    )
    destination = Path(report_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run exact candidate daily jobs against an explicit disposable test database. "
            "The command never uses generic database variables or deploys services."
        )
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--targets", required=True)
    parser.add_argument("--max-children", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--config-version", default=DEFAULT_CONFIG_VERSION)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    previous_dy_url = os.environ.get("DY_DATABASE_URL")
    previous_database_url = os.environ.get("DATABASE_URL")
    try:
        factory, normalized_url = get_test_session_factory()
        # The child process only understands the application variable. It is
        # populated from the already validated explicit test URL and restored
        # before this CLI exits.
        os.environ["DY_DATABASE_URL"] = normalized_url
        os.environ.pop("DATABASE_URL", None)
        report = run_candidate_acceptance(
            factory,
            start=args.start,
            end=args.end,
            targets=parse_candidate_targets(args.targets),
            max_children=args.max_children,
            report_path=args.report,
            config_version=args.config_version,
        )
    except ValueError as exc:
        print(f"candidate acceptance input error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Do not print exception text: SQLAlchemy errors can include credentials.
        print(f"candidate acceptance execution error: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if previous_dy_url is None:
            os.environ.pop("DY_DATABASE_URL", None)
        else:
            os.environ["DY_DATABASE_URL"] = previous_dy_url
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
    print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if report.status == "GREEN" else 3


if __name__ == "__main__":
    raise SystemExit(main())
