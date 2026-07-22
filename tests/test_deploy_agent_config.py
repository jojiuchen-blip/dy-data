from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))
PUBLIC_AGENT_ROOT_PATHS = (
    "/mcp",
    "/authorize",
    "/register",
    "/token",
    "/revoke",
    "/agent.md",
    "/agent/SKILL.md",
)


def test_api_image_contains_shared_cli_registry_and_fixed_test_environment() -> None:
    dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "deploy/compose.yaml").read_text(encoding="utf-8")
    env_example = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")

    assert "COPY apps/cli ./apps/cli" in dockerfile
    assert "/app/apps/cli/src" in dockerfile
    assert "ENV DY_AGENT_ENVIRONMENT=test" in dockerfile
    assert "DY_AGENT_ENVIRONMENT: test" in compose
    assert "DY_AGENT_ENVIRONMENT=test" in env_example
    assert "DY_WEB_BASE_URL=https://dy-business-engine.com" in env_example


def test_compose_proxy_and_railway_web_proxy_route_all_agent_root_endpoints() -> None:
    compose_nginx = (ROOT / "deploy/nginx.conf").read_text(encoding="utf-8")
    railway_web = (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")

    for source in (compose_nginx, railway_web):
        assert "location ^~ /.well-known/" in source
        assert "agent\\.md" in source
        assert "agent/SKILL\\.md" in source
        for path in PUBLIC_AGENT_ROOT_PATHS[:5]:
            assert path.removeprefix("/") in source
        assert "proxy_pass" in source
        assert "proxy_buffering off;" in source
        assert "proxy_set_header Host $host;" in source


def test_deploy_smoke_checks_discovery_oauth_and_protected_mcp() -> None:
    deploy_script = (ROOT / "deploy/tencent/deploy.sh").read_text(encoding="utf-8")
    railway_workflow = (ROOT / ".github/workflows/ci-cd.yml").read_text(
        encoding="utf-8"
    )

    for source in (deploy_script, railway_workflow):
        assert "/.well-known/dydata-agent.json" in source
        assert "/.well-known/oauth-authorization-server" in source
        assert "/.well-known/oauth-protected-resource/mcp" in source
        assert '"environment":"test"' in source
        assert "mcp_status" in source
        assert (
            '"$mcp_status" = "401"' in source
            or '"$mcp_status" != "401"' in source
        )


def test_explicit_agent_environment_rejects_unknown_or_mismatched_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dy_api.main import create_app

    monkeypatch.setenv("DY_AGENT_ENVIRONMENT", "production")
    monkeypatch.setenv("DY_WEB_BASE_URL", "https://production.example")
    with pytest.raises(RuntimeError, match="test"):
        create_app()

    monkeypatch.setenv("DY_AGENT_ENVIRONMENT", "test")
    monkeypatch.setenv("DY_WEB_BASE_URL", "https://wrong.example")
    with pytest.raises(RuntimeError, match="DY_WEB_BASE_URL"):
        create_app()

    monkeypatch.setenv("DY_WEB_BASE_URL", "https://dy-business-engine.com/")
    assert create_app().state.mcp_oauth_provider is not None
