"""The web pages' default statement period must equal the server's rule.

`/settlement`, `/finance/promotion` and the other settlement/finance routes must
open on the last fully completed Shanghai natural month: while it is 2026-10 the
default period is 2026-09, even though 2026-09 may still hold no data.

These tests execute the real TypeScript source through the repository's own
`tsc` and `node` instead of asserting on its text, so the Shanghai timezone
arithmetic, the month-boundary handling and the year rollover are actually
verified. Expected values come from the backend's `previous_business_month`,
which keeps the two implementations from drifting apart.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
UTIL = WEB / "src" / "utils" / "statementMonth.ts"
TSC = WEB / "node_modules" / "typescript" / "bin" / "tsc"
# `tmp/` is the repository's gitignored scratch root (`DY_TEST_SCRATCH_DIR`
# overrides it), so the compiled artifact never lands in version control.
SCRATCH_ROOT = Path(os.environ.get("DY_TEST_SCRATCH_DIR") or (ROOT / "tmp"))

# Instants chosen to pin the Shanghai boundary, the UTC boundary and the year
# rollover; every one of them is also fed to the backend rule.
MOMENTS = (
    "2026-10-12T09:21:00+08:00",
    "2026-10-01T00:00:00+08:00",
    "2026-09-30T23:59:59+08:00",
    "2026-09-30T16:00:00Z",
    "2026-09-30T15:59:00Z",
    "2026-01-01T00:00:00+08:00",
    "2026-03-01T00:00:00+08:00",
)


def _node() -> str:
    node = shutil.which("node")
    if node is None or not TSC.exists():
        pytest.skip("Node.js and the web TypeScript compiler are required")
    return node


@pytest.fixture(scope="module")
def scratch() -> Iterator[Path]:
    # A plainly created directory, not `tempfile.mkdtemp`: some sandboxes deny
    # nested creation under a mode-0700 temp dir.
    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = SCRATCH_ROOT / f"statement-month-{os.getpid()}-{uuid4().hex[:8]}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="module")
def compiled(scratch: Path) -> Path:
    """Compile the real util to ESM so Node can import it."""

    out = scratch / "build"
    out.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            _node(),
            str(TSC),
            str(UTIL),
            "--outDir",
            str(out),
            "--module",
            "esnext",
            "--target",
            "es2020",
            "--moduleResolution",
            "bundler",
            "--skipLibCheck",
            "--lib",
            "es2020,dom",
        ],
        cwd=WEB,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    built = out / "statementMonth.js"
    assert built.exists(), result.stdout + result.stderr
    return built


def _run(scratch: Path, compiled: Path, name: str, body: str) -> object:
    script = scratch / f"{name}.mjs"
    script.write_text(
        f"import * as util from {json.dumps(compiled.as_uri())};\n"
        "const result = (() => {\n"
        f"{body}\n"
        "})();\n"
        "process.stdout.write(JSON.stringify(result));\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [_node(), str(script)],
        cwd=scratch,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


MONTHS_EXPR = (
    "return " + json.dumps(list(MOMENTS)) + ".map((iso) => "
    "util.previousShanghaiStatementMonth(new Date(iso)));"
)


def test_web_default_period_matches_the_server_rule(scratch: Path, compiled: Path) -> None:
    sys.path.insert(0, str(ROOT))
    from apps.worker.month_close import previous_business_month  # noqa: PLC0415

    web_months = _run(scratch, compiled, "parity", MONTHS_EXPR)
    server_months = [
        previous_business_month(datetime.fromisoformat(moment)) for moment in MOMENTS
    ]

    assert web_months == server_months
    # Confirmed scope: during 2026-10 the pages open on the 2026-09 period.
    assert web_months[0] == "2026-09"


def test_web_default_period_still_matches_the_server_rule_at_the_real_clock(
    scratch: Path, compiled: Path
) -> None:
    """Drift guard: the two implementations agree at the current instant too."""

    sys.path.insert(0, str(ROOT))
    from apps.worker.month_close import previous_business_month  # noqa: PLC0415

    now = datetime.now(UTC)
    web_month = _run(
        scratch,
        compiled,
        "parity-now",
        f"return util.previousShanghaiStatementMonth(new Date({json.dumps(now.isoformat())}));",
    )

    assert web_month == previous_business_month(now)


def test_finance_fee_default_period_without_query_params_is_the_2026_09_period(
    scratch: Path, compiled: Path
) -> None:
    """FinanceFeePage opens on the previous Shanghai month, not the clock month.

    The page's initial month is `initialStatementMonth(searchParams)`, so this
    exercises exactly the no-query-parameter default an operator gets during
    2026-10.
    """

    result = _run(
        scratch,
        compiled,
        "finance-default",
        # A fixed instant inside 2026-10: the confirmed reference period.
        "const now = new Date('2026-10-12T09:21:00+08:00');"
        " const pageDefault = (search) => util.initialStatementMonth("
        "new URLSearchParams(search), now);"
        " return {"
        " noParams: pageDefault(''),"
        " otherParams: pageDefault('q=SAP&invoiceStatus=PENDING_INVOICE'),"
        " explicitMonth: pageDefault('month=2026-08'),"
        " clockMonth: new Intl.DateTimeFormat('en-CA', {"
        "   timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit'"
        " }).format(now)"
        " };",
    )

    assert result["noParams"] == "2026-09"
    assert result["otherParams"] == "2026-09"
    assert result["explicitMonth"] == "2026-08"
    # The clock month really is 2026-10, so this is not a coincidence of naming.
    assert result["clockMonth"] == "2026-10"


def test_web_default_period_is_the_last_completed_shanghai_month(
    scratch: Path, compiled: Path
) -> None:
    months = _run(scratch, compiled, "months", MONTHS_EXPR)

    assert months == [
        "2026-09",  # 2026-10-12 in Shanghai
        "2026-09",  # first instant of the Shanghai month
        "2026-08",  # last instant before it
        "2026-09",  # 2026-10-01 00:00 Shanghai, expressed in UTC
        "2026-08",  # one minute earlier, still September in Shanghai
        "2025-12",  # year rollover
        "2026-02",  # 31-day month boundary
    ]


def test_web_initial_period_prefers_a_valid_url_month_else_the_previous_month(
    scratch: Path, compiled: Path
) -> None:
    result = _run(
        scratch,
        compiled,
        "initial",
        # Fixed instant so the fallback assertion cannot drift with the clock.
        "const now = new Date('2026-10-12T09:21:00+08:00');"
        " const at = (search) => util.initialStatementMonth("
        "new URLSearchParams(search), now);"
        " return {"
        " valid: at('month=2026-08'),"
        " periodKey: at('periodKey=2026-07'),"
        " monthWins: at('month=2026-08&periodKey=2026-07'),"
        " absent: at(''),"
        " otherParams: at('q=SAP&month=2026-07'),"
        " malformed: at('month=2026-13'),"
        " blank: at('month=')"
        " };",
    )

    assert result == {
        "valid": "2026-08",
        "periodKey": "2026-07",
        "monthWins": "2026-08",
        "absent": "2026-09",
        "otherParams": "2026-07",
        "malformed": "2026-09",
        "blank": "2026-09",
    }


def test_web_month_control_mirrors_the_selection_into_the_url(
    scratch: Path, compiled: Path
) -> None:
    """The month control replaces one history entry and keeps other filters."""

    result = _run(
        scratch,
        compiled,
        "url",
        "const calls = [];"
        " globalThis.window = {"
        "   location: { pathname: '/finance/promotion', search: '?q=SAP&month=2026-08' },"
        "   history: { replaceState: (_state, _title, href) => {"
        "     calls.push(href);"
        "     const index = href.indexOf('?');"
        "     globalThis.window.location.search = index === -1 ? '' : href.slice(index);"
        "   } }"
        " };"
        " util.replaceStatementMonthInUrl('2026-07');"
        " util.replaceStatementMonthInUrl('2026-07');"
        " util.replaceStatementMonthInUrl('');"
        " return calls;",
    )

    # The second identical selection is a no-op, so no duplicated history write.
    assert result == [
        "/finance/promotion?q=SAP&month=2026-07",
        "/finance/promotion?q=SAP",
    ]
