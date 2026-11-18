"""Interaction and transport boundaries for the dedicated human product console."""

from __future__ import annotations

import getpass
import json
import warnings
from copy import deepcopy
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
import pytest

from dydata_cli.human_client import HumanProductSession
from dydata_cli.human_products import main
from dydata_cli.registry import api_command_mappings, command_catalog, mcp_capability_catalog


_PASSWORD = "human-test-password-sentinel"
_COOKIE = "human-test-cookie-sentinel"
_POLICY = {
    "appointment_hours": 72, "further_follow_up_hours": 168, "unreachable_hours": 168,
    "pending_action": "next", "appointment_action": "next",
    "further_follow_up_action": "next", "unreachable_action": "close",
}


def _product(product_id: str) -> dict[str, Any]:
    return {
        "product_id": product_id, "product_name": f"商品 {product_id}", "product_scope": "byd",
        "routing_enabled": False, "rule_version_id": "rule-v1",
        "first_follow_up_sla_hours": 24, "follow_up_policy": dict(_POLICY),
        "store_ids": ["store-old"], "list_version": 1, "can_manage": True,
    }


class ProductApi:
    """A stateful fixed-path HTTP fake with the current Web login response shape."""

    def __init__(self, *, product_ids: tuple[str, ...] = ("product-a", "product-b")) -> None:
        self.products = {product_id: _product(product_id) for product_id in product_ids}
        self.requests: list[httpx.Request] = []
        self.batches: list[dict[str, Any]] = []
        self.grant_writes: list[tuple[str, list[str]]] = []
        self.shared_writes: list[dict[str, Any]] = []
        self.fail_once: set[str] = set()
        self.fail_preview: set[str] = set()
        self.can_manage_grants = True
        self.drop_publication_response = False
        self.grants: dict[str, list[str]] = {product_id: ["user-old"] for product_id in product_ids}
        self.shared = {
            "rule_version_id": "base-v1", "first_follow_up_sla_hours": 24,
            "follow_up_policy": dict(_POLICY), "can_manage": True,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v1/")
        assert request.url.host == "dy-business-engine.com"
        assert "authorization" not in request.headers
        assert "x-dydata-command" not in request.headers
        assert "x-dydata-cli-version" not in request.headers
        assert "auth/cli" not in path and not path.startswith("cli/")
        if path == "auth/login":
            assert json.loads(request.content) == {"username": "human.admin", "password": _PASSWORD}
            return httpx.Response(200, headers={"Set-Cookie": f"dy_session={_COOKIE}; Path=/; Secure; HttpOnly"}, json={
                "data": {
                    "user_id": "user-actor", "username": "human.admin", "display_name": "Human Admin",
                    "role": "admin", "status": "active", "is_initialized": True,
                    "store_ids": [], "store_scope_mode": "all", "page_keys": ["D05"],
                    "is_highest_admin": True, "can_manage_accounts": True, "can_manage_global_settings": True,
                    "unexpected_server_secret": "do-not-echo-sentinel",
                }, "meta": {"source": "session", "generated_at": "2026-11-18T06:00:00Z"},
            })
        assert request.headers.get("cookie") == f"dy_session={_COOKIE}"
        if path == "auth/logout":
            return httpx.Response(200, headers={"Set-Cookie": "dy_session=; Max-Age=0; Path=/"}, json={"data": {}})
        if path == "admin/clue-routing/products":
            assert request.method == "GET"
            page, page_size = int(request.url.params["page"]), int(request.url.params["page_size"])
            rows = list(self.products.values())[(page - 1) * page_size:page * page_size]
            return httpx.Response(200, json={"data": {
                "rows": rows, "total": len(self.products), "page": page,
                "page_size": page_size, "can_manage_grants": self.can_manage_grants,
            }})
        if path == "admin/clue-routing/products/batch":
            body = json.loads(request.content)
            self.batches.append(body)
            assert request.method == "POST" and request.headers["idempotency-key"]
            product_ids = list(self.products) if body["all_matching"] else body["product_ids"]
            results = []
            for product_id in product_ids:
                before = deepcopy(self.products[product_id])
                after = deepcopy(before)
                if body["action"] == "enable" and not body["preview"]:
                    expected = body.get("expected_list_versions", {}).get(product_id)
                    if expected != before["list_version"]:
                        results.append({
                            "product_id": product_id, "status": "failed", "before": {}, "after": {},
                            "error": {"code": "LIST_VERSION_CHANGED" if expected is not None else "PREVIEW_REQUIRED"},
                        })
                        continue
                if product_id in self.fail_preview or (not body["preview"] and product_id in self.fail_once):
                    self.fail_once.discard(product_id)
                    results.append({
                        "product_id": product_id, "status": "failed", "before": {}, "after": {},
                        "error": {"code": "CONFLICT", "message": "unsafe-server-message-sentinel"},
                    })
                    continue
                if body["action"] == "publish_list":
                    lists = {row["product_id"]: row["store_ids"] for row in body.get("lists", [])}
                    after["store_ids"] = body.get("store_ids", lists.get(product_id))
                    if not body["preview"]:
                        after["list_version"] += 1
                elif body["action"] == "publish_rule":
                    for field, value in body["rules"].items():
                        if field == "first_follow_up_sla_hours":
                            after[field] = value
                        else:
                            after["follow_up_policy"][field] = value
                    if not body["preview"]:
                        after["rule_version_id"] = "rule-v2"
                else:
                    after["routing_enabled"] = body["action"] == "enable"
                if not body["preview"]:
                    self.products[product_id] = after
                results.append({
                    "product_id": product_id, "status": "preview" if body["preview"] else "success",
                    "before": before, "after": after,
                })
            if not body["preview"] and self.drop_publication_response:
                raise httpx.ReadError("unsafe transport error sentinel " + _COOKIE, request=request)
            return httpx.Response(200, json={"data": {"results": results}})
        if path.endswith("/grants"):
            product_id = path.split("/")[-2]
            if request.method == "PUT":
                user_ids = json.loads(request.content)["user_ids"]
                self.grants[product_id] = user_ids
                self.grant_writes.append((product_id, user_ids))
            return httpx.Response(200, json={"data": {
                "product_id": product_id, "user_ids": self.grants[product_id],
                "users": [{"user_id": user_id, "username": user_id, "display_name": user_id}
                          for user_id in ("user-old", "user-new")],
            }})
        if path == "admin/clue-routing/shared-rule":
            body = json.loads(request.content)
            self.shared_writes.append(body)
            before, after = deepcopy(self.shared), deepcopy(self.shared)
            for field, value in body["rules"].items():
                if field == "first_follow_up_sla_hours":
                    after[field] = value
                else:
                    after["follow_up_policy"][field] = value
            if not body["preview"]:
                after["rule_version_id"] = "base-v2"
                self.shared = after
            return httpx.Response(200, json={"data": {
                "before": before, "after": after, "status": "preview" if body["preview"] else "success",
            }})
        raise AssertionError("unexpected operation")


def _run(
    api: ProductApi, answers: list[str], *, argv: list[str] | None = None,
    password_input=None, is_interactive: bool = True, before_answer=None,
) -> tuple[int, str, dict[str, Any]]:
    output = StringIO()
    remaining = iter(answers)
    sessions = []

    def session_factory() -> HumanProductSession:
        session = HumanProductSession(transport=httpx.MockTransport(api))
        sessions.append(session)
        return session

    def ask(prompt: str) -> str:
        if before_answer is not None:
            before_answer(prompt)
        return next(remaining)

    exit_code = main(
        argv or ["manage"], session_factory=session_factory,
        text_input=ask, password_input=password_input or (lambda _: _PASSWORD),
        is_interactive_terminal=lambda: is_interactive, stream=output,
    )
    assert all(session._http.is_closed and not session._http.cookies for session in sessions)
    text = output.getvalue()
    assert _PASSWORD not in text and _COOKIE not in text
    assert "do-not-echo-sentinel" not in text and "unsafe-server-message-sentinel" not in text
    audit = json.loads(text.splitlines()[-1])["audit"]
    return exit_code, text, audit


def _input_file(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "change.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_all_filtered_freezes_preview_ids_and_retries_only_failed_items(tmp_path: Path) -> None:
    api = ProductApi()
    api.fail_once.add("product-b")
    receipt = tmp_path / "receipt.json"
    code, output, audit = _run(api, ["human.admin", "all", "1", "store-new", "PUBLISH 2", "y", "PUBLISH 1"], argv=[
        "manage", "--q", "商品", "--product-scope", "byd", "--audit", str(receipt),
    ])

    assert code == 0 and audit["status"] == "complete" and audit["failed_product_ids"] == []
    assert [batch["preview"] for batch in api.batches] == [True, False, True, False]
    assert api.batches[0]["all_matching"] is True
    assert api.batches[0]["filters"] == {"q": "商品", "product_scope": "byd"}
    assert api.batches[1]["product_ids"] == ["product-a", "product-b"]
    assert all(batch["all_matching"] is False for batch in api.batches[1:])
    assert [batch["product_ids"] for batch in api.batches[2:]] == [["product-b"], ["product-b"]]
    assert all(row["store_ids"] == ["store-new"] and not row["routing_enabled"] for row in api.products.values())
    assert all(row["list_version"] == 2 for row in api.products.values())
    assert "逐商品预览" in output and "逐商品发布结果" in output
    assert json.loads(receipt.read_text(encoding="utf-8")) == audit
    assert [request.url.path for request in api.requests].count("/api/v1/auth/logout") == 1
    write_keys = [request.headers["idempotency-key"] for request in api.requests
                  if request.url.path.endswith("/batch") and not json.loads(request.content)["preview"]]
    assert len(set(write_keys)) == 2


def test_multiselect_accumulates_across_pages_and_patches_only_named_fields(tmp_path: Path) -> None:
    api = ProductApi()
    path = _input_file(tmp_path, {"rules": {"appointment_hours": 96}})
    code, _, audit = _run(api, ["human.admin", "product-a", "n", "product-b", "done", "2", "PUBLISH 2"], argv=[
        "manage", "--page-size", "1", "--input", str(path),
    ])

    assert code == 0 and audit["status"] == "complete"
    assert api.batches[1]["product_ids"] == ["product-a", "product-b"]
    assert api.batches[1]["rules"] == {"appointment_hours": 96}
    assert all(row["follow_up_policy"] == {**_POLICY, "appointment_hours": 96} for row in api.products.values())
    assert all(row["first_follow_up_sla_hours"] == 24 and not row["routing_enabled"] for row in api.products.values())


def test_cancel_after_preview_never_publishes() -> None:
    api = ProductApi()
    code, _, audit = _run(api, ["human.admin", "all", "1", "store-new", "yes"])

    assert code == 0 and audit["status"] == "cancelled"
    assert len(api.batches) == 1 and api.batches[0]["preview"] is True
    assert all(row["list_version"] == 1 for row in api.products.values())


def test_partial_failure_retains_old_item_and_returns_failure_exit() -> None:
    api = ProductApi()
    api.fail_once.add("product-b")
    code, _, audit = _run(api, ["human.admin", "all", "1", "store-new", "PUBLISH 2", "n"])

    assert code == 1 and audit["status"] == "partial" and audit["failed_product_ids"] == ["product-b"]
    assert api.products["product-a"]["list_version"] == 2
    assert api.products["product-b"]["list_version"] == 1


def test_cancelling_a_retry_preserves_prior_partial_result_and_failure_exit() -> None:
    api = ProductApi()
    api.fail_once.add("product-b")
    code, _, audit = _run(api, ["human.admin", "all", "1", "store-new", "PUBLISH 2", "y", "cancel"])

    assert code == 1 and audit["status"] == "partial"
    assert audit["failed_product_ids"] == ["product-b"]
    assert len(api.batches) == 3 and len(audit["attempts"]) == 1
    assert api.products["product-a"]["list_version"] == 2
    assert api.products["product-b"]["list_version"] == 1


@pytest.mark.parametrize("note", ["", "业务负责人已确认名单并于会议明确授权"])
def test_enable_requires_separate_business_authorization_and_exact_confirmation(note: str) -> None:
    api = ProductApi()
    answers = ["human.admin", "all", "3", note] + (["PUBLISH 2"] if note else [])
    code, _, audit = _run(api, answers)

    if not note:
        assert code == 2 and api.batches == []
        assert not any(row["routing_enabled"] for row in api.products.values())
    else:
        assert code == 0 and audit["status"] == "complete"
        assert api.batches[-1]["authorization_note"] == note
        assert api.batches[-1]["expected_list_versions"] == {"product-a": 1, "product-b": 1}
        assert all(row["routing_enabled"] for row in api.products.values())


def test_enable_list_change_requires_new_preview_version_and_human_confirmation() -> None:
    api = ProductApi()
    changed = False

    def replace_list(prompt: str) -> None:
        nonlocal changed
        if "PUBLISH 2" in prompt and not changed:
            api.products["product-b"]["list_version"] = 2
            api.products["product-b"]["store_ids"] = ["store-changed"]
            changed = True
        if prompt.startswith("仅重试失败商品"):
            assert not api.products["product-b"]["routing_enabled"]

    code, output, audit = _run(api, [
        "human.admin", "all", "3", "业务负责人确认并授权", "PUBLISH 2", "y", "PUBLISH 1",
    ], before_answer=replace_list)

    assert code == 0 and audit["status"] == "complete"
    assert "LIST_VERSION_CHANGED" in output
    assert [batch["preview"] for batch in api.batches] == [True, False, True, False]
    assert api.batches[1]["expected_list_versions"] == {"product-a": 1, "product-b": 1}
    assert api.batches[3]["expected_list_versions"] == {"product-b": 2}
    assert api.batches[3]["product_ids"] == ["product-b"]
    assert all(row["routing_enabled"] for row in api.products.values())


def test_network_loss_after_publication_is_unknown_and_is_not_retried() -> None:
    api = ProductApi()
    api.drop_publication_response = True
    code, output, audit = _run(api, ["human.admin", "all", "1", "store-new", "PUBLISH 2"])

    assert code == 5 and audit["status"] == "unknown"
    assert len(api.batches) == 2
    assert audit["attempts"][0]["status"] == "unknown"
    assert audit["attempts"][0]["idempotency_key"]
    assert audit["attempts"][0]["request_id"].startswith("req_")
    assert "unsafe transport error sentinel" not in output
    assert all(row["list_version"] == 2 for row in api.products.values())


def test_product_specific_input_and_grants_use_previewed_exact_targets(tmp_path: Path) -> None:
    api = ProductApi()
    path = _input_file(tmp_path, {"lists": [
        {"product_id": "product-a", "store_ids": ["store-a"]},
        {"product_id": "product-b", "store_ids": ["store-b"]},
    ]})
    code, _, _ = _run(api, ["human.admin", "all", "1", "PUBLISH 2"], argv=["manage", "--input", str(path)])

    assert code == 0
    assert api.products["product-a"]["store_ids"] == ["store-a"]
    assert api.products["product-b"]["store_ids"] == ["store-b"]
    path.write_text(json.dumps({"user_ids": ["user-new"]}), encoding="utf-8")
    code, _, audit = _run(api, ["human.admin", "all", "5", "AUTHORIZE 2"], argv=["manage", "--input", str(path)])
    assert code == 0 and audit["status"] == "complete"
    assert api.grant_writes == [("product-a", ["user-new"]), ("product-b", ["user-new"])]


def test_grant_cancel_and_non_admin_cannot_issue_grant_write(tmp_path: Path) -> None:
    api = ProductApi()
    path = _input_file(tmp_path, {"user_ids": []})
    code, _, audit = _run(api, ["human.admin", "all", "5", "no"], argv=["manage", "--input", str(path)])
    assert code == 0 and audit["status"] == "cancelled" and not api.grant_writes
    api.can_manage_grants = False
    code, _, _ = _run(api, ["human.admin", "all", "5"])
    assert code == 0 and not api.grant_writes


def test_shared_rule_requires_own_confirmation_and_does_not_enable_products(tmp_path: Path) -> None:
    api = ProductApi()
    path = _input_file(tmp_path, {"rules": {"first_follow_up_sla_hours": 48}})
    code, _, audit = _run(api, ["human.admin", "PUBLISH SHARED"], argv=["shared-rule", "--input", str(path)])

    assert code == 0 and audit["status"] == "complete"
    assert [body["preview"] for body in api.shared_writes] == [True, False]
    assert api.shared["first_follow_up_sla_hours"] == 48 and api.shared["rule_version_id"] == "base-v2"
    assert not api.batches and not any(row["routing_enabled"] for row in api.products.values())


def test_shared_base_cancel_and_input_target_mismatch_do_not_publish(tmp_path: Path) -> None:
    api = ProductApi()
    path = _input_file(tmp_path, {"rules": {"appointment_hours": 96}})
    code, _, audit = _run(api, ["human.admin", "no"], argv=["shared-rule", "--input", str(path)])
    assert code == 0 and audit["status"] == "cancelled"
    assert len(api.shared_writes) == 1 and api.shared_writes[0]["preview"] is True
    assert api.shared["rule_version_id"] == "base-v1"
    path.write_text(json.dumps({"lists": [{"product_id": "product-b", "store_ids": ["store-new"]}]}), encoding="utf-8")
    code, _, _ = _run(api, ["human.admin", "product-a", "done", "1"], argv=["manage", "--input", str(path)])
    assert code == 2 and not api.batches


@pytest.mark.parametrize("argv", [
    ["manage", "--password", "private-value-sentinel"],
    ["manage", "--token", "private-value-sentinel"],
    ["manage", "--cookie", "private-value-sentinel"],
    ["manage", "--url", "https://private-value-sentinel.test"],
    ["manage", "--yes"],
])
def test_secret_url_and_unattended_arguments_are_rejected_before_network(argv: list[str]) -> None:
    api = ProductApi()
    code, output, _ = _run(api, [], argv=argv)
    assert code == 2 and api.requests == [] and "private-value-sentinel" not in output


def test_non_tty_fails_before_constructing_client_or_collecting_password() -> None:
    output = StringIO()

    def forbidden(*args, **kwargs):
        raise AssertionError("non-interactive command reached a sensitive dependency")

    assert main(["manage"], session_factory=forbidden, text_input=forbidden,
                password_input=forbidden, is_interactive_terminal=lambda: False, stream=output) == 2
    assert "交互终端" in output.getvalue()


def test_hidden_password_warning_stops_before_login() -> None:
    api = ProductApi()

    def warning_password(prompt: str) -> str:
        warnings.warn("password echo unavailable", getpass.GetPassWarning)
        return _PASSWORD

    code, _, _ = _run(api, ["human.admin"], password_input=warning_password)
    assert code == 2 and not api.requests


def test_existing_audit_is_preserved_before_login(tmp_path: Path) -> None:
    api = ProductApi()
    path = tmp_path / "receipt.json"
    path.write_text("existing artifact", encoding="utf-8")
    code, _, _ = _run(api, [], argv=["manage", "--audit", str(path)])
    assert code == 2 and not api.requests
    assert path.read_text(encoding="utf-8") == "existing artifact"


def test_new_console_does_not_extend_the_readonly_agent_or_mcp_maps() -> None:
    assert not any("products" in row["command"] or "shared-rule" in row["command"] for row in command_catalog())
    assert not any("clue-routing" in path for path in api_command_mappings()[0])
    assert all(row["read_only"] is True for row in mcp_capability_catalog())


@pytest.mark.parametrize("rules", [
    {}, {"first_follow_up_sla_hours": 0}, {"first_follow_up_sla_hours": True},
    {"appointment_hours": 8761}, {"pending_action": "arbitrary"},
    {"pending_action": ["next"]}, {"unexpected": "unsafe-value-sentinel"},
])
def test_invalid_patch_cannot_reach_preview_or_leak_input(tmp_path: Path, rules: dict[str, Any]) -> None:
    api = ProductApi()
    path = _input_file(tmp_path, {"rules": rules})
    code, output, _ = _run(api, ["human.admin", "all", "2"], argv=["manage", "--input", str(path)])
    assert code == 2 and not api.batches and "unsafe-value-sentinel" not in output
