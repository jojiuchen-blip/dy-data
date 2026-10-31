"""Local desktop supervision and probes; never reads browser profile or cookies."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen


FAILURE_FILE = Path('/tmp/browser-runtime.failed')
STATE_DIRECTORY = Path('/run/browser')
RECOVERY_WINDOW_SECONDS = 15 * 60
MAX_STARTS_PER_WINDOW = 4
STABLE_SECONDS = 60
CHILD_LOG_BYTES = 1024 * 1024


def mark_failure(code: str) -> None:
    """Write only a bounded non-sensitive failure code with private permissions."""
    descriptor = os.open(FAILURE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        os.chmod(FAILURE_FILE, 0o600)
        output.write(code[:128] + '\n')


def probe_display() -> None:
    library = ctypes.CDLL('libX11.so.6')
    library.XOpenDisplay.argtypes = [ctypes.c_char_p]
    library.XOpenDisplay.restype = ctypes.c_void_p
    library.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = library.XOpenDisplay(os.environ.get('DISPLAY', ':99').encode())
    if not display:
        raise RuntimeError('display_not_ready')
    library.XCloseDisplay(display)


def wait_display(timeout: float = 30, stop_requested=None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stop_requested is not None and stop_requested():
            return
        try:
            result = subprocess.run(
                [sys.executable, __file__, 'probe-display'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=min(2, max(0.01, deadline - time.monotonic())), check=False,
            )
            if result.returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    raise RuntimeError('display_startup_timeout')


def read_exact(connection: socket.socket, size: int) -> bytes:
    result = b''
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise RuntimeError('connection_closed')
        result += chunk
    return result


def probe_vnc(port: int = 5900) -> None:
    with socket.create_connection(('127.0.0.1', port), timeout=1) as connection:
        if read_exact(connection, 12) != b'RFB 003.008\n':
            raise RuntimeError('vnc_protocol_unavailable')


def probe_websocket(port: int = 6080) -> None:
    key = base64.b64encode(os.urandom(16)).decode('ascii')
    accept = base64.b64encode(hashlib.sha1(
        (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode('ascii')
    ).digest()).decode('ascii')
    with socket.create_connection(('127.0.0.1', port), timeout=1) as connection:
        connection.sendall((
            'GET /websockify HTTP/1.1\r\nHost: localhost\r\n'
            'Upgrade: websocket\r\nConnection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
            'Sec-WebSocket-Protocol: binary\r\n\r\n'
        ).encode('ascii'))
        headers = b''
        while not headers.endswith(b'\r\n\r\n'):
            headers += read_exact(connection, 1)
            if len(headers) > 8192:
                raise RuntimeError('websocket_headers_too_large')
        lines = headers.decode('ascii').split('\r\n')
        values = {name.lower(): value.strip() for line in lines[1:] if ':' in line
                  for name, value in [line.split(':', 1)]}
        if not lines[0].startswith('HTTP/1.1 101 ') or values.get('sec-websocket-accept') != accept:
            raise RuntimeError('websocket_upgrade_failed')
        frame = read_exact(connection, 2)
        if frame != b'\x82\x0c' or read_exact(connection, 12) != b'RFB 003.008\n':
            raise RuntimeError('websocket_vnc_unavailable')


def healthcheck() -> None:
    if FAILURE_FILE.exists():
        raise RuntimeError('desktop_restart_limit')
    for setting, default in [('CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT', '9223'),
                             ('CHROMIUM_REMOTE_DEBUGGING_PORT', '9222')]:
        port = int(os.environ.get(setting, default))
        with urlopen(f'http://127.0.0.1:{port}/json/version', timeout=1) as response:
            if not json.load(response).get('webSocketDebuggerUrl'):
                raise RuntimeError('cdp_unavailable')
    probe_vnc()
    probe_websocket(int(os.environ.get('PORT', os.environ.get('NOVNC_PORT', '6080'))))


class Service:
    """Restart a failed desktop child at most three times until stable for a minute."""

    def __init__(self, name: str, command: list[str]) -> None:
        self.name = name
        self.command = command
        self.process: subprocess.Popen | None = None
        self.started = 0.0
        self.retry_at = 0.0
        self.restarts = 0
        self.exhausted = False
        self.log_thread: threading.Thread | None = None

    def tick(self, now: float) -> None:
        if self.exhausted:
            return
        if self.process is not None:
            if self.process.poll() is None:
                if now - self.started >= 60:
                    self.restarts = 0
                return
            self.process = None
            if self.restarts >= 3:
                self.exhausted = True
                mark_failure(self.name)
                print(f'desktop_restart_limit service={self.name}', flush=True)
                return
            self.retry_at = now + 2 ** self.restarts
            self.restarts += 1
            print(f'desktop_retry service={self.name} attempt={self.restarts}', flush=True)
        if now >= self.retry_at:
            self.process = subprocess.Popen(
                self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            if getattr(self.process, 'stdout', None) is not None:
                self.log_thread = threading.Thread(target=self._drain_log, args=(self.process.stdout,), daemon=True)
                self.log_thread.start()
            self.started = now

    def _drain_log(self, stream) -> None:
        path = Path('/tmp') / (self.name + '.log')
        failed = False
        with stream:
            read_chunk = getattr(stream, 'read1', stream.read)
            while chunk := read_chunk(65536):
                if failed:
                    continue
                try:
                    if path.is_symlink():
                        raise RuntimeError('child_log_symlink')
                    if path.exists() and path.stat().st_size + len(chunk) > CHILD_LOG_BYTES:
                        os.replace(path, path.with_suffix('.log.1'))
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                    with os.fdopen(descriptor, 'ab') as output:
                        os.chmod(path, 0o600)
                        output.write(chunk)
                except (OSError, RuntimeError):
                    # Keep draining so a log error cannot deadlock the child.
                    failed = True
                    print('browser_log_unavailable service=' + self.name, flush=True)

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=3)
            # A crashed group leader can leave Chromium descendants behind.
            os.killpg(self.process.pid, signal.SIGKILL)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=3)
        except ProcessLookupError:
            pass
        if self.log_thread is not None:
            self.log_thread.join(timeout=1)


def desktop_services() -> list[Service]:
    """Build the complete owned process tree, with Xvfb first."""
    internal = os.environ.get('CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT', '9223')
    return [
        Service('xvfb', ['Xvfb', os.environ.get('DISPLAY', ':99'), '-screen', '0',
                        os.environ.get('SCREEN_WIDTH', '1440') + 'x' + os.environ.get('SCREEN_HEIGHT', '1000') + 'x24', '-nolisten', 'tcp']),
        Service('chromium', ['chromium', '--no-first-run', '--no-default-browser-check',
                            '--disable-breakpad', '--disable-crash-reporter', '--disable-dev-shm-usage',
                            '--no-sandbox', '--crash-dumps-dir=/tmp/chromium-crashes',
                            '--user-data-dir=' + str(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'chromium'),
                            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=' + internal,
                            os.environ.get('CHROMIUM_START_URL', 'about:blank')]),
        Service('cdp-proxy', [sys.executable, __file__, 'cdp-proxy']),
        Service('fluxbox', ['fluxbox']),
        Service('x11vnc', ['x11vnc', '-display', os.environ.get('DISPLAY', ':99'),
                          '-forever', '-shared', '-rfbauth', str(Path.home() / '.vnc/passwd'),
                          '-rfbport', '5900', '-localhost']),
        Service('websockify', ['websockify', '--web=/usr/share/novnc/',
                              '0.0.0.0:' + os.environ.get('PORT', os.environ.get('NOVNC_PORT', '6080')),
                              'localhost:5900']),
    ]


def atomic_json(path: Path, value: dict) -> None:
    """Write one bounded private runtime document without following links."""
    if path.is_symlink():
        raise RuntimeError('runtime_state_symlink')
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, sort_keys=True).encode('utf-8')
    if len(payload) > 4096:
        raise RuntimeError('runtime_state_size_limit')
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            os.chmod(temporary, 0o600)
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class RecoveryBudget:
    """Persistent rolling launch limit, shared by replacement containers."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or STATE_DIRECTORY / 'browser-runtime-recovery.json'

    def read(self, now: float) -> dict:
        """Validate state; never reset malformed or unreadable history."""
        if not self.path.exists():
            return {'version': 1, 'starts': [], 'exhaustion_reported': False}
        if self.path.is_symlink() or self.path.stat().st_size > 4096:
            raise RuntimeError('recovery_state_invalid')
        state = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(state, dict):
            raise RuntimeError('recovery_state_invalid')
        starts = state.get('starts')
        if (state.get('version') != 1 or not isinstance(starts, list) or len(starts) > MAX_STARTS_PER_WINDOW
                or not isinstance(state.get('exhaustion_reported'), bool)
                or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
                       or item < 0 or item > now + 5 for item in starts)):
            raise RuntimeError('recovery_state_invalid')
        state['starts'] = [item for item in starts if item > now - RECOVERY_WINDOW_SECONDS]
        if len(state['starts']) < MAX_STARTS_PER_WINDOW:
            state['exhaustion_reported'] = False
        return state

    def admit(self, now: float) -> tuple[float | None, bool]:
        """Reserve a launch or return cooldown and its already-reported flag."""
        state = self.read(now)
        if len(state['starts']) >= MAX_STARTS_PER_WINDOW:
            reported = state['exhaustion_reported']
            state['exhaustion_reported'] = True
            atomic_json(self.path, state)
            return max(0.1, min(state['starts']) + RECOVERY_WINDOW_SECONDS - now), reported
        state['starts'].append(now)
        atomic_json(self.path, state)
        return None, False

    def cancel(self, started_at: float) -> None:
        """A deliberate clean shutdown does not spend a failed-start allowance."""
        state = self.read(time.time())
        state['starts'] = [item for item in state['starts'] if item != started_at]
        atomic_json(self.path, state)


