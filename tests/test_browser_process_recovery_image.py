"""Isolated real-image recovery proof; never mounts a production browser profile."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from uuid import uuid4

import pytest


def docker(*arguments: str, check: bool = True) -> str:
    result = subprocess.run(['docker', *arguments], capture_output=True, text=True, timeout=20, check=False)
    if check and result.returncode:
        raise AssertionError('isolated docker command failed: ' + result.stderr[:1000])
    return result.stdout


def runtime_status(container: str) -> dict:
    return json.loads(docker('exec', container, 'python3', '-c',
        "import pathlib; print(pathlib.Path('/run/browser/browser-runtime-status.json').read_text())"))


def wait_healthy(container: str, *, previous_started_at: float | None = None, timeout: float = 80) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = json.loads(docker('inspect', '--format', '{{json .State}}', container))
        if not state.get('Running'):
            raise AssertionError('isolated browser container exited before recovery')
        if state.get('Health', {}).get('Status') == 'healthy':
            status = runtime_status(container)
            if previous_started_at is None or status['started_at'] != previous_started_at:
                probe = subprocess.run(['docker', 'exec', container, 'python3',
                                        '/usr/local/bin/browser-runtime.py', 'healthcheck'],
                                       capture_output=True, timeout=7, check=False)
                if probe.returncode == 0:
                    return status
        time.sleep(0.5)
    raise AssertionError('isolated browser did not become healthy within its recovery budget')


@pytest.mark.parametrize('component', ['chromium', 'xvfb', 'cdp-proxy'])
def test_real_browser_image_recovers_owned_critical_process(component: str) -> None:
    image = os.getenv('DY_BROWSER_RECOVERY_IMAGE')
    if not image:
        pytest.skip('DY_BROWSER_RECOVERY_IMAGE is required for isolated image proof')
    assert shutil.which('docker'), 'Docker is required when an explicit recovery image is configured'
    suffix = uuid4().hex
    container = 'dydata-browser-recovery-' + suffix
    volume = 'dydata-browser-recovery-state-' + suffix
    created_container = False
    created_volume = False
    deadline = time.monotonic() + 90
    try:
        docker('volume', 'create', volume)
        created_volume = True
        created_container = True
        docker('run', '-d', '--name', container, '--network', 'none', '--restart', 'no',
               '--memory', '1g', '--shm-size', '256m', '-v', volume + ':/run/browser',
               '-e', 'VNC_PASSWORD=synthetic-recovery-test-only', '-e', 'CHROMIUM_START_URL=about:blank',
               '-e', 'SCREEN_WIDTH=800', '-e', 'SCREEN_HEIGHT=600',
               '--health-cmd', 'python3 /usr/local/bin/browser-runtime.py healthcheck',
               '--health-interval', '2s', '--health-timeout', '5s', '--health-retries', '3',
               '--health-start-period', '5s', image)
        before = wait_healthy(container, timeout=max(0, deadline - time.monotonic()))
        assert {'chromium', 'xvfb', 'cdp-proxy'} <= before['processes'].keys()
        docker('exec', container, 'python3', '-c',
               "from pathlib import Path; Path('/home/browser/.config/chromium/recovery-canary.txt').write_text('synthetic-profile-canary')")
        docker('exec', container, 'python3', '-c',
               "import json,os,signal; from pathlib import Path; state=json.loads(Path('/run/browser/browser-runtime-status.json').read_text()); os.kill(state['processes'][" + repr(component) + "], signal.SIGKILL)")
        after = wait_healthy(container, previous_started_at=before['started_at'], timeout=max(0, deadline - time.monotonic()))
        assert after['processes'][component] != before['processes'][component]
        # The injected failure kills only the leader, like a single OOM victim.
        # Recovery must clean its old renderer/desktop group, not merely start
        # a new leader while the old descendants keep resources/pipes alive.
        remaining = json.loads(docker('exec', container, 'python3', '-c',
            "import json; from pathlib import Path; live=[]; group=" + str(before['processes'][component]) + "; "
            "\nfor path in Path('/proc').iterdir():"
            "\n if path.name.isdigit():"
            "\n  try:"
            "\n   fields=(path/'stat').read_text().rsplit(') ',1)[1].split()"
            "\n   if int(fields[2])==group and fields[0] not in ('Z','X'): live.append(int(path.name))"
            "\n  except (FileNotFoundError,ProcessLookupError): pass"
            "\nprint(json.dumps(live))"))
        assert remaining == [], 'old owned process group survived its leader recovery'
        budget = json.loads(docker('exec', container, 'cat', '/run/browser/browser-runtime-recovery.json'))
        assert 2 <= len(budget['starts']) <= 4
        assert docker('exec', container, 'cat', '/home/browser/.config/chromium/recovery-canary.txt') == 'synthetic-profile-canary'
        # Exercise the real signal cleanup and persistent volume across a clean
        # container restart, without bypassing its previous failed launch.
        docker('stop', '--time', '30', container)
        state = json.loads(docker('inspect', '--format', '{{json .State}}', container))
        assert not state['Running'] and state['ExitCode'] == 0
        docker('start', container)
        wait_healthy(container, previous_started_at=after['started_at'], timeout=max(0, deadline - time.monotonic()))
        restarted_budget = json.loads(docker('exec', container, 'cat', '/run/browser/browser-runtime-recovery.json'))
        assert restarted_budget['starts'][0] == budget['starts'][0]
        assert 2 <= len(restarted_budget['starts']) <= 4
        assert docker('exec', container, 'cat', '/home/browser/.config/chromium/recovery-canary.txt') == 'synthetic-profile-canary'
        assert all(name.startswith('dydata-browser-recovery-') for name in (container, volume))
    finally:
        if created_container:
            docker('rm', '--force', container, check=False)
        if created_volume:
            docker('volume', 'rm', volume)
