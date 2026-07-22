from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mcp_authorize_page_is_routed_and_preserved_after_login() -> None:
    app_source = (ROOT / "apps/web/src/App.tsx").read_text(encoding="utf-8")

    assert 'import { McpAuthorizePage } from "./pages/McpAuthorizePage"' in app_source
    assert 'location.pathname === "/auth/mcp/authorize"' in app_source
    assert 'pathname !== "/auth/mcp/authorize"' in app_source
    assert "<McpAuthorizePage" in app_source


def test_mcp_authorize_page_discloses_scope_without_collecting_credentials() -> None:
    page_source = (ROOT / "apps/web/src/pages/McpAuthorizePage.tsx").read_text(
        encoding="utf-8"
    )

    for required_copy in (
        "Agent 名称",
        "回调地址",
        "授权范围",
        "测试环境",
        "可读取门店",
        "允许只读访问",
        "拒绝",
    ):
        assert required_copy in page_source
    assert "fetchMcpAuthorizationRequest" in page_source
    assert "decideMcpAuthorization" in page_source
    assert "window.location.assign" in page_source
    assert "password" not in page_source.lower()


def test_web_client_uses_authenticated_mcp_consent_endpoints() -> None:
    client_source = (ROOT / "apps/web/src/api/client.ts").read_text(encoding="utf-8")

    assert '"/auth/mcp/request"' in client_source
    assert '"/auth/mcp/approve"' in client_source
    assert "fetchMcpAuthorizationRequest" in client_source
    assert "decideMcpAuthorization" in client_source
