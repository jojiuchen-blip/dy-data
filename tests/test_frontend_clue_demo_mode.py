from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
SRC = WEB / "src"


def _read(relative_path: str) -> str:
    return (SRC / relative_path).read_text(encoding="utf-8")


def test_demo_mode_requires_dev_and_explicit_flag() -> None:
    source = _read("demo/clueDemoMode.ts")
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    demo_env = (WEB / ".env.demo").read_text(encoding="utf-8")

    assert "import.meta.env.DEV" in source
    assert 'VITE_DEMO_MODE === "true"' in source
    assert "CLUE_DEMO_MODE" in source
    assert 'user_id: "DEMO-USER-ADMIN"' in source
    assert 'display_name: "演示最高管理员"' in source
    assert package["scripts"]["dev:demo"] == "vite --host 127.0.0.1 --mode demo"
    assert "VITE_DEMO_MODE=true" in demo_env
    assert "VITE_USE_MOCKS=true" in demo_env
