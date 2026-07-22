"""Unauthenticated discovery endpoints for Agent and CLI onboarding."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from dy_api.agent_contract import (
    agent_capabilities,
    agent_manifest,
    render_agent_guide,
    render_agent_skill,
)


router = APIRouter()


@router.get("/.well-known/dydata-agent.json")
def get_agent_manifest() -> dict[str, object]:
    """Return the stable machine-readable Agent entrypoint."""
    return agent_manifest()


@router.get("/api/v1/agent/capabilities")
def get_agent_capabilities() -> dict[str, object]:
    """Return the generated read-only capability contract."""
    return agent_capabilities()


@router.get("/agent.md")
def get_agent_guide() -> Response:
    """Return the platform-neutral Agent onboarding guide."""
    return Response(render_agent_guide(), media_type="text/markdown")


@router.get("/agent/SKILL.md")
def get_agent_skill() -> Response:
    """Return the generic Agent Skill backed by the live manifest."""
    return Response(render_agent_skill(), media_type="text/markdown")
