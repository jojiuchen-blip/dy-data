"""Real application/auth/database roundtrip after the product backend is integrated."""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path

import httpx
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from apps.api.dy_api.models import ClueProductRoutingConfig, DimSkuProductRule, DimStore, User
from apps.api.dy_api.clue_product_routing import load_product_store_ids
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
    client = TestClient(app)
    observed = []
    batches = []

    def bridge(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "dy-business-engine.com"
        assert "authorization" not in request.headers
        assert not request.url.path.startswith("/api/v1/auth/cli")
        if not request.url.path.endswith("/auth/login"):
            assert request.headers.get("cookie")
        observed.append((request.method, request.url.path))
        if request.url.path.endswith("/products/batch"):
            batches.append(json.loads(request.content))
        response = client.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
        return httpx.Response(response.status_code, headers=response.headers, content=response.content, request=request)

    change = tmp_path / "change.json"

    def run(answers: list[str], payload=None, command: str = "manage", before_answer=None, expected_exit: int = 0):
        remaining = iter(["human.roundtrip", *answers])
        output = StringIO()
        argv = [command]
        if payload is not None:
            change.write_text(json.dumps(payload), encoding="utf-8")
            argv.extend(["--input", str(change)])

        def ask(prompt: str) -> str:
            if before_answer is not None:
                before_answer(prompt)
            return next(remaining)

        code = main(
            argv, session_factory=lambda: HumanProductSession(transport=httpx.MockTransport(bridge)),
            text_input=ask, password_input=lambda _: "synthetic-roundtrip-password",
            is_interactive_terminal=lambda: True, stream=output,
        )
        assert "synthetic-roundtrip-password" not in output.getvalue()
        assert "dy_session=" not in output.getvalue()
        assert code == expected_exit, output.getvalue()
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
    blocked_rule = run(["p-byd", "done", "2", "n"], {"rules": {"first_follow_up_sla_hours": 48}}, expected_exit=1)
    assert blocked_rule["attempts"] == []
    assert blocked_rule["previews"][0]["results"][0]["error"]["code"] == "PRODUCT_NOT_ENABLED"
    run(["all", "3", "合成业务授权：名单已确认，同意本次测试开启", "PUBLISH 2"])
    db_session.expire_all()
    assert db_session.get(ClueProductRoutingConfig, "p-jc").routing_enabled
    assert db_session.get(ClueProductRoutingConfig, "p-byd").routing_enabled
    run(["all", "2", "PUBLISH 2"], {"rules": {"first_follow_up_sla_hours": 48}})
    run(["p-jc", "done", "4", "PUBLISH 1"])
    db_session.expire_all()
    assert not db_session.get(ClueProductRoutingConfig, "p-jc").routing_enabled
    assert db_session.get(ClueProductRoutingConfig, "p-byd").routing_enabled
    grants = run(["all", "5", "AUTHORIZE 2"], {"user_ids": ["roundtrip-manager"]})
    assert all(attempt["after"] == ["roundtrip-manager"] for attempt in grants["attempts"])
    shared = run(["PUBLISH SHARED"], {"rules": {"appointment_hours": 96}}, command="shared-rule")
    assert shared["attempts"][0]["after"]["follow_up_policy"]["appointment_hours"] == 96

    # Simulate a real store-catalog change between human preview and publication.
    # One product must retain its prior list while its peer succeeds; the human
    # then corrects the catalog and explicitly retries only that failed product.
    db_session.add(DimStore(store_id="002", store_name="Restorable Synthetic Store"))
    db_session.commit()
    unchanged_jc_version = db_session.get(ClueProductRoutingConfig, "p-jc").active_list_version_id

    def change_catalog(prompt: str) -> None:
        if "PUBLISH 2" in prompt:
            db_session.delete(db_session.get(DimStore, "002"))
            db_session.commit()
        elif prompt.startswith("仅重试失败商品"):
            assert load_product_store_ids(db_session, "p-byd") == {"001"}
            db_session.add(DimStore(store_id="002", store_name="Restored Synthetic Store"))
            db_session.commit()

    partial_retry = run(["all", "1", "PUBLISH 2", "y", "PUBLISH 1"], {"lists": [
        {"product_id": "p-jc", "store_ids": ["001"]},
        {"product_id": "p-byd", "store_ids": ["002"]},
    ]}, before_answer=change_catalog)
    assert partial_retry["status"] == "complete" and partial_retry["failed_product_ids"] == []
    assert len(partial_retry["attempts"]) == 2
    first_result = {row["product_id"]: row for row in partial_retry["attempts"][0]["results"]}
    assert first_result["p-jc"]["status"] == "success"
    assert first_result["p-byd"]["error"]["code"] == "UNKNOWN_STORE_IDS"
    assert partial_retry["attempts"][1]["product_ids"] == ["p-byd"]
    assert batches[-1]["lists"] == [{"product_id": "p-byd", "store_ids": ["002"]}]
    db_session.expire_all()
    assert db_session.get(ClueProductRoutingConfig, "p-jc").active_list_version_id == unchanged_jc_version
    assert load_product_store_ids(db_session, "p-jc") == {"001"}
    assert load_product_store_ids(db_session, "p-byd") == {"002"}

    run(["all", "4", "PUBLISH 2"])
    assert "expected_list_versions" not in batches[-1]
    previous_byd_version = db_session.get(ClueProductRoutingConfig, "p-byd").active_list_version_id
    changed_list_version = []

    def replace_published_list(prompt: str) -> None:
        if "PUBLISH 2" in prompt and not changed_list_version:
            replacement = client.post("https://dy-business-engine.com/api/v1/admin/clue-routing/products/batch", json={
                "product_ids": ["p-byd"], "action": "publish_list", "store_ids": ["001"], "preview": False,
            })
            assert replacement.status_code == 200
            result = replacement.json()["data"]["results"][0]
            assert result["status"] == "success"
            changed_list_version.append(result["after"]["list_version"])
        elif prompt.startswith("仅重试失败商品"):
            db_session.expire_all()
            assert not db_session.get(ClueProductRoutingConfig, "p-byd").routing_enabled
            assert db_session.get(ClueProductRoutingConfig, "p-jc").routing_enabled

    enable_retry = run([
        "all", "3", "合成业务负责人确认当前有效名单并授权开启", "PUBLISH 2", "y", "PUBLISH 1",
    ], before_answer=replace_published_list)
    assert enable_retry["status"] == "complete" and len(enable_retry["attempts"]) == 2
    first_enable = {row["product_id"]: row for row in enable_retry["attempts"][0]["results"]}
    assert first_enable["p-byd"]["error"]["code"] == "LIST_VERSION_CHANGED"
    assert first_enable["p-jc"]["status"] == "success"
    assert batches[-3]["expected_list_versions"]["p-byd"] == previous_byd_version
    assert batches[-1]["expected_list_versions"] == {"p-byd": changed_list_version[0]}
    assert batches[-1]["product_ids"] == ["p-byd"]
    assert changed_list_version[0] != previous_byd_version
    db_session.expire_all()
    assert db_session.get(ClueProductRoutingConfig, "p-jc").routing_enabled
    assert db_session.get(ClueProductRoutingConfig, "p-byd").routing_enabled
    assert observed.count(("POST", "/api/v1/auth/login")) == 11
    assert observed.count(("POST", "/api/v1/auth/logout")) == 11
