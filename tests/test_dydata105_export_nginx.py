"""Opt-in real Nginx -> real FastAPI -> synthetic database export regression.

Run with DY_TEST_NGINX=1 and a local Docker engine. Only a uniquely named,
disposable nginx container is created; no production service is contacted.
"""

from contextlib import contextmanager
import csv
from io import StringIO
import json
import os
from pathlib import Path
import socket
import subprocess
from threading import Thread
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn

from test_api_clues import client, _login_user, _seed_clue_center
from dy_api.auth import hash_password_pbkdf2
from apps.api.dy_api.models import DimStore, DimStoreOrgAssignment, User, UserStoreScope


pytestmark = pytest.mark.skipif(
    os.environ.get("DY_TEST_NGINX") != "1", reason="Set DY_TEST_NGINX=1 for disposable Docker Nginx regression"
)


@contextmanager
def _nginx_proxy(app, directory: Path):
    """Serve the test app behind a 4 KiB proxy header buffer."""
    listener = socket.socket()
    listener.bind(("0.0.0.0", 0))
    upstream_port = listener.getsockname()[1]
    with socket.socket() as proxy_socket:
        proxy_socket.bind(("127.0.0.1", 0))
        proxy_port = proxy_socket.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    name = f"dydata105-export-test-{uuid4().hex[:12]}"
    config = directory / "nginx.conf"
    config.write_text(
        "server { listen 80; location / { "
        f"proxy_pass http://host.docker.internal:{upstream_port}; "
        "proxy_buffer_size 4k; proxy_http_version 1.1; } }\n",
        encoding="utf-8",
    )
    started = False
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "Synthetic FastAPI server did not start"
        result = subprocess.run([
            "docker", "run", "--detach", "--rm", "--name", name,
            "--publish", f"127.0.0.1:{proxy_port}:80",
            "--add-host", "host.docker.internal:host-gateway",
            "--mount", f"type=bind,source={config},target=/etc/nginx/conf.d/default.conf,readonly",
            "nginx:1.27-alpine",
        ], capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stderr
        started = True
        base = f"http://127.0.0.1:{proxy_port}"
        with httpx.Client(trust_env=False, timeout=5) as probe:
            deadline = time.monotonic() + 15
            while True:
                try:
                    response = probe.get(base + "/api/v1/auth/me")
                    if response.status_code != 502:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "Disposable proxy failed to start"
                time.sleep(0.1)
        yield base
        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, timeout=10)
        assert "upstream sent too big header" not in logs.stderr, logs.stderr
    finally:
        if started:
            subprocess.run(["docker", "rm", "--force", name], capture_output=True, timeout=15)
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


@pytest.mark.parametrize("empty", [True, False])
@pytest.mark.parametrize("bulk", [False, True])
def test_large_scope_csv_survives_real_proxy_and_keeps_data_scope(client, db_session, tmp_path, empty, bulk):
    _seed_clue_center(db_session)
    extra_ids = [f"{number:020d}" for number in range(169)]
    db_session.add_all([DimStore(store_id=value, store_name=f"Synthetic {index}", is_active=True)
                        for index, value in enumerate(extra_ids)])
    db_session.flush()
    # This group overlaps all 170 authorized stores and an unauthorized store.
    # Both expanded scopes must remain server-side, and their intersection
    # must still exclude store-2's real clue row from the exported file.
    for index, store_id in enumerate(["store-1", "store-2", *extra_ids]):
        code = f"NGINX-SYNTHETIC-{index}"
        db_session.get(DimStore, store_id).service_store_code = code
        db_session.add(DimStoreOrgAssignment(service_store_code=code, group_name="Synthetic export group"))
    user = User(
        user_id="nginx-scope-user", username="nginx-scope-user", display_name="Synthetic scope",
        external_account_id="store-1", role="store", store_scope_mode="specified",
        status="active", is_initialized=True, password_hash=hash_password_pbkdf2("synthetic-password"),
    )
    db_session.add(user)
    db_session.flush()
    db_session.add_all([UserStoreScope(user_id=user.user_id, store_id=value)
                        for value in ["store-1", *extra_ids]])
    db_session.commit()
    _login_user(client, user.username, "synthetic-password")
    filters = {"assigned_date_start": "2099-01-01", "assigned_date_end": "2099-01-01"} if empty else {}
    organizations = client.get("/api/v1/clues/filter-options/organizations", params={"level": "group"})
    assert organizations.status_code == 200, organizations.text
    options = organizations.json()["data"]["options"]
    assert len(options) == 1
    filters.update({"org_level": "group", "org_key": options[0]["value"]})
    if bulk:
        filters["assigned_store_ids"] = ["store-1", *[f"selected-{number:020d}" for number in range(999)]]
    def export(http):
        if bulk:
            return http.post("/api/v1/clues/assignment-rounds/export", json={"filters": filters})
        return http.get("/api/v1/clues/assignment-rounds/export", params=filters)

    expected = export(client)
    assert expected.status_code == 200, expected.text
    with _nginx_proxy(client.app, tmp_path) as proxy:
        with httpx.Client(base_url=proxy, cookies=dict(client.cookies), trust_env=False, timeout=20) as browser:
            response = export(browser)
        assert response.status_code == 200, response.text
        assert response.content == expected.content
        assert response.content.startswith(b"\xef\xbb\xbf")
        assert len(response.headers["x-export-filters"].encode("ascii")) <= 1024
        assert "scope_store_ids" not in response.headers["x-export-filters"]
        assert "organization_store_ids" not in response.headers["x-export-filters"]
        if bulk:
            assert json.loads(response.headers["x-export-filters"])["assigned_store_ids"] == {"count": 1000}
        rows = list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))
        if empty:
            assert rows == []
        else:
            assert rows
            assert {row["assigned_store_id"] for row in rows} == {"store-1"}