def clear_stale_locks() -> None:
    """Remove only known process locks after the owned stack has stopped."""
    Path('/tmp/.X99-lock').unlink(missing_ok=True)
    profile = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'chromium'
    for name in ('SingletonCookie', 'SingletonLock', 'SingletonSocket'):
        (profile / name).unlink(missing_ok=True)


class BrowserSupervisor:
    """Recover the entire dependent stack; preserve profile and rolling budget."""

    def __init__(self, budget=None, services_factory=None, probe=None, display_waiter=None) -> None:
        self.budget = budget or RecoveryBudget()
        self.services_factory = services_factory or desktop_services
        self.probe = probe or healthcheck
        self.display_waiter = display_waiter or wait_display
        self.stopping = threading.Event()
        self.consecutive_failures = 0

    def generation(self, services: list[Service]) -> None:
        """Own one stack generation through startup, health and shutdown."""
        clear_stale_locks()
        FAILURE_FILE.unlink(missing_ok=True)
        services[0].tick(time.monotonic())
        self.display_waiter(stop_requested=self.stopping.is_set)
        if self.stopping.is_set():
            return
        for service in services[1:]:
            service.tick(time.monotonic())
        # Each Service starts once per generation. Stack recovery always uses
        # the persistent rolling ledger, not its legacy per-child tick budget.
        atomic_json(STATE_DIRECTORY / 'browser-runtime-status.json', {
            'version': 1, 'started_at': time.time(),
            'processes': {service.name: service.process.pid for service in services},
        })
        deadline = time.monotonic() + 30
        healthy_since = None
        next_probe = 0.0
        failures = 0
        while not self.stopping.is_set():
            now = time.monotonic()
            for service in services:
                if service.process.poll() is not None:
                    raise RuntimeError('critical_process_exited:' + service.name)
            if now >= next_probe:
                next_probe = now + 2
                try:
                    self.probe()
                    failures = 0
                    healthy_since = now if healthy_since is None else healthy_since
                    if now - healthy_since >= STABLE_SECONDS:
                        # Stability resets backoff, never the rolling launch ledger.
                        self.consecutive_failures = 0
                except (OSError, ValueError, RuntimeError):
                    healthy_since = None
                    failures += 1
                    if now >= deadline and failures >= 3:
                        raise RuntimeError('critical_health_unavailable')
            self.stopping.wait(0.25)

    def run(self) -> None:
        """Apply persisted admission before launching any desktop process."""
        while not self.stopping.is_set():
            started_at = time.time()
            cooldown, already_reported = self.budget.admit(started_at)
            if cooldown is not None:
                mark_failure('recovery_budget_cooldown')
                if not already_reported:
                    raise RuntimeError('recovery_budget_exhausted')
                # One failed exit reports exhaustion; replacement containers wait
                # for the same bounded window instead of repeatedly relaunching.
                print('browser_recovery_cooldown seconds=' + str(round(cooldown)), flush=True)
                self.stopping.wait(min(cooldown, RECOVERY_WINDOW_SECONDS))
                continue
            services = self.services_factory()
            try:
                self.generation(services)
            except (OSError, ValueError, RuntimeError) as exc:
                self.consecutive_failures += 1
                code = str(exc) if isinstance(exc, RuntimeError) and str(exc).startswith(
                    ('critical_process_exited:', 'display_startup_timeout', 'critical_health_unavailable')
                ) else 'critical_stack_failed'
                mark_failure(code)
                print('browser_stack_failed code=' + code + ' type=' + type(exc).__name__, flush=True)
            finally:
                for service in reversed(services):
                    service.stop()
            if self.stopping.is_set():
                self.budget.cancel(started_at)
                return
            self.stopping.wait(2 ** min(max(self.consecutive_failures - 1, 0), 2))


