"""Local desktop supervision and probes; never reads browser profile or cookies."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


FAILURE_FILE = Path('/tmp/browser-runtime.failed')


def probe_display() -> None:
    library = ctypes.CDLL('libX11.so.6')
    library.XOpenDisplay.argtypes = [ctypes.c_char_p]
    library.XOpenDisplay.restype = ctypes.c_void_p
    library.XCloseDisplay.argtypes = [ctypes.c_void_p]
    display = library.XOpenDisplay(os.environ.get('DISPLAY', ':99').encode())
    if not display:
        raise RuntimeError('display_not_ready')
    library.XCloseDisplay(display)


def wait_display(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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
    port = int(os.environ.get('CHROMIUM_REMOTE_DEBUGGING_INTERNAL_PORT', '9223'))
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
                FAILURE_FILE.write_text(self.name + '\n', encoding='utf-8')
                print(f'desktop_restart_limit service={self.name}', flush=True)
                return
            self.retry_at = now + 2 ** self.restarts
            self.restarts += 1
            print(f'desktop_retry service={self.name} attempt={self.restarts}', flush=True)
        if now >= self.retry_at:
            with open(f'/tmp/{self.name}.log', 'ab') as output:
                self.process = subprocess.Popen(
                    self.command, stdout=output, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            self.started = now

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=3)
        except ProcessLookupError:
            pass


def serve() -> None:
    services = [
        Service('fluxbox', ['fluxbox']),
        Service('x11vnc', ['x11vnc', '-display', os.environ.get('DISPLAY', ':99'),
                          '-forever', '-shared', '-rfbauth', str(Path.home() / '.vnc/passwd'),
                          '-rfbport', '5900', '-localhost']),
        Service('websockify', ['websockify', '--web=/usr/share/novnc/',
                              '0.0.0.0:' + os.environ.get('PORT', os.environ.get('NOVNC_PORT', '6080')),
                              'localhost:5900']),
    ]
    stopping = False

    def stop(signum: int, frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            for service in services:
                service.tick(time.monotonic())
            time.sleep(0.25)
    finally:
        for service in reversed(services):
            service.stop()


if __name__ == '__main__':
    commands = {'probe-display': probe_display, 'wait-display': wait_display,
                'healthcheck': healthcheck, 'serve': serve}
    try:
        commands[sys.argv[1]]()
    except Exception as exc:
        # Only controlled failures or exception types; never echo credentials/URLs.
        print(f'browser_runtime_failed type={type(exc).__name__}', file=sys.stderr)
        raise SystemExit(1)
