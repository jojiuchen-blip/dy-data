from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
SRC = WEB / "src"


def _read(relative_path: str) -> str:
    return (SRC / relative_path).read_text(encoding="utf-8")


def _exported_function(source: str, name: str) -> str:
    start = source.index(f"export async function {name}")
    end = source.find("\nexport ", start + 1)
    return source[start:] if end == -1 else source[start:end]


def test_demo_mode_requires_dev_and_explicit_flag() -> None:
    source = _read("demo/clueDemoMode.ts")
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    demo_env = (WEB / ".env.demo").read_text(encoding="utf-8")

    assert "import.meta.env.DEV" in source
    assert 'VITE_DEMO_MODE === "true"' in source
    assert "CLUE_DEMO_MODE" in source
    assert 'user_id: "DEMO-USER-ADMIN"' in source
    assert 'role: "highest_admin"' in source
    assert 'store_scope_mode: "all"' in source
    assert "page_keys: [" in source
    assert '"A01"' in source
    assert '"A02"' in source
    assert '"B01"' not in source
    assert '"C01"' not in source
    assert '"D01"' not in source
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


def test_demo_mode_is_scoped_to_clue_paths_and_keeps_other_routes_live() -> None:
    demo_mode = _read("demo/clueDemoMode.ts")
    client = _read("api/client.ts")
    app = _read("App.tsx")

    assert "isClueDemoPathname" in demo_mode
    for allowed_path in ['pathname === "/clues"', 'pathname === "/clues/details"']:
        assert allowed_path in demo_mode
    for rejected_path in ["/finance/promotion", "/settlement", "/admin", "/auth/"]:
        assert rejected_path not in demo_mode

    assert 'const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "true";' in client
    assert "blockDemoNetwork" not in client
    assert "CLUE_DEMO_MODE || import.meta.env.VITE_USE_MOCKS" not in client
    assert "allowDemoIdentity" in client
    assert "CLUE_DEMO_MODE && options.allowDemoIdentity" in client
    assert "function isClueDemoRuntime(): boolean" in client
    assert (
        "CLUE_DEMO_MODE && isClueDemoPathname(window.location.pathname)"
        in client
    )
    assert "if (CLUE_DEMO_MODE)" not in client

    assert "isClueDemoPathname(location.pathname)" in app
    assert "fetchAdminSession({ allowDemoIdentity: isDemoMode })" in app
    assert "isDemoMode={isDemoMode}" in app
    assert "onLogout={isDemoMode ? undefined : onLogout}" in app

    for value in [
        "CLUE_DEMO_MODE",
        "clueDemoRepository",
        "demoLoad",
        "clueDemoRepository.getAssignmentRounds",
        "clueDemoRepository.saveFollowUp",
        "clueDemoRepository.getHeadquartersPool",
        "clueDemoRepository.previewCycle",
        "clueDemoRepository.runTrial",
        "clueDemoRepository.getRules",
    ]:
        assert value in client


def test_admin_clue_allocation_demo_branches_are_pathname_scoped() -> None:
    client = _read("api/client.ts")
    admin_functions = [
        "fetchClueAllocationEligibleLeads",
        "fetchClueHeadquartersPool",
        "fetchClueAllocationCycles",
        "fetchClueAllocationAuditLogs",
        "previewClueAllocationCycle",
        "runClueAllocationTrial",
        "rebuildClueAllocationTrial",
        "fetchClueAllocationRules",
        "fetchClueAllocationRuleDetail",
        "fetchClueAllocationDecisions",
        "fetchClueAllocationStoreScores",
        "createClueAllocationRule",
        "createClueAllocationRuleVersion",
        "publishClueAllocationRuleVersion",
        "retireClueAllocationRuleVersion",
    ]

    for function_name in admin_functions:
        function_source = _exported_function(client, function_name)
        assert "if (isClueDemoRuntime())" in function_source
        assert "/admin/clue-allocation/" in function_source


def test_auth_gate_clears_stale_identity_before_session_refetch() -> None:
    app = _read("App.tsx")
    auth_gate = app[app.index("function AuthGate"):]
    effect = auth_gate[: auth_gate.index("}, [isDemoMode]);")]

    checking_index = effect.index("setChecking(true);")
    clear_user_index = effect.index("setUser(null);")
    fetch_index = effect.index("fetchAdminSession({ allowDemoIdentity: isDemoMode })")

    assert checking_index < clear_user_index < fetch_index
    assert 'key={isDemoMode ? "clue-demo" : "live"}' in app



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


def test_demo_status_reasons_use_supported_label_codes() -> None:
    combined = "\n".join(
        [
            _read("demo/clueDemoGenerator.ts"),
            _read("demo/clueDemoRepository.ts"),
        ]
    )

    for unsupported in [
        "订单已退款",
        "分配策略已穷尽",
        "首次跟进时限内",
        "跟进保护期内",
        "历史流转轮次",
        "演示跟进保护期内",
        "新一轮首次跟进时限内",
        "试运行重建生成",
        "试运行生成",
    ]:
        assert f'"{unsupported}"' not in combined

    for supported in [
        'statusReason: "order_refunded"',
        'statusReason: "strategies_exhausted"',
        'status_reason: "allocated_to_store"',
    ]:
        assert supported in combined


def test_demo_allocation_decisions_use_supported_execution_modes() -> None:
    combined = "\n".join(
        [
            _read("demo/clueDemoGenerator.ts"),
            _read("demo/clueDemoRepository.ts"),
        ]
    )

    assert 'execution_mode: "demo"' not in combined
    assert 'execution_mode: "formal"' in combined


def test_demo_admin_data_uses_supported_event_and_reason_codes() -> None:
    combined = "\n".join(
        [
            _read("demo/clueDemoGenerator.ts"),
            _read("demo/clueDemoRepository.ts"),
        ]
    )

    for unsupported in [
        "cycle_previewed",
        "cycle_executed",
        "cycle_rebuilt",
        "rule_published",
        "all_strategies_exhausted",
        "direct_headquarters",
        "demo_rebuild",
        "demo_trial",
    ]:
        assert f'"{unsupported}"' not in combined

    for supported in [
        '? "trial_executed"',
        '"trial_rebuilt" : "trial_executed"',
        'reason: "strategies_exhausted"',
        'reason: "sale_store_unmapped"',
    ]:
        assert supported in combined
