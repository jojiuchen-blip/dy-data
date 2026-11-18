"""Real application/auth/database roundtrip after the product backend is integrated."""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
pytest.importorskip("apps.api.dy_api.clue_product_routing", reason="product backend is not integrated into this isolated CLI worktree yet")

from apps.api.dy_api.models import ClueProductRoutingConfig, DimSkuProductRule, DimStore, User
from dy_api.main import create_app
from dy_api.routes._data import get_session_dependency
from dydata_cli.human_client import HumanProductSession
from dydata_cli.human_products import main


def test_human_console_real_login_preview_publish_readback_and_grants(db_session, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "human.roundtrip")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "synthetic-roundtrip-password")
    monkeypatch.delenv("DY_SUPER_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("DY_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "true")
    monkeypatch.setenv("DYDATA_ENV", "production")
    db_session.add_all([
        DimSkuProductRule(sku_id="sku-jc", product_id="p-jc", product_name="精诚套餐", product_scope="精诚养车"),
        DimSkuProductRule(sku_id="sku-byd", product_id="p-byd", product_name="本品套餐", product_scope="本品"),
        DimStore(store_id="001", store_name="Synthetic Store"),
        User(user_id="roundtrip-manager", username="roundtrip-manager", display_name="Synthetic Manager",
             role="store", status="active", is_initialized=True),
    ])
    db_session.commit()
    app = create_app()
    app.dependency_overrides[get_session_dependency] = lambda: db_session
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/v1/admin/clue-routing/products/batch" in paths
    client = TestClient(app)
    observed = []

    def bridge(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "dy-business-engine.com"
        assert "authorization" not in request.headers
        assert not request.url.path.startswith("/api/v1/auth/cli")
        if not request.url.path.endswith("/auth/login"):
            assert request.headers.get("cookie")
        observed.append((request.method, request.url.path))
        response = client.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
        return httpx.Response(response.status_code, headers=response.headers, content=response.content, request=request)

    change = tmp_path / "change.json"

    def run(answers: list[str], payload=None, command: str = "manage"):
        remaining = iter(["human.roundtrip", *answers])
        output = StringIO()
        argv = [command]
        if payload is not None:
            change.write_text(json.dumps(payload), encoding="utf-8")
            argv.extend(["--input", str(change)])
        code = main(
            argv, session_factory=lambda: HumanProductSession(transport=httpx.MockTransport(bridge)),
            text_input=lambda _: next(remaining), password_input=lambda _: "synthetic-roundtrip-password",
            is_interactive_terminal=lambda: True, stream=output,
        )
        assert "synthetic-roundtrip-password" not in output.getvalue()
        assert "dy_session=" not in output.getvalue()
        assert code == 0, output.getvalue()
        return json.loads(output.getvalue().splitlines()[-1])["audit"]

    cancelled = run(["all", "1", "cancel"], {"store_ids": ["001"]})
    assert cancelled["status"] == "cancelled"
    assert db_session.get(ClueProductRoutingConfig, "p-jc") is None
    receipt = run(["all", "1", "PUBLISH 2"], {"store_ids": ["001"]})
    assert receipt["status"] == "complete"
    assert receipt["attempts"][0]["server_request_id"]
    db_session.expire_all()
    assert not db_session.get(ClueProductRoutingConfig, "p-jc").routing_enabled
    assert not db_session.get(ClueProductRoutingConfig, "p-byd").routing_enabled
    run(["all", "2", "PUBLISH 2"], {"rules": {"first_follow_up_sla_hours": 48}})
    run(["all", "3", "合成业务授权：名单已确认，同意本次测试开启", "PUBLISH 2"])
    db_session.expire_all()
    assert db_session.get(ClueProductRoutingConfig, "p-jc").routing_enabled
    assert db_session.get(ClueProductRoutingConfig, "p-byd").routing_enabled
    run(["p-jc", "done", "4", "PUBLISH 1"])
    db_session.expire_all()
    assert not db_session.get(ClueProductRoutingConfig, "p-jc").routing_enabled
    assert db_session.get(ClueProductRoutingConfig, "p-byd").routing_enabled
    grants = run(["all", "5", "AUTHORIZE 2"], {"user_ids": ["roundtrip-manager"]})
    assert all(attempt["after"] == ["roundtrip-manager"] for attempt in grants["attempts"])
    shared = run(["PUBLISH SHARED"], {"rules": {"appointment_hours": 96}}, command="shared-rule")
    assert shared["attempts"][0]["after"]["follow_up_policy"]["appointment_hours"] == 96
    assert observed.count(("POST", "/api/v1/auth/login")) == 7
    assert observed.count(("POST", "/api/v1/auth/logout")) == 7
