"""Run publication browser contracts against an isolated Vite with mocked APIs."""
from __future__ import annotations

import os
import signal
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen

import playwright


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"


def stop_process_tree(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def test_dashboard_publication_browser(tmp_path):
    package = Path(playwright.__file__).resolve().parent / "driver" / "package"
    bundled_node = package.parent / ("node.exe" if os.name == "nt" else "node")
    node = str(bundled_node) if bundled_node.is_file() else shutil.which("node")
    vite = WEB / "node_modules" / "vite" / "bin" / "vite.js"
    assert node, "Node.js is required for publication browser contracts"
    assert (package / "package.json").is_file(), "Python Playwright driver package is required"
    assert vite.is_file(), "Run npm ci in apps/web before publication browser contracts"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "VITE_USE_MOCKS": "false", "VITE_CLUE_DEMO_MODE": "false",
           "VITE_API_BASE_URL": "/api/v1", "PUBLICATION_TEST_BASE_URL": base_url,
           "PLAYWRIGHT_NODE_PACKAGE": str(package)}
    log_path = tmp_path / "publication-vite.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [node, str(vite), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
            cwd=WEB, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        try:
            deadline = time.monotonic() + 40
            while True:
                assert process.poll() is None, log_path.read_text(encoding="utf-8")
                try:
                    with urlopen(base_url, timeout=2) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    pass
                assert time.monotonic() < deadline, log_path.read_text(encoding="utf-8")
                time.sleep(0.2)
            runner = subprocess.Popen(
                [node, "--test", "--test-reporter=tap", str(WEB / "tests" / "dashboardPublications.browser.test.mjs")],
                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            try:
                output, _ = runner.communicate(timeout=360)
            except subprocess.TimeoutExpired:
                stop_process_tree(runner)
                output, _ = runner.communicate(timeout=10)
                raise AssertionError(f"Publication browser suite exceeded 360 seconds:\n{output}") from None
            finally:
                stop_process_tree(runner)
            (tmp_path / "publication-browser.tap").write_text(output, encoding="utf-8")
            assert runner.returncode == 0, output
            count = re.search(r"# tests (\d+)", output)
            assert count and int(count.group(1)) >= 10, output
            assert re.search(r"# fail 0(?:\r?\n|$)", output), output
            assert re.search(r"# skipped 0(?:\r?\n|$)", output), output
        finally:
            stop_process_tree(process)
