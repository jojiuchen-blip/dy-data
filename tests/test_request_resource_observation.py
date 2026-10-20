"""Real ASGI lifecycle and application integration for privacy-safe observations."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import logging.config
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.routing import Mount, Route, Router

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402
from dy_api import request_resource_observation as observation  # noqa: E402


SECRET = "sensitive-business-identifier-987654321"


@pytest.fixture()
def observations():
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    log = observation.logger
    previous = (list(log.handlers), log.level, log.disabled, log.propagate)
    observation.configure_request_resource_logging()
    log.addHandler(Capture())
    try:
        yield records
    finally:
        log.handlers, log.level, log.disabled, log.propagate = previous


def events(records):
    return [json.loads(record.getMessage()) for record in records]


def scope(path="/resource/value", *, method="GET", kind="http"):
    return {"type": kind, "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode(),
            "root_path": "", "query_string": f"token={SECRET}".encode(),
            "headers": [(b"authorization", f"Bearer {SECRET}".encode()), (b"cookie", SECRET.encode()),
                        (b"x-request-id", SECRET.encode())],
            "scheme": "http", "server": ("testserver", 80), "client": ("127.0.0.1", 12345)}


async def unused_receive():
    pytest.fail("the observer must not read or prefetch the request body")


async def discard_send(message):
    pass


def middleware(app, *, path="/resource/{item}", rss_reader=lambda: 123456):
    # A real registered routing table, independently from the controlled ASGI
    # response used to exercise message forwarding and cancellation precisely.
    router = Router(routes=[Route(path, app, methods=["GET", "POST"])])
    return observation.RequestResourceObservationMiddleware(app, router=router, rss_reader=rss_reader)


def test_create_app_starts_before_endpoint_and_never_logs_sensitive_request_data(observations):
    app = create_app()

    @app.post("/_observation/{business_id}")
    async def endpoint(business_id: str, request: Request):
        recorded = events(observations)
        assert len(recorded) == 1 and recorded[0]["event"] == "api_request_start"
        assert business_id == SECRET and (await request.json())["private"] == SECRET
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        return {"ok": True}

    response = TestClient(app).post(f"/_observation/{SECRET}?token={SECRET}", json={"private": SECRET},
                                    headers={"authorization": f"Bearer {SECRET}", "cookie": SECRET,
                                             "x-request-id": SECRET})
    assert response.status_code == 200 and response.json() == {"ok": True}
    start, end = events(observations)
    assert start["route_template"] == end["route_template"] == "/_observation/{business_id}"
    assert start["request_id"] == end["request_id"] and len(start["request_id"]) == 32
    assert start["request_id"] != SECRET
    assert (start["active_requests"], end["active_requests"]) == (1, 0)
    assert start["duration_ms"] is None and end["duration_ms"] >= 0
    assert end["status"] == 200 and end["exception_class"] is None
    assert SECRET not in " ".join(record.getMessage() for record in observations)
    assert all(record.exc_info is None and record.stack_info is None for record in observations)


@pytest.mark.parametrize("path,method,status,template", [
    ("/docs", "GET", 200, "/docs"),
    ("/docs", "POST", 405, "/docs"),
    (f"/missing/{SECRET}", "GET", 404, "unknown"),
])
def test_real_app_registered_routes_method_errors_and_404(observations, path, method, status, template):
    response = TestClient(create_app()).request(method, path + f"?private={SECRET}")
    assert response.status_code == status
    start, end = events(observations)
    assert start["route_template"] == end["route_template"] == template
    assert end["status"] == status and end["active_requests"] == 0
    assert SECRET not in json.dumps(events(observations))


@pytest.mark.parametrize("method,suffix,status", [
    ("GET", f"/records/{SECRET}", 200),
    ("POST", f"/records/{SECRET}", 405),
    ("HEAD", f"/records/{SECRET}", 405),
    ("GET", f"/missing/{SECRET}", 404),
])
def test_nested_include_router_uses_registered_prefixes_before_endpoint(observations, method, suffix, status):
    app = create_app()
    calls = []
    child = APIRouter(prefix="/child")

    @child.get("/records/{record_id}")
    async def endpoint(record_id: str):
        assert events(observations)[0]["route_template"] == "/extra/outer/nested/child/records/{record_id}"
        calls.append(record_id)
        return {"record": record_id}

    parent = APIRouter(prefix="/outer")
    parent.include_router(child, prefix="/nested")
    app.include_router(parent, prefix="/extra")
    response = TestClient(app).request(method, "/extra/outer/nested/child" + suffix + f"?token={SECRET}")
    assert response.status_code == status
    assert calls == ([SECRET] if status == 200 else [])
    start, end = events(observations)
    expected = "unknown" if status == 404 else "/extra/outer/nested/child/records/{record_id}"
    assert start["route_template"] == end["route_template"] == expected
    assert end["active_requests"] == 0
    assert SECRET not in json.dumps([start, end])


@pytest.mark.parametrize("method,suffix,status", [
    ("GET", f"/records/{SECRET}", 200),
    ("POST", f"/records/{SECRET}", 405),
    ("GET", f"/missing/{SECRET}", 404),
])
def test_parameterized_mount_with_included_router_keeps_only_registered_templates(observations, method, suffix, status):
    child = FastAPI()
    router = APIRouter()

    @router.get("/records/{record_id}")
    async def endpoint(record_id: str):
        return {"ok": True}

    child.include_router(router, prefix="/api/v2")
    app = create_app()
    app.mount("/tenants/{tenant_id}", child)
    response = TestClient(app, root_path="/deployment").request(
        method, f"/deployment/tenants/{SECRET}/api/v2" + suffix)
    assert response.status_code == status
    expected = "unknown" if status == 404 else "/tenants/{tenant_id}/api/v2/records/{record_id}"
    assert {item["route_template"] for item in events(observations)} == {expected}
    assert SECRET not in json.dumps(events(observations))


def test_full_match_after_included_partial_uses_selected_registered_route(observations):
    first, second = APIRouter(), APIRouter()

    @first.get("/objects/{object_id}")
    async def first_endpoint(object_id: str):
        pytest.fail("method mismatch must not execute the first endpoint")

    @second.post("/objects/fixed")
    async def second_endpoint():
        return {"selected": True}

    app = create_app()
    app.include_router(first, prefix="/version")
    app.include_router(second, prefix="/version")
    response = TestClient(app).post("/version/objects/fixed")
    assert response.status_code == 200 and response.json() == {"selected": True}
    assert {item["route_template"] for item in events(observations)} == {"/version/objects/fixed"}


@pytest.mark.parametrize("path,method,status,template", [
    ("/api/v1/dashboard/douyin-ranking", "GET", 401, "/api/v1/dashboard/douyin-ranking"),
    ("/api/v1/dashboard/douyin-ranking/export", "GET", 401, "/api/v1/dashboard/douyin-ranking/export"),
    ("/api/v1/dashboard/publications/douyin-ranking/filters", "GET", 401,
     "/api/v1/dashboard/publications/{module}/filters"),
    (f"/api/v1/stores/{SECRET}/monthly-settlement", "GET", 401,
     "/api/v1/stores/{store_id}/monthly-settlement"),
    ("/api/v1/dashboard/douyin-ranking", "POST", 405, "/api/v1/dashboard/douyin-ranking"),
])
def test_actual_included_business_routes_are_classified_without_bypassing_auth(observations, path, method, status, template):
    response = TestClient(create_app()).request(method, path + f"?private={SECRET}")
    assert response.status_code == status
    start, end = events(observations)
    assert start["route_template"] == end["route_template"] == template
    assert end["active_requests"] == 0 and end["status"] == status
    assert SECRET not in json.dumps([start, end])


def test_included_matcher_never_uses_spoofed_scope_or_calls_registered_handlers(observations, monkeypatch):
    router = APIRouter()
    handler_calls = []

    @router.get("/records/{record_id}")
    async def endpoint(record_id: str):
        handler_calls.append(record_id)

    registered = FastAPI()
    registered.include_router(router, prefix="/registered")

    def forbidden_match(request_scope):
        pytest.fail("observer must not invoke routing hooks or construct effective handlers")

    for route in [*router.routes, *registered.router.routes]:
        monkeypatch.setattr(route, "matches", forbidden_match)
    original = scope(f"/registered/records/{SECRET}")
    original["route"] = Route("/" + SECRET, endpoint)
    original["fastapi"] = {"private": SECRET}
    original_keys = set(original)
    original_fastapi = dict(original["fastapi"])

    async def app(request_scope, receive, send):
        assert request_scope is original

    observer = observation.RequestResourceObservationMiddleware(app, router=registered.router)
    asyncio.run(observer(original, unused_receive, discard_send))
    assert handler_calls == []
    assert set(original) == original_keys and original["fastapi"] == original_fastapi
    assert {item["route_template"] for item in events(observations)} == {"/registered/records/{record_id}"}
    assert SECRET not in json.dumps(events(observations))


def test_real_app_handled_http_error_preserves_response_without_exception_message(observations):
    app = create_app()

    @app.get("/_handled/{identifier}")
    async def handled(identifier: str):
        raise HTTPException(status_code=418, detail=SECRET)

    response = TestClient(app).get(f"/_handled/{SECRET}")
    assert response.status_code == 418 and response.json() == {"detail": SECRET}
    start, end = events(observations)
    assert start["route_template"] == "/_handled/{identifier}"
    assert end["status"] == 418 and end["exception_class"] is None
    assert SECRET not in json.dumps(events(observations))


def test_real_app_unhandled_exception_keeps_fastapi_500_and_returns_counter(observations):
    app = create_app()

    @app.get("/_failure/{identifier}")
    async def failing(identifier: str):
        raise RuntimeError(SECRET)

    response = TestClient(app, raise_server_exceptions=False).get(f"/_failure/{SECRET}")
    assert response.status_code == 500 and response.text == "Internal Server Error"
    start, end = events(observations)
    assert start["route_template"] == "/_failure/{identifier}"
    assert end["exception_class"] == "RuntimeError" and end["active_requests"] == 0
    # The outer ServerErrorMiddleware sends the 500 after the observation exits.
    assert end["status"] is None and SECRET not in json.dumps(events(observations))


def test_stream_chunks_and_trailers_are_forwarded_immediately_without_buffering(observations):
    async def scenario():
        first_delivered, release = asyncio.Event(), asyncio.Event()
        messages = [
            {"type": "http.response.start", "status": 200, "headers": [(b"x-private", SECRET.encode())], "trailers": True},
            {"type": "http.response.body", "body": b"first", "more_body": True},
            {"type": "http.response.body", "body": b"second", "more_body": False},
            {"type": "http.response.trailers", "headers": [(b"checksum", b"original")]},
        ]
        forwarded = []

        async def app(request_scope, receive, send):
            await send(messages[0])
            await send(messages[1])
            await release.wait()
            await send(messages[2])
            await send(messages[3])

        async def send(message):
            forwarded.append(message)
            if message is messages[1]:
                first_delivered.set()

        observer = middleware(app)
        task = asyncio.create_task(observer(scope(), unused_receive, send))
        try:
            await asyncio.wait_for(first_delivered.wait(), 2)
            assert forwarded == messages[:2] and not task.done()
            assert observer.active_requests == 1 and len(events(observations)) == 1
        finally:
            release.set()
        await task
        assert all(actual is expected for actual, expected in zip(forwarded, messages, strict=True))
        assert observer.active_requests == 0 and events(observations)[1]["status"] == 200
        assert SECRET not in json.dumps(events(observations))

    asyncio.run(scenario())


def test_cancellation_is_reraised_and_counter_released_in_finally(observations):
    async def scenario():
        entered = asyncio.Event()

        async def app(request_scope, receive, send):
            entered.set()
            await asyncio.Event().wait()

        observer = middleware(app)
        task = asyncio.create_task(observer(scope(), unused_receive, discard_send))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel(SECRET)
        with pytest.raises(asyncio.CancelledError, match=SECRET):
            await task
        assert observer.active_requests == 0

    asyncio.run(scenario())
    start, end = events(observations)
    assert end["exception_class"] == "CancelledError" and end["status"] is None
    assert end["active_requests"] == 0 and SECRET not in json.dumps([start, end])


@pytest.mark.parametrize("cancel_after_first_chunk", [False, True])
def test_real_app_stream_lifetime_and_cancellation_are_observed(observations, cancel_after_first_chunk):
    async def scenario():
        first_delivered, release = asyncio.Event(), asyncio.Event()
        sent = []

        class StreamEndpoint:
            async def __call__(self, request_scope, receive, send):
                await send({"type": "http.response.start", "status": 206, "headers": []})
                await send({"type": "http.response.body", "body": b"first", "more_body": True})
                await release.wait()
                await send({"type": "http.response.body", "body": b"last", "more_body": False})

        app = create_app()
        app.add_route("/_stream/{identifier}", StreamEndpoint(), methods=["GET"])
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})

        async def send(message):
            sent.append(message)
            if message.get("body") == b"first":
                first_delivered.set()

        task = asyncio.create_task(app(scope(f"/_stream/{SECRET}"), incoming.get, send))
        try:
            await asyncio.wait_for(first_delivered.wait(), 2)
            assert len(events(observations)) == 1 and not task.done()
            if cancel_after_first_chunk:
                task.cancel(SECRET)
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                release.set()
                await task
                assert b"".join(message.get("body", b"") for message in sent) == b"firstlast"
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        start, end = events(observations)
        assert start["route_template"] == end["route_template"] == "/_stream/{identifier}"
        assert end["active_requests"] == 0 and end["status"] == 206
        assert end["exception_class"] == ("CancelledError" if cancel_after_first_chunk else None)
        assert SECRET not in json.dumps([start, end])

    asyncio.run(scenario())


@pytest.mark.parametrize("during_send", [False, True])
def test_disconnect_does_not_swallow_error_or_leak_active_count(observations, during_send):
    async def scenario():
        disconnected = {"type": "http.disconnect"}
        send_error = OSError(SECRET)
        reads = 0

        async def receive():
            nonlocal reads
            reads += 1
            return disconnected

        async def app(request_scope, receiver, send):
            if during_send:
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": SECRET.encode()})
            else:
                assert await receiver() is disconnected

        async def send(message):
            if message["type"] == "http.response.body":
                raise send_error

        observer = middleware(app)
        if during_send:
            with pytest.raises(OSError) as caught:
                await observer(scope(), receive, send)
            assert caught.value is send_error and reads == 0
        else:
            await observer(scope(), receive, send)
            assert reads == 1
        assert observer.active_requests == 0

    asyncio.run(scenario())
    assert events(observations)[1]["exception_class"] == ("OSError" if during_send else None)
    assert SECRET not in json.dumps(events(observations))


def test_concurrent_http_calls_have_exact_counts_and_distinct_internal_ids(observations):
    async def scenario():
        both_entered = asyncio.Event()
        releases = [asyncio.Event(), asyncio.Event()]
        entered = 0

        async def app(request_scope, receive, send):
            nonlocal entered
            index = entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await releases[index].wait()
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        observer = middleware(app)
        tasks = [asyncio.create_task(observer(scope(f"/resource/{SECRET}-{number}"), unused_receive, discard_send))
                 for number in range(2)]
        try:
            await asyncio.wait_for(both_entered.wait(), 2)
            assert observer.active_requests == 2
            assert [record["active_requests"] for record in events(observations)] == [1, 2]
            releases[0].set()
            await tasks[0]
            assert observer.active_requests == 1
        finally:
            for release in releases:
                release.set()
        await asyncio.gather(*tasks)
        assert observer.active_requests == 0

    asyncio.run(scenario())
    records = events(observations)
    assert [record["active_requests"] for record in records] == [1, 2, 1, 0]
    assert len({record["request_id"] for record in records}) == 2
    assert {record["route_template"] for record in records} == {"/resource/{item}"}
    assert SECRET not in json.dumps(records)


@pytest.mark.parametrize("kind", ["websocket", "lifespan"])
def test_non_http_scopes_are_untouched_and_unlogged(observations, kind):
    async def scenario():
        original_scope = scope(kind=kind)

        async def app(request_scope, receive, send):
            assert request_scope is original_scope and receive is unused_receive and send is discard_send

        observer = middleware(app)
        await observer(original_scope, unused_receive, discard_send)
        assert observer.active_requests == 0

    asyncio.run(scenario())
    assert observations == []


@pytest.mark.parametrize("raises", [False, True])
def test_log_sink_failure_never_changes_application_result_or_original_error(observations, monkeypatch, raises):
    original = RuntimeError(SECRET)
    sent = []

    def log_failure(*args, **kwargs):
        raise OSError("private logging failure that must not be emitted")

    monkeypatch.setattr(observation.logger, "info", log_failure)

    async def app(request_scope, receive, send):
        if raises:
            raise original
        await send({"type": "http.response.start", "status": 204, "headers": []})

    async def send(message):
        sent.append(message)

    observer = middleware(app)
    if raises:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(observer(scope(), unused_receive, send))
        assert caught.value is original
    else:
        asyncio.run(observer(scope(), unused_receive, send))
        assert sent == [{"type": "http.response.start", "status": 204, "headers": []}]
    assert observer.active_requests == 0 and observations == []


@pytest.mark.parametrize("value", [None, 0, -1, True, 1.5, "raise"])
def test_unknown_or_invalid_rss_is_null_never_zero(observations, value):
    async def app(request_scope, receive, send):
        pass

    def rss_reader():
        if value == "raise":
            raise RuntimeError(SECRET)
        return value

    asyncio.run(middleware(app, rss_reader=rss_reader)(scope(), unused_receive, discard_send))
    assert all(record["rss_bytes"] is None for record in events(observations))


def test_linux_rss_reader_is_current_resident_pages_and_unavailable_is_unknown(monkeypatch):
    def statm(path, mode):
        assert path == "/proc/self/statm" and mode == "rb"
        return io.BytesIO(b"999 25 8 1 0 1 0\n")

    monkeypatch.setattr("builtins.open", statm)
    monkeypatch.setattr(os, "sysconf", lambda key: 4096, raising=False)
    assert observation.read_process_rss_bytes() == 25 * 4096

    def unavailable(path, mode):
        raise OSError(SECRET)

    monkeypatch.setattr("builtins.open", unavailable)
    assert observation.read_process_rss_bytes() is None


def test_nested_registered_mount_template_contains_no_matched_parameter_values(observations):
    async def app(request_scope, receive, send):
        pass

    child = Router(routes=[Route("/records/{record_id}", app)])
    router = Router(routes=[Mount("/tenants/{tenant_id}", app=child)])
    observer = observation.RequestResourceObservationMiddleware(app, router=router)
    asyncio.run(observer(scope(f"/tenants/{SECRET}/records/{SECRET}"), unused_receive, discard_send))
    assert {record["route_template"] for record in events(observations)} == {"/tenants/{tenant_id}/records/{record_id}"}
    assert SECRET not in json.dumps(events(observations))


def test_default_uvicorn_logging_configuration_still_emits_two_info_lines_to_stdout():
    code = """
import asyncio, json, logging, logging.config, sys
import httpx
from uvicorn.config import LOGGING_CONFIG
logging.config.dictConfig(LOGGING_CONFIG)
sys.path.insert(0, 'apps/api')
from dy_api.main import app
logging.getLogger().setLevel(logging.WARNING)
assert not logging.getLogger().isEnabledFor(logging.INFO)
async def run():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        response = await client.get('/docs?token=sensitive-business-identifier-987654321')
        assert response.status_code == 200
asyncio.run(run())
"""
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    for key in ("DY_AGENT_ENVIRONMENT", "DY_WEB_BASE_URL", "DATABASE_URL", "DY_DATABASE_URL"):
        environment.pop(key, None)
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment,
                            capture_output=True, encoding="utf-8", timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert [record["event"] for record in records] == ["api_request_start", "api_request_end"]
    assert records[1]["status"] == 200 and records[1]["active_requests"] == 0
    assert SECRET not in result.stdout and SECRET not in result.stderr
