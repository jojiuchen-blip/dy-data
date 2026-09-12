from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


SPEC = importlib.util.spec_from_file_location(
    'browser_runtime', Path(__file__).parents[1] / 'deploy/browser/runtime.py'
)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


def test_display_wait_retries_until_actual_x_connection(monkeypatch):
    outcomes = iter([1, 1, 0])
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=next(outcomes))

    monkeypatch.setattr(runtime.subprocess, 'run', run)
    monkeypatch.setattr(runtime.time, 'sleep', lambda _: None)
    runtime.wait_display()
    assert len(calls) == 3
    assert all(command[-1] == 'probe-display' for command in calls)


def test_display_timeout_fails_startup(monkeypatch):
    clock = iter([0, 0, 0, 1, 1, 2])
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(runtime.time, 'sleep', lambda _: None)
    monkeypatch.setattr(runtime.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match='display_startup_timeout'):
        runtime.wait_display(timeout=1)


def test_hung_display_probe_is_bounded(monkeypatch):
    outcomes = iter([False, True])

    def run(command, **kwargs):
        assert kwargs['timeout'] <= 2
        if not next(outcomes):
            raise subprocess.TimeoutExpired(command, 2)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runtime.subprocess, 'run', run)
    monkeypatch.setattr(runtime.time, 'sleep', lambda _: None)
    runtime.wait_display()


def test_failed_desktop_restarts_without_other_processes_and_stops_at_limit(monkeypatch, tmp_path):
    children = []

    def spawn(command, **kwargs):
        process = SimpleNamespace(returncode=None)
        process.poll = lambda: process.returncode
        children.append(process)
        assert command == ['x11vnc']
        return process

    monkeypatch.setattr(runtime.subprocess, 'Popen', spawn)
    monkeypatch.setattr(runtime, 'open', lambda *a, **kw: open(tmp_path / 'log', 'ab'), raising=False)
    monkeypatch.setattr(runtime, 'FAILURE_FILE', tmp_path / 'failure')
    service = runtime.Service('x11vnc', ['x11vnc'])
    service.tick(0)
    for failed_at, restart_at in [(1, 2), (3, 5), (6, 10)]:
        children[-1].returncode = 1
        service.tick(failed_at)
        service.tick(restart_at - 0.1)
        assert service.process is None
        service.tick(restart_at)
    children[-1].returncode = 1
    service.tick(11)
    service.tick(100)
    assert len(children) == 4
    assert service.exhausted
    assert runtime.FAILURE_FILE.read_text().strip() == 'x11vnc'


def test_stable_service_resets_restart_budget():
    service = runtime.Service('x11vnc', ['x11vnc'])
    service.process = SimpleNamespace(poll=lambda: None)
    service.started = 1
    service.restarts = 3
    service.tick(62)
    assert service.restarts == 0


@pytest.mark.parametrize('stage', ['cdp', 'vnc', 'websocket', 'exhausted'])
def test_health_fails_for_each_broken_component(monkeypatch, tmp_path, stage):
    monkeypatch.setattr(runtime, 'FAILURE_FILE', tmp_path / 'failure')
    if stage == 'exhausted':
        runtime.FAILURE_FILE.touch()

    def fail():
        raise OSError('unavailable')

    class Response:
        def __enter__(self):
            if stage == 'cdp':
                fail()
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(runtime, 'urlopen', lambda *a, **kw: Response())
    monkeypatch.setattr(runtime.json, 'load', lambda _: {'webSocketDebuggerUrl': 'ws://local'})
    monkeypatch.setattr(runtime, 'probe_vnc', lambda: fail() if stage == 'vnc' else None)
    monkeypatch.setattr(runtime, 'probe_websocket', lambda _: fail() if stage == 'websocket' else None)
    with pytest.raises((OSError, RuntimeError)):
        runtime.healthcheck()


def test_vnc_probe_rejects_listening_non_vnc_service(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def recv(self, count):
            return b'HTTP/1.1 200'[:count]

    monkeypatch.setattr(runtime.socket, 'create_connection', lambda *a, **kw: Connection())
    with pytest.raises(RuntimeError, match='vnc_protocol_unavailable'):
        runtime.probe_vnc()
