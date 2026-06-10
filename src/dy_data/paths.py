from __future__ import annotations

from pathlib import Path

from .config import path_value, script_root, workspace_root


def app_path(name: str, env_name: str | None = None, default: str | Path | None = None) -> Path:
    return path_value(name, env_name=env_name, default=default)


__all__ = ["app_path", "path_value", "script_root", "workspace_root"]
