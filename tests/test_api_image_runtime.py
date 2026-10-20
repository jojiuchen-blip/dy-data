"""Exercise the built API image without a checkout mount or external services."""

import os
import subprocess
import time
import uuid

import pytest


IMAGE = os.getenv("DY_API_IMAGE_SMOKE_IMAGE")
pytestmark = pytest.mark.skipif(
    not IMAGE, reason="Set DY_API_IMAGE_SMOKE_IMAGE to test a built API image"
)
RUNTIME_ARGS = [
    "--network", "none",
    "--env", "DY_DATABASE_URL=sqlite+pysqlite:///:memory:",
]


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )


def test_built_api_image_imports_application():
    result = _docker(
        "run", "--rm", *RUNTIME_ARGS, IMAGE, "python", "-c",
        "from dy_api.main import app; assert app.title == 'Douyin Laike Dashboard API'",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_built_api_image_default_command_serves_http():
    name = f"dydata-api-smoke-{uuid.uuid4().hex}"
    started = _docker("run", "--detach", "--name", name, *RUNTIME_ARGS, IMAGE)
    assert started.returncode == 0, started.stdout + started.stderr
    # Probe inside the network-isolated container: no published ports, secrets,
    # source mounts, migrations, or access to a production database are needed.
    probe = """
import json
from urllib.error import HTTPError
from urllib.request import urlopen

with urlopen('http://127.0.0.1:8000/.well-known/dydata-agent.json', timeout=2) as response:
    assert response.status == 200
    assert json.load(response)['environment'] == 'production'
try:
    urlopen('http://127.0.0.1:8000/api/v1/auth/me', timeout=2)
except HTTPError as error:
    assert error.code == 401, error.code
else:
    raise AssertionError('Unauthenticated API request must return 401')
"""
    try:
        deadline = time.monotonic() + 45
        last_probe = None
        while time.monotonic() < deadline:
            state = _docker("inspect", "--format", "{{.State.Running}}", name)
            if state.returncode != 0 or state.stdout.strip() != "true":
                break
            last_probe = _docker("exec", name, "python", "-c", probe)
            if last_probe.returncode == 0:
                return
            time.sleep(1)
        logs = _docker("logs", name)
        probe_error = "" if last_probe is None else last_probe.stdout + last_probe.stderr
        pytest.fail("API image failed startup smoke:\n" + logs.stdout + logs.stderr + probe_error)
    finally:
        removed = _docker("rm", "--force", name)
        assert removed.returncode == 0, removed.stdout + removed.stderr
