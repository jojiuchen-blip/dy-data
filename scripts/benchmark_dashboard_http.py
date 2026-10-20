"""Opt-in disposable PostgreSQL / real uvicorn ranking HTTP capacity probe.

Run on the Docker host with DYDATA_PUBLICATION_HTTP_CAPACITY=1 and a local
DYDATA_PUBLICATION_TEST_DATABASE_URL supplied through the environment:
    python scripts/benchmark_dashboard_http.py run --image IMAGE \
        --network-container LOCAL_POSTGRES --output .tmp/http-capacity

Setup, API and client are separate containers. Only API receives the measured
768 MiB / 2 CPU budget; no host port is published. The existing synthetic
real-source fixture is reused, never a production database or frozen shortcut.
This is a diagnostic command, deliberately outside ordinary pytest collection.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from threading import Barrier, Lock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "ranking_http_scale_"
REPORT_PREFIX = "HTTP_CAPACITY_JSON="
MEMORY_LIMIT = 768 * 1024 * 1024
API_PATH = "/api/v1/dashboard/douyin-ranking"
VERSION = "http-scale"


def _engine(schema):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    assert re.fullmatch(PREFIX + r"[a-f0-9]{32}", schema), "not an owned random schema"
    url = make_url(os.environ["DYDATA_PUBLICATION_TEST_DATABASE_URL"])
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert "test" in (url.database or "").lower()
    return create_engine(url, connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=120000"})


def _prepare(schema):
    from sqlalchemy import func, select, text
    from sqlalchemy.orm import Session

    sys.path.insert(0, str(ROOT / "tests"))
    import test_dashboard_publication_ranking_scale_postgres as fixture
    from apps.api.dy_api.access_control import ensure_access_control_seed
    from apps.api.dy_api.models import User, UserStoreScope
    from apps.api.dy_api.dashboard_publications.schema import heads

    # The HTTP contract uses Shanghai calendar dates. Align the reusable
    # fixture's origin (including roster validity) with Shanghai midnight.
    fixture.START = datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    engine = _engine(schema)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    fixture.Base.metadata.create_all(engine)
    fixture.source_metadata.create_all(engine)
    fixture.metadata.create_all(engine)
    with Session(engine) as session:
        fixture._seed_sources(session)
        counts = {model.__tablename__: session.scalar(select(func.count()).select_from(model))
                  for model in (fixture.RawDouyinOrder, fixture.ClueAssignmentRound,
                                fixture.ClueCenterOrder, fixture.DimStore)}
        assert list(counts.values()) == [fixture.ORDER_COUNT, fixture.ROUND_COUNT,
                                        fixture.CENTER_COUNT, fixture.STORE_COUNT]
        ensure_access_control_seed(session)
        for identity, role, state in (("reader", "highest_admin", "active"),
                                      ("store", "store", "active"),
                                      ("revoked", "store", "disabled")):
            session.add(User(user_id=identity, username=identity, display_name=identity,
                             role=role, status=state, is_initialized=True,
                             store_scope_mode="specified" if role == "store" else "all"))
        session.flush()
        session.add(UserStoreScope(user_id="store", store_id="S42"))
        session.execute(fixture.runs.insert().values(id=VERSION, module="douyin-ranking",
            status="building", cutoff=fixture.CUTOFF, created_at=fixture.CUTOFF, stats_json={}))
        session.commit()
        started = time.perf_counter()
        stats = fixture.ranking.build(session, VERSION, fixture.CUTOFF)
        build_seconds = time.perf_counter() - started
        assert build_seconds < 180, "real-source build exceeded the existing 180s budget"
        session.execute(fixture.runs.update().where(fixture.runs.c.id == VERSION).values(
            status="success", published_at=datetime.now(timezone.utc), stats_json=stats))
        session.execute(heads.insert().values(module="douyin-ranking", publication_id=VERSION))
        session.commit()
    engine.dispose()
    return dict(schema=schema, counts=counts, publication_id=VERSION,
                source_origin=fixture.START.isoformat(), build_seconds=build_seconds, stats=stats)


def _memory():
    import resource

    base = Path("/sys/fs/cgroup")
    values = {name.replace(".", "_"): (base / name).read_text().strip()
              for name in ("memory.current", "memory.peak", "memory.max", "memory.events", "cpu.max")}
    for name in ("memory_current", "memory_peak", "memory_max"):
        values[name] = int(values[name])
    status = Path("/proc/self/status").read_text()
    values["rss_current_bytes"] = int(re.search(r"^VmRSS:\s+(\d+)", status, re.MULTILINE).group(1)) * 1024
    values["rss_peak_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return values


def _serve(schema, port):
    import uvicorn
    from fastapi import Depends, Request as FastApiRequest
    import fastapi.routing
    from starlette.responses import JSONResponse
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from dy_api.auth import get_current_user
    from dy_api.main import create_app
    from dy_api.routes._data import get_session_dependency
    from apps.api.dy_api.dashboard_publications import ranking, ranking_build

    engine = _engine(schema)
    # Initialize the dialect before observing business SQL.
    with engine.connect():
        pass
    observed = dict(statements=0, source_reads=0, mutations=0, builder_calls=0, requests=[])
    lock = Lock()
    active_request = ContextVar("capacity_request", default=None)

    def observe(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.strip().upper()
        source = bool(re.search(r"\b(RAW_DOUYIN_\w+|CLUE_ASSIGNMENT_ROUNDS|CLUE_CENTER_ORDERS|CLUE_MASTER_LEADS|CLUE_FOLLOW_UP_RECORDS)\b", normalized))
        mutation = not normalized.startswith(("SELECT", "WITH")) or bool(
            re.search(r"\b(INSERT INTO|UPDATE\s+|DELETE FROM|CREATE TABLE|ALTER TABLE|TRUNCATE)\b", normalized))
        with lock:
            observed["statements"] += 1
            observed["source_reads"] += int(source)
            observed["mutations"] += int(mutation)
        assert not source and not mutation, "HTTP read attempted source access or mutation"
        context.capacity_started = time.perf_counter()

    def after_query(connection, cursor, statement, parameters, context, executemany):
        measurement = active_request.get()
        if measurement is None:
            return
        seconds = time.perf_counter() - context.capacity_started
        # SQLAlchemy templates retain placeholders, never bound parameter values.
        template = re.sub(r"\s+", " ", statement).strip()[:180]
        with lock:
            measurement["sql_count"] += 1
            measurement["sql_seconds"] += seconds
            measurement["slowest_sql"].append(dict(seconds=seconds, template=template))
            measurement["slowest_sql"].sort(key=lambda item: item["seconds"], reverse=True)
            del measurement["slowest_sql"][3:]

    def reject_builder(*args, **kwargs):
        with lock:
            observed["builder_calls"] += 1
        raise AssertionError("HTTP read attempted ranking build")

    event.listen(engine, "before_cursor_execute", observe)
    event.listen(engine, "after_cursor_execute", after_query)
    ranking.build = ranking_build.build = reject_builder

    def session_dependency():
        with Session(engine) as session:
            yield session

    app = create_app()
    # Test-only DB routing. Keep production cookie authentication, authorization,
    # API routes, middleware, serialization and workbook generation unchanged.
    app.dependency_overrides[get_session_dependency] = session_dependency

    # Annotate the original auth call; no identity or authorization is replaced.
    def timed_auth(request: FastApiRequest, session=Depends(session_dependency)):
        started = time.perf_counter()
        try:
            return get_current_user(request, session)
        finally:
            measurement = active_request.get()
            if measurement is not None:
                measurement["auth_seconds"] += time.perf_counter() - started

    # FastAPI resolves annotations from globals, while this dependency is
    # intentionally local to the test server to keep host imports lightweight.
    timed_auth.__annotations__["request"] = FastApiRequest
    app.dependency_overrides[get_current_user] = timed_auth
    original_serialize = fastapi.routing.serialize_response
    original_render = JSONResponse.render

    async def timed_serialize(*args, **kwargs):
        started = time.perf_counter()
        try:
            return await original_serialize(*args, **kwargs)
        finally:
            measurement = active_request.get()
            if measurement is not None:
                measurement["response_serialization_seconds"] += time.perf_counter() - started

    def timed_render(response, content):
        started = time.perf_counter()
        try:
            return original_render(response, content)
        finally:
            measurement = active_request.get()
            if measurement is not None:
                measurement["json_encoding_seconds"] += time.perf_counter() - started

    fastapi.routing.serialize_response = timed_serialize
    JSONResponse.render = timed_render

    @app.middleware("http")
    async def request_stages(request, call_next):
        if not request.url.path.startswith("/api/v1/dashboard/"):
            return await call_next(request)
        measurement = dict(path=request.url.path, sql_count=0, sql_seconds=0.0,
                           auth_seconds=0.0, response_serialization_seconds=0.0,
                           json_encoding_seconds=0.0, slowest_sql=[])
        token = active_request.set(measurement)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            measurement["status"] = response.status_code
            return response
        finally:
            measurement["response_ready_seconds"] = time.perf_counter() - started
            # Auth includes its SQL; do not subtract it again from this remainder.
            measurement["non_sql_python_framework_seconds"] = max(0,
                measurement["response_ready_seconds"] - measurement["sql_seconds"])
            active_request.reset(token)
            with lock:
                observed["requests"].append(measurement)
                del observed["requests"][:-64]

    @app.get("/__capacity__/status", include_in_schema=False)
    def capacity_status():
        with lock:
            snapshot = dict(observed)
        return dict(memory=_memory(), sql=snapshot)

    uvicorn.run(app, host="127.0.0.1", port=port, workers=1, access_log=False, log_level="warning")


def _request(port, path, params=None, identity="reader"):
    from dy_api.auth import create_session_token

    headers = {}
    if identity is not None:
        token = create_session_token(identity, user_id=identity, auth_type="user")
        headers["Cookie"] = "dy_session=" + token
    url = f"http://127.0.0.1:{port}" + path
    if params:
        url += "?" + urlencode(params)
    started = time.perf_counter()
    try:
        response = urlopen(Request(url, headers=headers), timeout=120)
    except HTTPError as error:
        response = error
    with response:
        body = response.read()  # Fully receive every byte before stopping timer.
        return dict(status=response.status, seconds=time.perf_counter() - started,
                    bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                    headers={key.lower(): value for key, value in response.headers.items()}, body=body)


def _json(result):
    return json.loads(result["body"])


def _probe(port):
    from openpyxl import load_workbook

    for attempt in range(120):
        try:
            baseline = _json(_request(port, "/__capacity__/status", identity=None))
            break
        except URLError:
            time.sleep(0.25)
    else:
        raise RuntimeError("API readiness exceeded 30s")
    assert baseline["memory"]["memory_max"] == MEMORY_LIMIT
    assert baseline["memory"]["cpu_max"] == "200000 100000"
    params = dict(periodStart="2026-01-01", periodEnd="2026-12-31", productScope="all",
                  level="group", publication_id=VERSION)
    order_count, store_count = 510467, 1531
    expected = order_count
    records = []

    def measured(name, path=API_PATH, options=None, identity="reader", expected_status=200):
        result = _request(port, path, options if options is not None else params, identity)
        assert result["status"] == expected_status, (name, result["status"], result["body"][:400])
        record = {key: value for key, value in result.items() if key not in {"body", "headers"}}
        record["case"] = name
        record["api_memory_after_response"] = _json(_request(port, "/__capacity__/status", identity=None))["memory"]
        if expected_status != 200:
            record["error"] = _json(result)["detail"]
        elif path.endswith("/export"):
            assert result["headers"].get("x-publication-id") == VERSION
            assert "spreadsheetml.sheet" in result["headers"].get("content-type", "")
            assert int(result["headers"]["content-length"]) == result["bytes"]
            book = load_workbook(BytesIO(result["body"]), read_only=True, data_only=True)
            assert len(book.worksheets) == 3
            for sheet in book:
                assert VERSION in str(sheet["A3"].value)
                assert "上游尚未提供完整截止时间" in str(sheet["A3"].value)
            first_rows = list(book.worksheets[0].values)
            data_rows = [row for row in first_rows if len(row) >= 5 and isinstance(row[4], (int, float))]
            assert len(data_rows) == 1681, len(data_rows)
            assert sum(row[4] for row in data_rows) == expected * 5
            record.update(sheets=3, organization_rows_per_sheet=len(data_rows),
                          auxiliary_order_sum=sum(row[4] for row in data_rows))
            book.close()
        else:
            payload = _json(result)
            assert payload["meta"]["publication"]["id"] == VERSION
            assert payload["meta"]["publication"]["dataAsOf"] is None
            data = payload["data"]
            if path.endswith("/filters"):
                assert len(data["stores"]) == store_count
                assert len(data["saleMonths"]) == 10
                record.update(stores=len(data["stores"]), months=len(data["saleMonths"]))
            else:
                assert data["rows"]
                assert len(data["rows"]) <= int((options or params).get("pageSize", 50))
                record.update(total=data["total"], orders=int(data["totals"]["orderCount"]),
                              rows=len(data["rows"]))
        records.append(record)
        print("HTTP_CASE=" + json.dumps(record, ensure_ascii=False), flush=True)
        return record

    filters_path = "/api/v1/dashboard/publications/douyin-ranking/filters"
    for iteration in range(3):
        filters = measured(f"filters_year_{iteration + 1}", filters_path, dict(publication_id=VERSION))
        record = measured(f"group_year_{iteration + 1}")
        assert record["orders"] == expected
        record["page_seconds_including_filters"] = filters["seconds"] + record["seconds"]
    for name, extra, expected_orders in (
        ("store", dict(level="store", storeId="S42"),
         sum(number % store_count == 42 for number in range(order_count))),
        ("group", dict(level="store", groupName="Group 2", page=2, pageSize=50),
         sum((number % store_count) % 10 == 2 for number in range(order_count))),
        ("september", dict(periodStart="2026-09-01", periodEnd="2026-09-30"),
         sum(243 <= number % 291 <= 272 for number in range(order_count))),
        ("product", dict(productScope="jingcheng"),
         sum(number % 7 != 0 for number in range(order_count))),
    ):
        record = measured("filter_" + name, options={**params, **extra})
        assert record["orders"] == expected_orders, (name, record, expected_orders)
    export_params = {**params, "levels": "group,service_center,district,area,store"}
    measured("export_all_levels", API_PATH + "/export", export_params)
    measured("unauthenticated_export", API_PATH + "/export", export_params,
             identity=None, expected_status=401)
    measured("revoked_account_export", API_PATH + "/export", export_params,
             identity="revoked", expected_status=401)
    # A03 is deliberately granted to all initialized roles by access_control;
    # current ranking routes deliberately expose the full organization scope.
    record = measured("store_account_global_A03", identity="store")
    assert record["orders"] == expected
    measured("store_account_export_global_A03", API_PATH + "/export", export_params, identity="store")
    measured("invalid_export_options", API_PATH + "/export", {**export_params, "metrics": "invalid"}, expected_status=422)
    measured("invalid_export_period", API_PATH + "/export", {**export_params,
             "periodStart": "2026-09-30", "periodEnd": "2026-09-01"}, expected_status=422)
    measured("expired_export_version", API_PATH + "/export", {**export_params,
             "publication_id": "expired"}, expected_status=410)
    barrier = Barrier(3)

    def concurrent_case(name, path, options):
        barrier.wait(timeout=10)
        return measured(name, path, options)

    began = time.perf_counter()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(concurrent_case, "concurrent_year", API_PATH, params),
                   pool.submit(concurrent_case, "concurrent_september", API_PATH,
                               {**params, "periodStart": "2026-09-01", "periodEnd": "2026-09-30"}),
                   pool.submit(concurrent_case, "concurrent_export", API_PATH + "/export", export_params)]
        concurrent_results = [future.result() for future in futures]
    assert concurrent_results[0]["orders"] == expected
    assert concurrent_results[1]["orders"] == sum(243 <= number % 291 <= 272 for number in range(order_count))
    concurrency_seconds = time.perf_counter() - began
    final = _json(_request(port, "/__capacity__/status", identity=None))
    assert final["sql"]["statements"] > 0
    assert all(final["sql"][key] == 0 for key in ("mutations", "source_reads", "builder_calls"))
    assert final["memory"]["memory_peak"] < MEMORY_LIMIT
    assert "oom_kill 0" in final["memory"]["memory_events"]
    return dict(baseline=baseline, final=final, cases=records,
                concurrency=dict(clients=3, reads=2, exports=1, wall_seconds=concurrency_seconds,
                                 cases=[result["case"] for result in concurrent_results]),
                caveats=["Local synthetic source distribution; no production incident attribution.",
                         "Reusable fixture origin aligned to Shanghai midnight for HTTP calendar-date contract.",
                         "A03 is unconditionally granted by current access_control; 403 revocation is not available.",
                         "HTTP client and XLSX parsing excluded from measured API cgroup.",
                         "Stage profiling adds test-only timing. Auth includes its SQL; non-SQL remainder includes Python/framework, excluding network transfer.",
                         "Single uvicorn worker, one concurrent burst; not sustained load or browser rendering."])


def _cleanup(schema):
    from sqlalchemy import text

    engine = _engine(schema)
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    engine.dispose()
    return dict(dropped_owned_schema=schema)


def _run(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    schema = args.schema or PREFIX + uuid4().hex
    assert re.fullmatch(PREFIX + r"[a-f0-9]{32}", schema)
    port = 20000 + secrets.randbelow(30000)
    api_name = "dydata104-http-" + uuid4().hex[:12]
    environment = {**os.environ, "DY_SESSION_SECRET": secrets.token_urlsafe(48),
                   "PYTHONPATH": "/repo:/repo/apps/api:/repo/apps/cli/src", "DY_API_TEST_MODE": "true"}
    common = ["docker", "run", "--network", "container:" + args.network_container,
              "--mount", f"type=bind,source={ROOT},target=/repo,readonly", "--workdir", "/repo"]
    for name in ("DYDATA_PUBLICATION_TEST_DATABASE_URL", "DYDATA_PUBLICATION_HTTP_CAPACITY",
                 "DY_SESSION_SECRET", "PYTHONPATH", "DY_API_TEST_MODE"):
        common.extend(["--env", name])
    report = dict(schema=schema, api_container=api_name, image=args.image,
                  api_memory_limit_bytes=MEMORY_LIMIT, api_cpus=2,
                  source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8").strip(),
                  harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    def command(mode, *, detached=False):
        limits = ["--memory", "768m", "--memory-swap", "768m", "--cpus", "2"]
        options = ["--detach", "--name", api_name] if detached else ["--rm", "--name", api_name + "-" + mode]
        return [*common, *limits, *options, args.image, "python", "/repo/scripts/benchmark_dashboard_http.py",
                mode, "--schema", schema, "--port", str(port)]

    def execute(mode, timeout):
        path = output / (mode + ".log")
        with path.open("w", encoding="utf-8") as log:
            try:
                result = subprocess.run(command(mode), env=environment, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=timeout)
            except subprocess.TimeoutExpired:
                # Killing the Docker CLI alone can leave its container running.
                subprocess.run(["docker", "rm", "--force", api_name + "-" + mode], capture_output=True)
                raise
        lines = path.read_text(encoding="utf-8").splitlines()
        assert result.returncode == 0, f"{mode} failed ({result.returncode}); inspect {path}"
        return json.loads(next(line.removeprefix(REPORT_PREFIX) for line in reversed(lines)
                               if line.startswith(REPORT_PREFIX)))

    api_started = False
    try:
        print(f"Preparing isolated source fixture; evidence directory: {output}", flush=True)
        report["prepare"] = (dict(reused_owned_schema=schema) if args.schema else execute("prepare", 300))
        subprocess.run(command("serve", detached=True), env=environment, check=True, capture_output=True)
        api_started = True
        report["probe"] = execute("probe", 300)
        report["passed"] = True
    finally:
        if api_started:
            subprocess.run(["docker", "stop", "--time", "10", api_name], capture_output=True)
            state = json.loads(subprocess.check_output(["docker", "inspect", api_name], text=True, encoding="utf-8"))[0]
            report["docker_state"] = state["State"]
            report["docker_limits"] = {key: state["HostConfig"][key] for key in ("Memory", "MemorySwap", "NanoCpus")}
            report["docker_state"].pop("Error", None)
            logs = subprocess.run(["docker", "logs", api_name], capture_output=True, text=True, encoding="utf-8")
            (output / "api.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
            subprocess.run(["docker", "rm", api_name], capture_output=True, check=True)
        try:
            report["cleanup"] = (dict(retained_owned_schema=schema) if args.keep_schema
                                 else execute("cleanup", 60))
        finally:
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    assert report["docker_state"]["OOMKilled"] is False
    assert report["docker_state"]["ExitCode"] == 0
    print("Report: " + str(output / "report.json"), flush=True)


def main() -> None:
    """Run the explicitly enabled local capacity diagnostic or one container phase."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "prepare", "serve", "probe", "cleanup"))
    parser.add_argument("--schema")
    parser.add_argument("--port", type=int, default=28764)
    parser.add_argument("--image")
    parser.add_argument("--network-container")
    parser.add_argument("--output", default=".tmp/http-capacity")
    parser.add_argument("--keep-schema", action="store_true", help="retain only this run's owned schema for independent serve/probe; clean explicitly afterward")
    args = parser.parse_args()
    if os.environ.get("DYDATA_PUBLICATION_HTTP_CAPACITY") != "1":
        parser.error("explicit opt-in DYDATA_PUBLICATION_HTTP_CAPACITY=1 is required")
    if args.mode == "run":
        if not args.image or not args.network_container:
            parser.error("run requires --image and --network-container")
        _run(args)
        return
    if not args.schema:
        parser.error("container phases require --schema")
    if args.mode == "serve":
        _serve(args.schema, args.port)
        return
    result = {"prepare": lambda: _prepare(args.schema), "probe": lambda: _probe(args.port),
              "cleanup": lambda: _cleanup(args.schema)}[args.mode]()
    print(REPORT_PREFIX + json.dumps(result, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    main()
