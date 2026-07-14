import json
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = REPO_ROOT / ".agent" / "project-manager-suite"
LOCK_PATH = REPO_ROOT / ".agent" / "project-manager-suite.lock.json"
BASELINE_PATH = REPO_ROOT / "docs" / "baseline" / "baseline-audit-dy-data.json"
LINK_GRAPH_PATH = REPO_ROOT / "docs" / "index" / "project-link-graph.json"


def _contains_windows_absolute_path(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_windows_absolute_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_windows_absolute_path(item) for item in value)
    return isinstance(value, str) and re.search(r"[A-Za-z]:\\", value) is not None


def test_project_manager_suite_install_is_locked_and_portable() -> None:
    package_metadata = json.loads((SUITE_ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    manifest = json.loads((SUITE_ROOT / ".install-manifest.json").read_text(encoding="utf-8"))

    assert package_metadata["version"] == "2.0.0"
    assert lock["suite_version"] == "2.0.0"
    assert lock["target_path"] == ".agent/project-manager-suite"
    assert lock["content_hash_algorithm"] == "sha256-path-null-lf-v1"
    assert re.fullmatch(r"[a-f0-9]{64}", lock["content_sha256"])
    assert not _contains_windows_absolute_path(lock)
    assert not _contains_windows_absolute_path(manifest)

    result = subprocess.run(
        [
            "node",
            str(SUITE_ROOT / "tools" / "verify-suite-lock.mjs"),
            str(REPO_ROOT),
            "--json",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    verification = json.loads(result.stdout)
    assert verification["status"] == "valid"
    assert verification["manifest_verified"] is True


def test_generated_governance_artifacts_are_repository_relative() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    link_graph = json.loads(LINK_GRAPH_PATH.read_text(encoding="utf-8"))

    assert baseline["hostRoot"] == "."
    assert link_graph["hostRoot"] == "."
    assert not _contains_windows_absolute_path(baseline)
    assert not _contains_windows_absolute_path(link_graph)


def test_local_worktrees_are_ignored() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/.worktrees/" in gitignore


def test_agents_routes_project_work_through_installed_suite() -> None:
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "## 2. Project Governance Suite Gate" in agents
    assert ".agent/project-manager-suite.lock.json" in agents
    assert "tools/verify-suite-lock.mjs" in agents
    assert "skills/00-01-ai-project-manager/SKILL.md" in agents
    assert "tools/validate-global-files.mjs" in agents
    assert "tools/route-check.mjs" in agents
    assert "AI-Coding助手2.0" not in agents


def test_governance_authority_files_define_distinct_roles() -> None:
    project_rules = (REPO_ROOT / "project-rules.md").read_text(encoding="utf-8")
    project_profile = (REPO_ROOT / "project-profile.md").read_text(encoding="utf-8")
    execution_plan = (REPO_ROOT / "docs" / "plans" / "execution-plan.md").read_text(
        encoding="utf-8"
    )
    authority_map = (REPO_ROOT / "docs" / "governance" / "authority-map.md").read_text(
        encoding="utf-8"
    )
    rules_readme = (REPO_ROOT / "docs" / "rules" / "README.md").read_text(encoding="utf-8")

    for marker in (
        "## 1. 规则入口与引用约定",
        "## 2. 项目结构约定",
        "## 3. 工作方式约定",
        "## 6. 交付件要求",
        "## 7. AI 协作规则",
        "Linear",
        "AGENTS.md",
        "docs/rules/",
    ):
        assert marker in project_rules

    for marker in (
        "## 1. 当前阶段",
        "## 2. 当前目标",
        "## 3. 进行中任务",
        "## 4. 下一步任务",
        "## 5. 完成标准",
        "当前正式计划文件组",
        "当前子开发计划：",
        "DYDATA-6",
    ):
        assert marker in execution_plan

    for path in (
        "docs/项目产品介绍书.md",
        "docs/architecture.md",
        "docs/技术架构与部署规划.md",
        "docs/data-model.md",
        "docs/api-contract.md",
        "docs/design-system/README.md",
        "docs/superpowers/specs/",
        "docs/plans/",
    ):
        assert path in authority_map

    for status in ("authority", "evidence", "legacy", "stale", "missing"):
        assert f"`{status}`" in authority_map

    assert "DYDATA-7" in rules_readme
    assert "不从套包默认规则直接复制" in rules_readme
    assert "docs/design-system/README.md" in project_profile
    assert "docs/design-system/tokens.json" in project_profile
    assert "docs/design-system.md" not in project_profile


def test_ci_runs_suite_governance_gates_before_product_tests() -> None:
    required_commands = (
        "npm --prefix .agent/project-manager-suite run test:ai-pm",
        "node .agent/project-manager-suite/tools/verify-suite-lock.mjs .",
        "node .agent/project-manager-suite/tools/check-protocol-alignment.mjs .agent/project-manager-suite",
        "node .agent/project-manager-suite/tools/validate-global-files.mjs .",
        "node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S0.5",
    )

    for relative_path in (
        ".github/workflows/ci-cd.yml",
        ".github/workflows/tencent-lighthouse-deploy.yml",
    ):
        workflow = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        positions = [workflow.index(command) for command in required_commands]
        assert positions == sorted(positions)
        assert positions[-1] < workflow.index("python -m pytest")
