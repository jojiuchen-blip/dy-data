from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import json
import io
import os
import signal
import sys
import time
from uuid import uuid4
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


def test_health_checks_worker_facing_proxy_even_when_internal_cdp_works(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'FAILURE_FILE', tmp_path / 'failure')
    urls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def response(url, **kwargs):
        urls.append(url)
        if ':9222/' in url:
            raise OSError('proxy unavailable')
        return Response()

    monkeypatch.setattr(runtime, 'urlopen', response)
    monkeypatch.setattr(runtime.json, 'load', lambda _: {'webSocketDebuggerUrl': 'ws://synthetic'})
    with pytest.raises(OSError, match='proxy unavailable'):
        runtime.healthcheck()
    assert [url.split(':')[-1].split('/')[0] for url in urls] == ['9223', '9222']


def test_persistent_launch_budget_cannot_be_reset_by_replacement_process_or_minute_stability(tmp_path):
    path = tmp_path / 'budget.json'
    budget = runtime.RecoveryBudget(path)
    for moment in [1000, 1070, 1140, 1210]:
        assert budget.admit(moment) == (None, False)
    replacement = runtime.RecoveryBudget(path)
    cooldown, reported = replacement.admit(1280)
    assert cooldown == 620 and not reported
    assert runtime.RecoveryBudget(path).admit(1281) == (619, True)
    assert len(json.loads(path.read_text())['starts']) == 4
    assert replacement.admit(1900) == (None, False)
    assert len(json.loads(path.read_text())['starts']) == 4


@pytest.mark.parametrize('payload', ['[]', '{"version":1,"starts":[true],"exhaustion_reported":false}',
                                    '{"version":1,"starts":[9999],"exhaustion_reported":false}', 'bad json'])
def test_recovery_budget_invalid_state_is_not_silently_erased(tmp_path, payload):
    path = tmp_path / 'budget.json'
    path.write_text(payload)
    with pytest.raises((RuntimeError, ValueError)):
        runtime.RecoveryBudget(path).admit(1000)
    assert path.read_text() == payload


def test_stack_owns_all_critical_components_and_keeps_profile(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    services = runtime.desktop_services()
    assert services[0].name == 'xvfb'
    assert {item.name for item in services} == {'xvfb', 'chromium', 'cdp-proxy', 'fluxbox', 'x11vnc', 'websockify'}
    chromium = next(item for item in services if item.name == 'chromium')
    assert '--user-data-dir=' + str(tmp_path / 'config/chromium') in chromium.command


@pytest.mark.parametrize('component', ['chromium', 'xvfb', 'cdp-proxy'])
def test_dead_critical_process_fails_entire_generation(monkeypatch, tmp_path, component):
    monkeypatch.setattr(runtime, 'STATE_DIRECTORY', tmp_path)
    monkeypatch.setattr(runtime, 'FAILURE_FILE', tmp_path / 'failed')
    monkeypatch.setattr(runtime, 'clear_stale_locks', lambda: None)
    services = []
    for index, name in enumerate(['xvfb', 'chromium', 'cdp-proxy']):
        services.append(SimpleNamespace(name=name, process=SimpleNamespace(pid=123 + index,
            poll=lambda name=name: -9 if name == component else None), tick=lambda _: None))
    supervisor = runtime.BrowserSupervisor(display_waiter=lambda **kwargs: None)
    with pytest.raises(RuntimeError, match='critical_process_exited:' + component):
        supervisor.generation(services)


def test_exhaustion_exits_once_then_replacement_waits_without_launching(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'FAILURE_FILE', tmp_path / 'failed')
    budget = runtime.RecoveryBudget(tmp_path / 'budget.json')
    monkeypatch.setattr(runtime.time, 'time', lambda: 1000)
    for _ in range(4):
        budget.admit(1000)
    supervisor = runtime.BrowserSupervisor(budget=budget, services_factory=lambda: pytest.fail('must not launch'))
    with pytest.raises(RuntimeError, match='recovery_budget_exhausted'):
        supervisor.run()
    replacement = runtime.BrowserSupervisor(budget=runtime.RecoveryBudget(budget.path),
                                             services_factory=lambda: pytest.fail('must not launch'))
    waits = []
    def stop_after_wait(seconds):
        waits.append(seconds)
        replacement.stopping.set()
    monkeypatch.setattr(replacement.stopping, 'wait', stop_after_wait)
    replacement.run()
    assert waits == [900]
    assert runtime.FAILURE_FILE.read_text().strip() == 'recovery_budget_cooldown'


def test_reset_is_explicit_and_only_touches_supervision_state(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'STATE_DIRECTORY', tmp_path)
    monkeypatch.setattr(runtime, 'FAILURE_FILE', tmp_path / 'failed')
    path = tmp_path / 'browser-runtime-recovery.json'
    path.write_text('synthetic budget')
    runtime.FAILURE_FILE.write_text('synthetic failure')
    profile = tmp_path / 'profile-canary'
    profile.write_text('unchanged')
    runtime.reset_recovery_budget()
    assert not path.exists() and not runtime.FAILURE_FILE.exists()
    assert profile.read_text() == 'unchanged'


def test_stopping_supervisor_cleans_all_children_and_releases_clean_start(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'FAILURE_FILE', tmp_path / 'failed')
    budget = runtime.RecoveryBudget(tmp_path / 'budget.json')
    stopped = []
    services = [SimpleNamespace(name=name, stop=lambda name=name: stopped.append(name)) for name in ['xvfb', 'chromium', 'cdp-proxy']]
    supervisor = runtime.BrowserSupervisor(budget=budget, services_factory=lambda: services)
    monkeypatch.setattr(supervisor, 'generation', lambda _: supervisor.stopping.set())
    supervisor.run()
    assert stopped == ['cdp-proxy', 'chromium', 'xvfb']
    assert json.loads(budget.path.read_text())['starts'] == []


def test_child_stderr_is_private_and_bounded_by_two_rotating_files(monkeypatch, tmp_path):
    original_path = runtime.Path
    monkeypatch.setattr(runtime, 'Path', lambda value: tmp_path if value == '/tmp' else original_path(value))
    service = runtime.Service('synthetic-child', ['unused'])
    service._drain_log(io.BytesIO(b'x' * (runtime.CHILD_LOG_BYTES * 3 + 123)))
    paths = list(tmp_path.iterdir())
    assert {path.name for path in paths} == {'synthetic-child.log', 'synthetic-child.log.1'}
    assert all(0 < path.stat().st_size <= runtime.CHILD_LOG_BYTES for path in paths)
    if runtime.os.name == 'posix':
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in paths)