def cdp_proxy() -> None:
    """Bridge the worker-facing CDP port to Chromium's local endpoint."""
    import socketserver

    target_port = int(os.environ.get('CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT', '9223'))
    bind_port = int(os.environ.get('CHROMIUM_REMOTE_DEBUGGING_PORT', '9222'))
    authority = f'127.0.0.1:{target_port}'.encode('ascii')

    class ProxyHandler(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.create_connection(('127.0.0.1', target_port), timeout=5) as upstream:
                upstream.settimeout(None)

                def pipe(source, destination, rewrite=False):
                    try:
                        first = True
                        while data := source.recv(65536):
                            if first and rewrite:
                                while b'\r\n\r\n' not in data:
                                    if len(data) > 65536:
                                        return
                                    chunk = source.recv(65536)
                                    if not chunk:
                                        return
                                    data += chunk
                                headers, body = data.split(b'\r\n\r\n', 1)
                                lines = []
                                for line in headers.split(b'\r\n'):
                                    if line.lower().startswith(b'host:'):
                                        line = b'Host: ' + authority
                                    elif line.lower().startswith(b'origin:'):
                                        line = b'Origin: http://' + authority
                                    lines.append(line)
                                data = b'\r\n'.join(lines) + b'\r\n\r\n' + body
                            first = False
                            destination.sendall(data)
                    except OSError:
                        pass
                    finally:
                        try:
                            destination.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass

                sender = threading.Thread(target=pipe, args=(self.request, upstream, True), daemon=True)
                sender.start()
                pipe(upstream, self.request)

    class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(('0.0.0.0', bind_port), ProxyHandler) as server:
        server.serve_forever()


def reset_recovery_budget() -> None:
    """Explicit operator recovery; stop the browser service before using this."""
    path = STATE_DIRECTORY / 'browser-runtime-recovery.json'
    if path.is_symlink():
        raise RuntimeError('recovery_state_invalid')
    path.unlink(missing_ok=True)
    FAILURE_FILE.unlink(missing_ok=True)


def serve() -> None:
    """Supervise browser prerequisites without changing session or source facts."""
    supervisor = BrowserSupervisor()

    def stop(signum: int, frame: object) -> None:
        supervisor.stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    supervisor.run()


if __name__ == '__main__':
    commands = {'probe-display': probe_display, 'wait-display': wait_display,
                'healthcheck': healthcheck, 'serve': serve, 'cdp-proxy': cdp_proxy,
                'reset-recovery-budget': reset_recovery_budget}
    try:
        commands[sys.argv[1]]()
    except Exception as exc:
        # Only controlled failures or exception types; never echo credentials/URLs.
        print(f'browser_runtime_failed type={type(exc).__name__}', file=sys.stderr)
        raise SystemExit(1)
