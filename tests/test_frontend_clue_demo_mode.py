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


def test_demo_generator_has_required_scale_and_privacy_guards() -> None:
    profile = _read("demo/clueDemoProfile.ts")
    generator = _read("demo/clueDemoGenerator.ts")
    types = _read("demo/clueDemoTypes.ts")
    combined = "\n".join([profile, generator, types])

    for required in [
        "leadCount: 480",
        "storeCount: 48",
        "cityCount: 12",
        "oneRoundLeadCount: 230",
        "twoRoundLeadCount: 90",
        "threeRoundLeadCount: 40",
        "directHeadquartersLeadCount: 60",
        "terminalWithoutRoundLeadCount: 60",
        "minimumFollowUpCount: 650",
        "maximumFollowUpCount: 750",
        "createClueDemoState",
        "assertClueDemoState",
        'startsWith("DEMO-")',
    ]:
        assert required in combined

    assert "local_exports" not in combined
    assert "telephone" not in profile.lower()
    assert "follow_life_account_name" not in profile


def test_demo_repository_exposes_coherent_clue_center_reads() -> None:
    source = _read("demo/clueDemoRepository.ts")
    for name in [
        "class ClueDemoRepository",
        "getFilters(",
        "getOverview(",
        "getAssignmentRounds(",
        "getOrderDetail(",
        "getOrderPhone(",
        "filterRounds(",
        "paginate(",
        "reset(",
        'source: "demo"',
    ]:
        assert name in source
