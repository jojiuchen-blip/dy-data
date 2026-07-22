from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from dy_api.main import create_app  # noqa: E402


def test_agent_manifest_is_a_stable_test_environment_entrypoint() -> None:
    client = TestClient(create_app())

    response = client.get("/.well-known/dydata-agent.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    manifest = response.json()
    assert manifest == {
        "name": "dydata-agent",
        "manifest_version": "1.0",
        "environment": "test",
        "read_only": True,
        "service": {
            "base_url": "https://dy-business-engine.com",
            "capabilities_url": "https://dy-business-engine.com/api/v1/agent/capabilities",
            "agent_guide_url": "https://dy-business-engine.com/agent.md",
            "skill_url": "https://dy-business-engine.com/agent/SKILL.md",
        },
        "cli": {
            "version": "0.3.0",
            "schema_version": "1.1",
            "install_spec": "git+https://github.com/jojiuchen-blip/dy-data.git@main#subdirectory=apps/cli",
            "discovery_command": "dydata commands --json",
            "doctor_command": "dydata agent doctor --json",
        },
        "mcp": {
            "url": "https://dy-business-engine.com/mcp",
            "transport": "streamable-http",
            "oauth_issuer": "https://dy-business-engine.com",
            "protected_resource_metadata": "https://dy-business-engine.com/.well-known/oauth-protected-resource/mcp",
        },
        "authorization": {
            "user_handoff_required": True,
            "agent_must_not_handle_credentials": True,
            "scope": "mcp:read",
        },
    }
    assert "production" not in response.text.lower()


def test_agent_capabilities_are_derived_from_the_read_only_registry() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/agent/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "test"
    assert body["read_only"] is True
    assert body["schema_version"] == "1.0"
    assert body["capabilities"] == [
        {
            "command": "clues.follow-up-stats",
            "mcp_tool": "clues_follow_up_stats",
            "purpose": "Summarize clue follow-up results for authorized stores.",
            "data_scope": "authorized_stores",
            "business_side_effect": "none",
        },
        {
            "command": "stores.list",
            "mcp_tool": "stores_list",
            "purpose": "List stores available within the caller's data scope.",
            "data_scope": "authorized_stores",
            "business_side_effect": "none",
        },
    ]


def test_agent_markdown_and_skill_point_back_to_machine_contracts() -> None:
    client = TestClient(create_app())

    guide = client.get("/agent.md")
    skill = client.get("/agent/SKILL.md")

    assert guide.status_code == 200
    assert skill.status_code == 200
    assert guide.headers["content-type"].startswith("text/markdown")
    assert skill.headers["content-type"].startswith("text/markdown")
    for text in (guide.text, skill.text):
        assert "https://dy-business-engine.com/.well-known/dydata-agent.json" in text
        assert "https://dy-business-engine.com/api/v1/agent/capabilities" in text
        assert "https://dy-business-engine.com/mcp" in text
        assert "dydata agent doctor --json" in text
        assert "不得索取、读取、转发或保存用户的账号、密码、Cookie 或 Token" in text
        assert "stores_list" in text
        assert "clues_follow_up_stats" in text
