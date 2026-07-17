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


def test_demo_repository_models_follow_up_and_round_transitions() -> None:
    source = _read("demo/clueDemoRepository.ts")
    for value in [
        "saveFollowUp(",
        "deleteFollowUpRecord(",
        "advanceAfterRoundFailure(",
        "exportAssignmentRounds(",
        'payload.follow_result === "lost"',
        'payload.follow_result === "request_store_change"',
        'round.round_effective_status = "inactive"',
        "round.can_operate_current_round = false",
        "DEMO-PHONE-",
        "demo-clue-assignment-rounds-",
    ]:
        assert value in source


def test_demo_repository_covers_all_allocation_admin_calls() -> None:
    source = _read("demo/clueDemoRepository.ts")
    for method in [
        "getEligibleLeads(",
        "getHeadquartersPool(",
        "getCycles(",
        "getAuditLogs(",
        "previewCycle(",
        "runTrial(",
        "rebuildTrial(",
        "getRules(",
        "getRuleDetail(",
        "getDecisions(",
        "getStoreScores(",
        "createRule(",
        "createRuleVersion(",
        "publishRuleVersion(",
        "retireRuleVersion(",
    ]:
        assert method in source

    for marker in ["DEMO-PREVIEW-", "DEMO-CYCLE-", "DEMO-AUDIT-", "previewTokens"]:
        assert marker in source


def test_client_routes_clue_and_admin_calls_without_demo_network() -> None:
    client = _read("api/client.ts")
    app = _read("App.tsx")

    for value in [
        "CLUE_DEMO_MODE",
        "CLUE_DEMO_ADMIN_USER",
        "clueDemoRepository",
        "demoLoad",
        "blockDemoNetwork",
        'fallbackReason: "当前展示合成演示数据。"',
        "clueDemoRepository.getAssignmentRounds",
        "clueDemoRepository.saveFollowUp",
        "clueDemoRepository.getHeadquartersPool",
        "clueDemoRepository.previewCycle",
        "clueDemoRepository.runTrial",
        "clueDemoRepository.getRules",
    ]:
        assert value in client

    assert "isDemoMode={CLUE_DEMO_MODE}" in app
    assert "CLUE_DEMO_MODE ? undefined : onLogout" in app


def test_shell_discloses_demo_data_on_desktop_and_mobile() -> None:
    shell = _read("components/Shell.tsx")
    styles = _read("styles.css")
    readme = (WEB / "README.md").read_text(encoding="utf-8")

    assert "isDemoMode?: boolean" in shell
    assert "演示数据 · 全部为合成数据 · 不写入数据库" in shell
    assert "demo-mode-notice" in shell
    assert ".demo-mode-notice" in styles
    assert ".app-shell--demo" in styles
    assert "npm run dev:demo" in readme
    assert "刷新页面后恢复" in readme