def test_dead_leader_still_cleans_owned_group_and_joins_log_pump(monkeypatch):
    signals = []
    joins = []
    service = runtime.Service('synthetic-dead-leader', ['unused'])
    service.process = SimpleNamespace(pid=424242, poll=lambda: -9, wait=lambda **kwargs: -9)
    service.log_thread = SimpleNamespace(join=lambda **kwargs: joins.append(kwargs['timeout']))
    monkeypatch.setattr(runtime.signal, 'SIGKILL', getattr(signal, 'SIGKILL', 9), raising=False)
    monkeypatch.setattr(runtime.os, 'killpg', lambda pid, signum: signals.append((pid, signum)), raising=False)
    service.stop()
    assert signals == [(424242, signal.SIGTERM), (424242, signal.SIGKILL)]
    assert joins == [1]


def test_already_gone_group_still_joins_log_pump(monkeypatch):
    joins = []
    service = runtime.Service('synthetic-gone-group', ['unused'])
    service.process = SimpleNamespace(pid=424242, poll=lambda: -9)
    service.log_thread = SimpleNamespace(join=lambda **kwargs: joins.append(kwargs['timeout']))
    def missing_group(*args):
        raise ProcessLookupError()
    monkeypatch.setattr(runtime.os, 'killpg', missing_group, raising=False)
    service.stop()
    assert joins == [1]


@pytest.mark.skipif(os.name != 'posix', reason='real owned process groups require POSIX; Linux CI executes this case')
def test_real_orphan_descendant_and_inherited_stderr_are_cleaned_after_only_leader_is_killed(tmp_path):
    descendant_pid_path = tmp_path / 'descendant.pid'
    descendant_code = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "Path(" + repr(str(descendant_pid_path)) + ").write_text(str(os.getpid())); "
        "print('synthetic orphan holds stderr pipe', flush=True); time.sleep(60)"
    )
    leader_code = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-u','-c'," + repr(descendant_code) + "]); time.sleep(60)"
    )
    name = 'dydata-test-orphan-' + uuid4().hex
    service = runtime.Service(name, [sys.executable, '-u', '-c', leader_code])

    def running(pid):
        try:
            fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(') ', 1)[1].split()
        except (FileNotFoundError, ProcessLookupError):
            return False
        return fields[0] not in ('Z', 'X')

    try:
        service.tick(time.monotonic())
        deadline = time.monotonic() + 5
        while not descendant_pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert descendant_pid_path.exists()
        descendant_pid = int(descendant_pid_path.read_text())
        assert running(descendant_pid)
        os.kill(service.process.pid, signal.SIGKILL)
        assert service.process.wait(timeout=5) == -signal.SIGKILL
        assert running(descendant_pid), 'setup must leave the descendant alive after only its leader dies'
        assert service.log_thread.is_alive(), 'descendant must retain the stderr pipe before cleanup'
        service.stop()
        deadline = time.monotonic() + 2
        while running(descendant_pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not running(descendant_pid)
        assert not service.log_thread.is_alive()
    finally:
        service.stop()
        for suffix in ('.log', '.log.1'):
            (Path('/tmp') / (name + suffix)).unlink(missing_ok=True)
