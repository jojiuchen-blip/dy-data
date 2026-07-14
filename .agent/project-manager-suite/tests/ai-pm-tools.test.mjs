import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { validateGlobalFiles } from '../tools/validate-global-files.mjs';
import { routeCheck } from '../tools/route-check.mjs';
import { generateHostRules } from '../tools/generate-host-rules.mjs';
import { bootstrapHost } from '../tools/bootstrap-host.mjs';
import { installSuiteIntoHost } from '../tools/install-suite-into-host.mjs';
import { devlogSync } from '../tools/devlog-sync.mjs';
import { checkPlanConsistency } from '../skills/05-01-delivery-planner/scripts/check-plan-consistency.mjs';
import { collectBaselineGaps } from '../skills/01-01-project-baseline-auditor/scripts/collect-baseline-gaps.mjs';
import { collectProjectLinks } from '../skills/00-03-project-link-indexer/scripts/collect-project-links.mjs';
import { runProjectLinkIndexer } from '../skills/00-03-project-link-indexer/scripts/run-project-link-indexer.mjs';
import { validateProjectLinks } from '../skills/00-03-project-link-indexer/scripts/validate-project-links.mjs';
import { buildClaudeHookBootstrap, buildOpenCodeBootstrap } from '../lib/bootstrap/index.js';
import { verifyTask } from '../skills/06-01-coding-standards/scripts/verify-task-context.mjs';
import { createEmptyLedger, writeLedger } from '../skills/02-01-brd-writer/scripts/ledger-io.mjs';
import { fileRoles, globalCompanionAbilities } from '../lib/ai-pm-protocol/index.js';

const TEST_FILE_PATH = fileURLToPath(import.meta.url);
const CURRENT_SUITE_ROOT = path.resolve(path.dirname(TEST_FILE_PATH), '..');

function makeTempDir(prefix) {
    return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function writeFile(targetPath, content) {
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    fs.writeFileSync(targetPath, content, 'utf8');
}

function writeJsonFile(targetPath, value) {
    writeFile(targetPath, JSON.stringify(value, null, 2));
}

function readFile(targetPath) {
    return fs.readFileSync(targetPath, 'utf8');
}

function buildStartupInterview(overrides = {}) {
    return {
        project_name: '演示项目',
        project_one_liner: '帮助团队稳定推进项目',
        target_users: '运营人员',
        main_problem: '推进信息分散',
        ...overrides
    };
}

function buildRulesContent() {
    return `# 项目全局规则

## 1. 规则入口与引用约定

- 规则入口：project-rules.md

## 2. 项目结构约定

- 项目结构：docs/、logs/、.agent/

## 3. 工作方式约定

- 每轮沉淀：是

## 6. 交付件要求

- 交付物要求：按阶段沉淀

## 7. AI 协作规则

- AI 协作：主入口先校验再推进
`;
}

function buildProfileContent(overrides = {}) {
    const values = {
        project_name: '演示项目',
        project_one_liner: '帮助团队稳定推进项目',
        current_stage: 'S1',
        collaboration_mode: '业务单人 + AI执行',
        target_users: '运营人员',
        main_problem: '当前推进信息分散',
        v1_core_goal: '完成需求收敛',
        coverage_scope: '内部人员',
        page_primary_user: '运营人员',
        page_primary_purpose: '业务处理',
        page_positioning_tag: '操作',
        recommended_stage: 'S1',
        current_round_deliverable: '业务需求文档 / BRD',
        largest_uncertainty: '验收口径待确认',
        current_executor: 'ai-project-manager'
    };

    Object.assign(values, overrides);

    return `# 项目画像

## 1. 基本信息

- 项目名称：${values.project_name}
- 项目一句话目标：${values.project_one_liner}
- 目标使用者：${values.target_users}
- 主要问题：${values.main_problem}

## 2. 身份识别

- 协作模式：${values.collaboration_mode}

## 3. 业务目标

- 第一版核心目标：${values.v1_core_goal}

## 4. 页面与任务定位

- 项目覆盖对象：${values.coverage_scope}
- 当前页面主要给谁用：${values.page_primary_user}
- 当前页面主要用途：${values.page_primary_purpose}
- 页面定位标签：${values.page_positioning_tag}

## 5. 当前资产

- 已有材料：BRD 草稿

## 6. 项目入口与识别信息

- 计划入口：docs/plans/execution-plan.md
- 状态入口：logs/

## 7. 当前判断

- 当前阶段：${values.current_stage}
- 当前最适合进入的阶段：${values.recommended_stage}
- 当前轮应输出的交付物：${values.current_round_deliverable}
- 当前最大不确定项：${values.largest_uncertainty}
- 当前任务执行主体：${values.current_executor}

## 8. 待确认

- 验收口径待确认
`;
}

function buildPlanContent(overrides = {}) {
    const values = {
        current_stage: 'S1',
        current_goal: '完成 BRD 收敛',
        in_progress: '整理核心需求',
        next_tasks: '准备进入页面阶段',
        completion_criteria: 'BRD 可评审'
    };

    Object.assign(values, overrides);

    return `# 当前执行计划

## 1. 当前阶段

- ${values.current_stage}

## 2. 当前目标

- ${values.current_goal}

## 3. 进行中任务

- ${values.in_progress}

## 4. 下一步任务

- ${values.next_tasks}

## 5. 完成标准

- ${values.completion_criteria}

## 6. 前置依赖

- 用户确认页面方向

## 7. 待确认项

- 页面细节待确认
`;
}

function writeFoundationArtifacts(hostRoot, slug = 'demo') {
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', `foundation-glossary-${slug}.md`), '# 术语表\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', `foundation-schema-${slug}.md`), '# 数据结构\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', `foundation-api-${slug}.md`), '# 接口草案\n');
    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'foundation', `foundation-delivery-${slug}.md`),
        `# Foundation 交付清单

| 产物 | 文件路径 | 说明 |
|---|---|---|
| 术语表 | docs/prd/foundation/foundation-glossary-${slug}.md | 已确认 |
| 数据结构 | docs/prd/foundation/foundation-schema-${slug}.md | 已确认 |
| 接口草案 | docs/prd/foundation/foundation-api-${slug}.md | 已确认 |
`
    );
}

function writeFullPrdArtifacts(hostRoot, slug = 'demo') {
    const mainFile = `mainprd-${slug}.md`;
    const subprdFile = 'subprd/01-subprd-core.md';

    writeFile(
        path.join(hostRoot, 'docs', 'prd', `prd-feature-list-${slug}.md`),
        `# 功能列表

## 功能总表

| # | 页面 | 区块 | 功能说明 | subprd文件 | 状态 |
|---|---|---|---|---|---|
| 1 | 操作页 | 核心操作 | 处理核心流程 | [01-subprd-core.md](${subprdFile}) | 已确认 |
`
    );
    writeFile(
        path.join(hostRoot, 'docs', 'prd', mainFile),
        `# mainprd

## subprd索引

| # | 区块 | 所属页面 | subprd文件 | 状态 |
|---|---|---|---|---|
| 1 | 核心操作 | 操作页 | [01-subprd-core.md](${subprdFile}) | 已确认 |
`
    );
    writeFile(
        path.join(hostRoot, 'docs', 'prd', subprdFile),
        `# 核心操作 subprd

- mainprd回链：[${mainFile}](../${mainFile})
`
    );
}

function buildMainDeliveryPlanContent(slug = 'demo') {
    return `# Demo Main Delivery Plan

> **版本**：v1
> **发布日期**：2026-06-01
> **适用范围**：demo

## 驾驶舱摘要（供 \`execution-plan.md\` 同步）

| 字段 | 内容 |
|---|---|
| 当前正式计划文件 | \`main-delivery-plan-${slug}.md\` |
| 当前任务看板 | \`task-kanban-${slug}.md\` |
| 当前子开发计划 | \`sub-delivery-plan-${slug}-T0.1-demo-task.md\` |
| 当前阶段 | \`S4 开发执行\` |
| 当前目标 | 当前进入 T0.1 实现演示任务。 |
| 当前活跃 Phase / Task | \`Phase 0 / T0.1 实现演示任务\` |
| 下一步任务 | 打开 T0.1 子开发计划并执行演示任务。 |
| 完成标准摘要 | \`node src/demo.js\` 输出 demo-ok。 |
| 当前阻塞与前置依赖 | 无 |
| 待确认项 | 无 |

## 0. 本计划使用指南
### 0.2 PRD 加载约束
按任务读取 PRD。
### 0.3 读前门禁
动手前确认 PRD、核心逻辑和核心文件。
### 0.4 完成前验证门禁
完成后执行真实验证。

## 环境依赖声明
无额外环境依赖。

## 1. 差距基线
- G1: demo gap

## 2. 分工与边界
- AI 执行，人审核。

## 3. 执行阶段
### Phase 0：Demo
| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.1 | [sub-delivery-plan-${slug}-T0.1-demo-task.md](sub-delivery-plan-${slug}-T0.1-demo-task.md) | 进行中 |

## 4. 任务看板
- 看板入口：[task-kanban-${slug}.md](task-kanban-${slug}.md)

## 5. 发布闸门
- [ ] 真实验证完成

## 6. 风险与应对
- 无

## 7. AI 执行示例
- 读取任务看板，按 Task 进入对应子开发计划。

## 8. PRD → 任务反向索引
| PRD | Task | 子开发计划 |
|---|---|---|
| mainprd-${slug}.md §1 | T0.1 | [sub-delivery-plan-${slug}-T0.1-demo-task.md](sub-delivery-plan-${slug}-T0.1-demo-task.md) |
`;
}

function buildTaskKanbanContent(slug = 'demo') {
    return `# Demo Task Kanban

| Task | 子开发计划 | Owner | 前置 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|---|---|
| T0.1 | [sub-delivery-plan-${slug}-T0.1-demo-task.md](sub-delivery-plan-${slug}-T0.1-demo-task.md) | AI | 无 | 进行中 | - | demo |
`;
}

function buildSubDeliveryPlanContent(slug = 'demo') {
    return `# T0.1 Demo Sub Delivery Plan

## 任务来源
- 主开发计划：[main-delivery-plan-${slug}.md](main-delivery-plan-${slug}.md)
- 任务看板：[task-kanban-${slug}.md](task-kanban-${slug}.md)

#### T0.1 实现演示任务

**Requirement ID**：REQ-DEMO-001

**PRD 双链·读**：
- \`mainprd-${slug}.md\` §1

**核心逻辑**：
- 根据 PRD 处理演示任务。

**核心文件**：
- \`src/demo.js\`

**完成标准**：
- 运行 \`node src/demo.js\` 输出 demo-ok。

**Verification Method**：
- 执行 \`node src/demo.js\`。

**Evidence**：
- logs/demo-task.md

**Failure Handling**：
- PRD 或核心文件定位不到时阻塞。

**完成收尾：状态同步**：
- 完成实现与验证后，把完成事实、验证证据和完成日期提交给 \`ai-project-manager\`，同步主计划、看板和本子计划状态。

**Owner**：AI 执行 -> 人审核
**前置**：无
**状态**：进行中
`;
}

function writeMultiFileDeliveryPlan(hostRoot, slug = 'demo') {
    const planDir = path.join(hostRoot, 'docs', 'plans', 'delivery-plans');
    const mainPath = path.join(planDir, `main-delivery-plan-${slug}.md`);
    const kanbanPath = path.join(planDir, `task-kanban-${slug}.md`);
    const subPath = path.join(planDir, `sub-delivery-plan-${slug}-T0.1-demo-task.md`);

    writeFile(mainPath, buildMainDeliveryPlanContent(slug));
    writeFile(kanbanPath, buildTaskKanbanContent(slug));
    writeFile(subPath, buildSubDeliveryPlanContent(slug));

    return { planDir, mainPath, kanbanPath, subPath };
}

function createHostFixture({ withRules = true, withProfile = true, withPlan = true, withDevlog = true, profileOverrides = {}, planOverrides = {}, logContent = '记录 S1 阶段推进' } = {}) {
    const hostRoot = makeTempDir('pm-suite-host-');

    if (withRules) {
        writeFile(path.join(hostRoot, 'project-rules.md'), buildRulesContent());
    }

    if (withProfile) {
        writeFile(path.join(hostRoot, 'project-profile.md'), buildProfileContent(profileOverrides));
    }

    if (withPlan) {
        writeFile(path.join(hostRoot, 'docs', 'plans', 'execution-plan.md'), buildPlanContent(planOverrides));
    }

    if (withDevlog) {
        writeFile(path.join(hostRoot, 'logs', '20260406_refactor_log_tester.md'), logContent);
    }

    return hostRoot;
}

test('validate-global-files resolves authority files on a valid host fixture', () => {
    const hostRoot = createHostFixture();
    generateHostRules({ hostRoot, dryRun: false, force: false });

    const result = validateGlobalFiles({ hostRoot });

    assert.equal(result.summary.errors, 0);
    assert.equal(result.authority.project_profile, 'project-profile.md');
    assert.equal(result.authority.global_rules, 'project-rules.md');
    assert.equal(result.authority.execution_plan, 'docs/plans/execution-plan.md');
    assert.equal(result.authority.project_devlog, 'logs/20260406_refactor_log_tester.md');
    assert.equal(result.rulesDirectory.missingDefaultRules.length, 0);
});

test('validate-global-files resolves a host-configured devlog directory from project-profile', () => {
    const hostRoot = createHostFixture({ withDevlog: false });
    const profilePath = path.join(hostRoot, 'project-profile.md');
    const configuredProfile = readFile(profilePath).replace(
        '- 状态入口：logs/',
        '- 最近状态入口：`【系统推断】 docs/devlog/`'
    );
    writeFile(profilePath, configuredProfile);
    writeFile(path.join(hostRoot, 'docs', 'devlog', '20260406_refactor_log_tester.md'), '记录 S1 阶段推进');
    generateHostRules({ hostRoot, dryRun: false, force: false });

    const result = validateGlobalFiles({ hostRoot });

    assert.equal(result.authority.project_devlog, 'docs/devlog/20260406_refactor_log_tester.md');
    assert.equal(
        result.issues.some((issue) => ['missing_logs_directory', 'missing_devlog_entry'].includes(issue.code)),
        false
    );
});

test('route-check blocks S2 routing when stage transition writeback is missing', () => {
    const hostRoot = createHostFixture({
        withDevlog: false,
        profileOverrides: {
            current_stage: 'S1',
            recommended_stage: 'S1',
            current_round_deliverable: '页面代码 / 页面交付清单'
        },
        planOverrides: {
            current_stage: 'S1',
            current_goal: '进入页面设计阶段',
            next_tasks: '调用 page-designer'
        }
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });

    const result = routeCheck({ hostRoot, targetStage: 'S2' });

    assert.equal(result.canEnter, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'stage_transition_writeback_missing'));
    assert.equal(result.gateChecks.pageTaskRequired.pass, true);
});

test('route-check accepts date-style daily logs as stage transition evidence', () => {
    const hostRoot = createHostFixture({
        withDevlog: false,
        profileOverrides: {
            current_stage: 'S1',
            recommended_stage: 'S1',
            current_round_deliverable: '页面代码 / 页面交付清单'
        },
        planOverrides: {
            current_stage: 'S1',
            current_goal: '进入页面设计阶段',
            next_tasks: '调用 page-designer'
        }
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFile(path.join(hostRoot, 'logs', '2026-05-22.md'), '# 2026-05-22\n\n记录 S2 阶段切换。\n');

    const result = routeCheck({ hostRoot, targetStage: 'S2' });

    assert.equal(result.gateChecks.stageWritebackBeforeRouting.pass, true);
    assert.equal(result.gateChecks.stageWritebackBeforeRouting.evidence, 'logs/2026-05-22.md');
    assert.ok(!result.blockingReasons.some((item) => item.code === 'stage_transition_writeback_missing'));
});

test('route-check treats page task option lists as unresolved placeholders', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S1',
            recommended_stage: 'S1',
            current_round_deliverable: '页面代码 / 页面交付清单',
            coverage_scope: '本地工具 / 内网工具 / 待确认',
            page_primary_user: '例如自己、同岗位、操作员、管理员',
            page_primary_purpose: '业务处理 / 系统管理 / 内容展示 / 待确认',
            page_positioning_tag: '操作 / 配置 / 查看 / 待确认'
        },
        planOverrides: {
            current_stage: 'S1',
            current_goal: '进入页面设计阶段',
            next_tasks: '调用 page-designer'
        },
        logContent: '记录 S2 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });

    const result = routeCheck({ hostRoot, targetStage: 'S2' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.pageTaskRequired.pass, false);
    assert.deepEqual(
        result.gateChecks.pageTaskRequired.missingFields.sort(),
        ['coverage_scope', 'page_positioning_tag', 'page_primary_purpose', 'page_primary_user']
    );
});

test('route-check stays in startup/bootstrap mode when page signal appears before authority files exist', () => {
    const hostRoot = makeTempDir('pm-suite-host-startup-page-signal-');

    writeFile(
        path.join(hostRoot, 'notes.md'),
        '# 启动记录\n\n- 目标：先做车主端页面和管理后台\n- 下一步：梳理页面方向\n'
    );

    const result = routeCheck({ hostRoot, targetStage: 'S2' });

    assert.equal(result.canEnter, false);
    assert.equal(result.currentStage, null);
    assert.equal(result.recommendedStage, 'S0');
    assert.equal(result.routeTarget, null);
    assert.equal(result.nextAction, '停留主入口，发起首轮极简访谈并补齐项目画像');
    assert.ok(result.blockingReasons.some((item) => item.code === 'startup_minimum_missing'));
});

test('route-check sends code-only existing host to baseline auditor before startup interview', () => {
    const hostRoot = makeTempDir('pm-suite-existing-code-no-profile-');
    writeJsonFile(path.join(hostRoot, 'package.json'), {
        name: 'half-built-console',
        description: '已经开发一半的业务控制台'
    });
    writeFile(path.join(hostRoot, 'src', 'pages', 'Home.vue'), '<template>home</template>\n');

    const result = routeCheck({ hostRoot });

    assert.equal(result.recommendedStage, 'S0.5');
    assert.equal(result.targetStage, 'S0.5');
    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'project-baseline-auditor');
    assert.equal(result.blockingReasons.some((item) => item.code === 'startup_minimum_missing'), false);
    assert.match(result.nextAction, /project-baseline-auditor/);
});

test('collect-baseline-gaps creates project profile draft and maintenance document gap list from existing code', () => {
    const hostRoot = makeTempDir('pm-suite-baseline-code-only-');
    writeJsonFile(path.join(hostRoot, 'package.json'), {
        name: 'maintenance-console',
        description: '维护现有业务控制台'
    });
    writeFile(path.join(hostRoot, 'src', 'pages', 'Dashboard.vue'), '<template><button>保存</button></template>\n');
    writeFile(path.join(hostRoot, 'src', 'api', 'orders.js'), 'export function listOrders() { return fetch("/api/orders"); }\n');
    writeFile(path.join(hostRoot, 'src', 'models', 'order.js'), 'export const order = { id: "string" };\n');

    const result = collectBaselineGaps({ hostRoot, write: true });
    const profileContent = readFile(path.join(hostRoot, 'project-profile.md'));
    const artifactTypes = result.artifacts.map((item) => item.type);

    assert.equal(result.mode, 'existing-project-baseline');
    assert.equal(result.scope, 'maintenance-docs-only');
    assert.equal(fs.existsSync(path.join(hostRoot, 'docs', 'baseline', `baseline-audit-${result.slug}.json`)), true);
    assert.match(profileContent, /项目名称：`【系统推断】 maintenance-console`/);
    assert.match(profileContent, /当前最大不确定项：`【主入口回写】 目标使用者待确认`/);
    assert.equal(result.profile.next_questions.length, 1);
    assert.equal(result.profile.next_questions[0].field, 'target_users');
    assert.deepEqual(artifactTypes, ['PROJECT_PROFILE', 'BRD', 'PAGE_EXPLAINER', 'FOUNDATION', 'PRD']);
    assert.equal(result.artifacts.some((item) => /delivery-planner|test-case/.test(item.recommended_skill || '')), false);
});

test('collect-baseline-gaps ignores dependency and generated directories at any depth', () => {
    const hostRoot = makeTempDir('pm-suite-baseline-ignore-noise-');
    writeJsonFile(path.join(hostRoot, 'package.json'), {
        name: 'legacy-ops-console',
        description: '标准化历史运营控制台'
    });
    writeFile(path.join(hostRoot, 'apps', 'admin', 'src', 'views', 'Dashboard.vue'), '<template>real page</template>\n');
    writeFile(path.join(hostRoot, 'apps', 'admin', 'src', 'api', 'orders.js'), 'export const ordersApi = "/api/orders";\n');
    writeFile(path.join(hostRoot, 'apps', 'admin', 'node_modules', 'vendor', 'Widget.vue'), '<template>dependency page</template>\n');
    writeFile(path.join(hostRoot, 'apps', 'admin', 'dist', 'api-endpoints.js'), 'export const generatedApi = "/api/generated";\n');
    writeFile(path.join(hostRoot, 'server', 'target', 'classes', 'db', 'migration', 'V1__generated.sql'), 'create table generated_noise(id int);\n');

    const result = collectBaselineGaps({ hostRoot, write: false });
    const evidencePaths = [
        ...result.evidence.pages,
        ...result.evidence.apis,
        ...result.evidence.models,
        ...result.evidence.configs
    ];

    assert.equal(evidencePaths.some((item) => item.includes('/node_modules/')), false);
    assert.equal(evidencePaths.some((item) => item.includes('/dist/')), false);
    assert.equal(evidencePaths.some((item) => item.includes('/target/')), false);
    assert.ok(result.evidence.pages.includes('apps/admin/src/views/Dashboard.vue'));
    assert.ok(result.evidence.apis.includes('apps/admin/src/api/orders.js'));
});

test('collect-baseline-gaps reports precise host evidence without cache or worktree-path noise', () => {
    const hostRoot = makeTempDir('pm-suite-baseline-precise-evidence-');
    writeFile(path.join(hostRoot, 'README.md'), '# dy-data\n\n面向经销商的订单经营平台。\n');
    writeFile(path.join(hostRoot, '.pytest_cache', 'README.md'), '# pytest cache\n');
    writeFile(path.join(hostRoot, 'apps', 'web', 'src', 'pages', 'DashboardPage.tsx'), 'export function DashboardPage() { return null; }\n');
    writeFile(path.join(hostRoot, 'apps', 'web', 'src', 'components', 'Button.tsx'), 'export function Button() { return null; }\n');
    writeFile(path.join(hostRoot, 'apps', 'web', 'src', 'App.tsx'), 'export function App() { return null; }\n');
    writeFile(
        path.join(hostRoot, 'apps', 'api', 'dy_api', 'routes', 'dashboard.py'),
        '@router.get("/dashboard")\ndef dashboard(): pass\n\n@router.post("/refresh")\ndef refresh(): pass\n'
    );
    writeFile(path.join(hostRoot, 'apps', 'api', 'dy_api', 'models.py'), 'class Order(Base):\n    pass\n');
    writeFile(path.join(hostRoot, 'alembic', 'versions', '001_initial.py'), 'def upgrade():\n    op.create_table("orders")\n');
    writeFile(path.join(hostRoot, 'src', 'dy_data', '__pycache__', 'config.cpython-312.pyc'), 'binary cache noise\n');

    const result = collectBaselineGaps({ hostRoot, slug: 'dy-data', write: false });

    assert.equal(result.hostRoot, '.');
    assert.equal(result.evidence.readme, 'README.md');
    assert.deepEqual(result.evidence.pages, ['apps/web/src/pages/DashboardPage.tsx']);
    assert.deepEqual(result.evidence.apis, ['apps/api/dy_api/routes/dashboard.py']);
    assert.deepEqual(result.evidence.models, ['alembic/versions/001_initial.py', 'apps/api/dy_api/models.py']);
    assert.equal(result.evidence.configs.some((item) => item.includes('__pycache__')), false);
    assert.deepEqual(result.evidence.counts, {
        page_files: 1,
        api_files: 1,
        api_endpoints: 2,
        model_files: 2,
        model_definitions: 1,
        migration_files: 1
    });
    assert.match(result.artifacts.find((item) => item.type === 'PAGE_EXPLAINER').reason, /页面文件线索 1 个/);
    assert.match(
        result.artifacts.find((item) => item.type === 'FOUNDATION').reason,
        /API 端点线索 2 个、模型定义 1 个、迁移 1 个/
    );
});

test('collect-baseline-gaps ignores AI tool directories when selecting project evidence', () => {
    const hostRoot = makeTempDir('pm-suite-baseline-ignore-tooling-');
    writeFile(path.join(hostRoot, 'src', 'views', 'Home.vue'), '<template>real host page</template>\n');
    writeFile(path.join(hostRoot, '.claude', 'skills', 'coding-standards', 'references', 'README.md'), '# Coding standards\n');
    writeFile(path.join(hostRoot, '.playwright-mcp', 'page-snapshot.yml'), 'url: http://localhost:3000\n');

    const result = collectBaselineGaps({ hostRoot, write: false });
    const evidencePaths = [
        result.evidence.readme,
        ...result.evidence.pages,
        ...result.evidence.apis,
        ...result.evidence.models,
        ...result.evidence.configs
    ].filter(Boolean);

    assert.equal(result.evidence.readme, null);
    assert.equal(evidencePaths.some((item) => item.includes('/.claude/')), false);
    assert.equal(evidencePaths.some((item) => item.includes('/.playwright-mcp/')), false);
    assert.ok(result.evidence.pages.includes('src/views/Home.vue'));
});

test('collect-baseline-gaps preserves user-confirmed profile fields while adding inferred evidence', () => {
    const hostRoot = makeTempDir('pm-suite-baseline-existing-profile-');
    writeFile(
        path.join(hostRoot, 'project-profile.md'),
        '# 项目画像\n\n## 1. 基本信息\n\n- 项目名称：`【用户确认】 老系统`\n- 项目一句话目标：`【用户确认】 稳定维护老系统`\n- 当前阶段：`【主入口回写】 S0`\n- 协作模式：`【系统推断】 业务单人 + AI执行`\n\n## 3. 业务目标\n\n- 目标使用者：`【用户确认】 运营人员`\n- 主要问题：`【用户确认】 文档缺失导致维护困难`\n\n## 4. 页面与任务定位\n\n- 项目覆盖对象：`【用户确认】 内网工具`\n- 当前页面主要给谁用：`【用户确认】 值班主管`\n- 当前页面主要用途：`【用户确认】 业务处理`\n\n## 5. 第一版范围\n\n- 核心功能 1：`【用户确认】 工单流转`\n- 核心功能 2：`【用户确认】 权限配置`\n- 核心功能 3：`【用户确认】 数据看板`\n\n## 8. 当前判断\n\n- 当前最适合进入的阶段：`【主入口回写】 S0`\n- 当前轮应输出的交付物：`【主入口回写】 既有项目关键文件诊断清单`\n- 当前最大不确定项：`【主入口回写】 待确认`\n- 当前任务执行主体：`【主入口回写】 ai-project-manager`\n'
    );
    writeJsonFile(path.join(hostRoot, 'package.json'), {
        name: 'new-package-name',
        description: '代码中的描述'
    });
    writeFile(path.join(hostRoot, 'src', 'pages', 'Home.vue'), '<template>home</template>\n');

    const result = collectBaselineGaps({ hostRoot, write: true });
    const profileContent = readFile(path.join(hostRoot, 'project-profile.md'));

    assert.match(profileContent, /项目名称：`【用户确认】 老系统`/);
    assert.match(profileContent, /目标使用者：`【用户确认】 运营人员`/);
    assert.match(profileContent, /项目覆盖对象：`【用户确认】 内网工具`/);
    assert.match(profileContent, /当前页面主要给谁用：`【用户确认】 值班主管`/);
    assert.match(profileContent, /核心功能 1：`【用户确认】 工单流转`/);
    assert.match(profileContent, /核心功能 2：`【用户确认】 权限配置`/);
    assert.match(profileContent, /核心功能 3：`【用户确认】 数据看板`/);
    assert.match(profileContent, /已有文档：`【系统推断】/);
    assert.doesNotMatch(profileContent, /项目名称：`【系统推断】 new-package-name`/);
    assert.equal(result.profile.next_questions.length, 1);
    assert.equal(result.profile.next_questions[0].field, 'project_name');
    assert.deepEqual(
        result.profile.conflicts.map((item) => item.field),
        ['project_name', 'project_one_liner']
    );
});

test('route-check uses baseline audit JSON to route maintenance-doc gaps only to document skills', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S0.5',
            recommended_stage: 'S0.5',
            current_round_deliverable: '既有项目关键文件诊断清单',
            largest_uncertainty: 'BRD 缺失'
        },
        planOverrides: {
            current_stage: 'S0.5',
            current_goal: '补齐既有项目维护知识底座',
            next_tasks: '读取 baseline-audit 后补 BRD'
        },
        logContent: '记录 S0.5 既有项目基线诊断'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeJsonFile(path.join(hostRoot, 'docs', 'baseline', 'baseline-audit-demo.json'), {
        mode: 'existing-project-baseline',
        scope: 'maintenance-docs-only',
        slug: 'demo',
        summary: {
            status: 'missing_required_artifacts',
            recommended_next_skill: 'brd-writer'
        },
        artifacts: [
            {
                type: 'BRD',
                status: 'missing',
                recommended_skill: 'brd-writer'
            },
            {
                type: 'FOUNDATION',
                status: 'missing',
                recommended_skill: 'foundation-builder'
            }
        ]
    });

    const result = routeCheck({ hostRoot });

    assert.equal(result.routeTarget.skill, 'brd-writer');
    assert.equal(result.context.baselineAudit.recommendedNextSkill, 'brd-writer');
    assert.equal(result.context.baselineAudit.scope, 'maintenance-docs-only');
    assert.equal(JSON.stringify(result.context.baselineAudit).includes('delivery-planner'), false);
    assert.equal(JSON.stringify(result.context.baselineAudit).includes('test-case'), false);
    assert.match(result.nextAction, /baseline-audit/);
});

test('route-check refreshes stale baseline when recommended BRD gap is already filled', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S0.5',
            recommended_stage: 'S0.5',
            current_round_deliverable: '既有项目关键文件诊断清单',
            largest_uncertainty: 'BRD 缺失'
        },
        planOverrides: {
            current_stage: 'S0.5',
            current_goal: '补齐既有项目维护知识底座',
            next_tasks: '读取 baseline-audit 后补 BRD'
        },
        logContent: '记录 S0.5 既有项目基线诊断'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeJsonFile(path.join(hostRoot, 'docs', 'baseline', 'baseline-audit-demo.json'), {
        mode: 'existing-project-baseline',
        scope: 'maintenance-docs-only',
        slug: 'demo',
        summary: {
            status: 'missing_required_artifacts',
            recommended_next_skill: 'brd-writer'
        },
        artifacts: [
            {
                type: 'BRD',
                status: 'missing',
                recommended_skill: 'brd-writer'
            }
        ]
    });
    writeFile(path.join(hostRoot, 'docs', 'brd', 'BRD-demo-20260601-1000.md'), '# BRD Demo\n');

    const result = routeCheck({ hostRoot });

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'project-baseline-auditor');
    assert.equal(result.routeTarget.source, 'baseline-refresh');
    assert.equal(result.context.baselineAudit.status, 'missing_required_artifacts');
    assert.match(result.nextAction, /刷新 baseline/);
    assert.doesNotMatch(result.nextAction, /交由 brd-writer/);
});

test('route-check refreshes stale baseline when recommended foundation gap is already filled', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S0.5',
            recommended_stage: 'S0.5',
            current_round_deliverable: '既有项目关键文件诊断清单',
            largest_uncertainty: 'foundation 缺失'
        },
        planOverrides: {
            current_stage: 'S0.5',
            current_goal: '补齐既有项目维护知识底座',
            next_tasks: '读取 baseline-audit 后补 foundation'
        },
        logContent: '记录 S0.5 既有项目基线诊断'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeJsonFile(path.join(hostRoot, 'docs', 'baseline', 'baseline-audit-demo.json'), {
        mode: 'existing-project-baseline',
        scope: 'maintenance-docs-only',
        slug: 'demo',
        summary: {
            status: 'missing_required_artifacts',
            recommended_next_skill: 'foundation-builder'
        },
        artifacts: [
            {
                type: 'FOUNDATION',
                status: 'missing',
                recommended_skill: 'foundation-builder'
            }
        ]
    });
    writeFoundationArtifacts(hostRoot);

    const result = routeCheck({ hostRoot });

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'project-baseline-auditor');
    assert.equal(result.routeTarget.source, 'baseline-refresh');
    assert.match(result.nextAction, /刷新 baseline/);
    assert.doesNotMatch(result.nextAction, /交由 foundation-builder/);
});

test('route-check accepts completed baseline audit as S0.5 completion state', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S0.5',
            recommended_stage: 'S0.5',
            current_round_deliverable: '既有项目关键文件诊断清单',
            largest_uncertainty: '无'
        },
        planOverrides: {
            current_stage: 'S0.5',
            current_goal: '补齐既有项目维护知识底座',
            next_tasks: '主入口重新判断下一阶段'
        },
        logContent: '记录 S0.5 既有项目基线诊断'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeJsonFile(path.join(hostRoot, 'docs', 'baseline', 'baseline-audit-demo.json'), {
        mode: 'existing-project-baseline',
        scope: 'maintenance-docs-only',
        slug: 'demo',
        summary: {
            status: 'ready',
            recommended_next_skill: null
        },
        artifacts: []
    });

    const result = routeCheck({ hostRoot });

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'ai-project-manager');
    assert.equal(result.routeTarget.source, 'baseline-complete');
    assert.equal(result.context.baselineAudit.status, 'ready');
    assert.equal(result.blockingReasons.some((item) => item.code === 'baseline_audit_missing'), false);
    assert.match(result.nextAction, /维护知识底座已补齐/);
});

test('collect-project-links compiles host artifacts into a rebuildable file-level graph', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S3',
            recommended_stage: 'S3',
            current_round_deliverable: '开发执行计划',
            largest_uncertainty: '文件引用关系待建立'
        },
        planOverrides: {
            current_stage: 'S3',
            current_goal: '建立文件级引用关系',
            next_tasks: '运行 project-link-indexer'
        }
    });

    writeFile(
        path.join(hostRoot, 'docs', 'brd', 'BRD-demo-20260601-1000.md'),
        '# BRD Demo\n\n- 下游 PRD：[mainprd](../prd/mainprd-demo.md)\n'
    );
    writeFile(
        path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-delivery-demo.md'),
        '# 页面交付清单\n\n- 上游 BRD：[BRD](../../../docs/brd/BRD-demo-20260601-1000.md)\n'
    );
    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'foundation-delivery-demo.md'),
        '# Foundation 交付清单\n\n- 页面说明：[[src/frontend/page-preview/explainer-delivery-demo.md|页面交付清单]]\n'
    );
    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'),
        '# mainprd\n\n| subprd | 链接 |\n|---|---|\n| 订单 | [订单](subprd/01-subprd-order.md) |\n'
    );
    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'subprd', '01-subprd-order.md'),
        '# 订单 subprd\n\n- mainprd回链：[mainprd-demo.md](../mainprd-demo.md)\n'
    );
    writeMultiFileDeliveryPlan(hostRoot);

    const result = collectProjectLinks({ hostRoot, write: true });
    const nodeByPath = new Map(result.nodes.map((item) => [item.path, item]));

    assert.equal(result.mode, 'project-link-index');
    assert.equal(result.outputs.graphJson, 'docs/index/project-link-graph.json');
    assert.equal(result.outputs.graphMarkdown, 'docs/index/project-link-graph.md');
    assert.equal(result.outputs.wikiSchemaJson, 'docs/index/project-wiki-schema.json');
    assert.equal(result.hostRoot, '.');
    assert.equal(fs.existsSync(path.join(hostRoot, result.outputs.graphJson)), true);
    assert.equal(fs.existsSync(path.join(hostRoot, result.outputs.graphMarkdown)), true);
    assert.equal(fs.existsSync(path.join(hostRoot, result.outputs.wikiSchemaJson)), true);
    assert.equal(readFile(path.join(hostRoot, result.outputs.graphJson)).includes(hostRoot), false);
    assert.equal(nodeByPath.get('docs/prd/mainprd-demo.md').kind, 'mainprd');
    assert.equal(nodeByPath.get('docs/plans/delivery-plans/main-delivery-plan-demo.md').kind, 'delivery_plan');
    assert.equal(nodeByPath.get('docs/plans/delivery-plans/sub-delivery-plan-demo-T0.1-demo-task.md').kind, 'delivery_plan');
    assert.equal(nodeByPath.get('docs/plans/delivery-plans/task-kanban-demo.md').kind, 'delivery_plan');
    assert.ok(
        result.edges.some(
            (edge) =>
                edge.relation === 'indexes' &&
                edge.from === 'docs/prd/mainprd-demo.md' &&
                edge.to === 'docs/prd/subprd/01-subprd-order.md'
        )
    );
    assert.ok(
        result.edges.some(
            (edge) =>
                edge.relation === 'depends_on' &&
                edge.from === 'docs/plans/delivery-plans/sub-delivery-plan-demo-T0.1-demo-task.md' &&
                edge.to === 'docs/prd/mainprd-demo.md' &&
                edge.evidence.some((item) => item.syntax === 'prd_double_link')
        )
    );
    assert.equal(result.issues.some((item) => item.code === 'missing_reverse_link'), false);
});

test('validate-project-links reports broken links and missing reverse links without stage routing advice', () => {
    const hostRoot = createHostFixture();

    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'),
        '# mainprd\n\n| subprd | 链接 |\n|---|---|\n| 订单 | [订单](subprd/01-subprd-order.md) |\n| 缺失 | [缺失](missing-doc.md) |\n'
    );
    writeFile(path.join(hostRoot, 'docs', 'prd', 'subprd', '01-subprd-order.md'), '# 订单 subprd\n\n- 暂无mainprd回链\n');

    const result = validateProjectLinks({ hostRoot });
    const codes = result.issues.map((item) => item.code);
    const serializedIssues = JSON.stringify(result.issues);

    assert.equal(result.valid, false);
    assert.ok(codes.includes('broken_link'));
    assert.ok(codes.includes('missing_reverse_link'));
    assert.equal(serializedIssues.includes('delivery-planner'), false);
    assert.equal(serializedIssues.includes('test-case'), false);
});

test('project-link-indexer ignores source-code string fixtures and unresolved placeholder backticks', () => {
    const hostRoot = createHostFixture();

    writeFile(
        path.join(hostRoot, 'README.md'),
        '# Demo\n\n- 模板路径：`0X-subprd-<区块英文短名>.md`\n- 通配路径：`docs/prd/*.md`\n'
    );
    writeFile(
        path.join(hostRoot, 'src', 'fixture.js'),
        'const sample = "# Doc\\n\\n[missing](missing-from-code.md)\\n";\n'
    );

    const result = validateProjectLinks({ hostRoot });
    const targets = result.issues.map((item) => item.target || '');

    assert.equal(targets.some((item) => item.includes('missing-from-code.md')), false);
    assert.equal(targets.some((item) => item.includes('0X-subprd-<区块英文短名>.md')), false);
    assert.equal(targets.some((item) => item.includes('docs/prd/*.md')), false);
});

test('project-link-indexer ignores dependency and generated directories at any depth', () => {
    const hostRoot = createHostFixture();

    writeFile(
        path.join(hostRoot, 'word-format-checker-web', 'node_modules', 'dayjs', 'README.md'),
        '# dayjs\n\n[missing dependency doc](docs/missing.md)\n'
    );
    writeFile(
        path.join(hostRoot, 'word-format-checker-web', 'dist', 'index.html'),
        '<a href="missing-generated.html">generated</a>\n'
    );
    writeFile(
        path.join(hostRoot, 'word-format-checker-web', 'src', 'App.vue'),
        '<template><main>real source</main></template>\n'
    );
    writeFile(path.join(hostRoot, '.pytest_cache', 'README.md'), '# pytest cache\n');
    writeFile(path.join(hostRoot, 'src', '__pycache__', 'config.cpython-312.pyc'), 'compiled cache\n');

    const result = collectProjectLinks({ hostRoot, write: false });
    const nodePaths = result.nodes.map((item) => item.path);
    const issueSources = result.issues.map((item) => item.from || item.evidence?.path || '');

    assert.equal(nodePaths.some((item) => item.includes('/node_modules/')), false);
    assert.equal(nodePaths.some((item) => item.includes('/dist/')), false);
    assert.equal(nodePaths.some((item) => item.includes('.pytest_cache')), false);
    assert.equal(nodePaths.some((item) => item.includes('__pycache__')), false);
    assert.equal(issueSources.some((item) => item.includes('/node_modules/')), false);
    assert.equal(issueSources.some((item) => item.includes('/dist/')), false);
    assert.ok(nodePaths.includes('word-format-checker-web/src/App.vue'));
});

test('project-link-indexer is registered as a global companion ability and file role', () => {
    assert.ok(globalCompanionAbilities.some((item) => item.skill === 'project-link-indexer'));
    assert.ok(
        fileRoles.some(
            (item) =>
                item.id === 'project_link_index' &&
                item.defaultPath === 'docs/index/project-link-graph.json' &&
                item.writtenBy.includes('project-link-indexer')
        )
    );
});

test('run-project-link-indexer builds index when key artifacts exist and no index is present', () => {
    const hostRoot = createHostFixture();
    writeFile(path.join(hostRoot, 'docs', 'brd', 'BRD-demo-20260601-1000.md'), '# BRD Demo\n');

    const result = runProjectLinkIndexer({ hostRoot, trigger: 'artifact_files_added_or_split' });

    assert.equal(result.mode, 'build');
    assert.equal(fs.existsSync(path.join(hostRoot, 'docs', 'index', 'project-link-graph.json')), true);
    assert.equal(result.outputs.graphJson, 'docs/index/project-link-graph.json');
    assert.ok(result.summary.nodes > 0);
});

test('run-project-link-indexer refreshes index when current key artifact nodes are missing', () => {
    const hostRoot = createHostFixture();
    writeFile(path.join(hostRoot, 'docs', 'brd', 'BRD-demo-20260601-1000.md'), '# BRD Demo\n');
    collectProjectLinks({ hostRoot, write: true });
    writeMultiFileDeliveryPlan(hostRoot);

    const result = runProjectLinkIndexer({ hostRoot, trigger: 'artifact_files_added_or_split' });
    const graph = JSON.parse(readFile(path.join(hostRoot, 'docs', 'index', 'project-link-graph.json')));
    const nodePaths = graph.nodes.map((item) => item.path);

    assert.equal(result.mode, 'refresh');
    assert.ok(nodePaths.includes('docs/plans/delivery-plans/main-delivery-plan-demo.md'));
    assert.ok(nodePaths.includes('docs/plans/delivery-plans/task-kanban-demo.md'));
});

test('run-project-link-indexer does nothing when index already covers current key artifacts', () => {
    const hostRoot = createHostFixture();
    writeFile(path.join(hostRoot, 'docs', 'brd', 'BRD-demo-20260601-1000.md'), '# BRD Demo\n');
    collectProjectLinks({ hostRoot, write: true });

    const result = runProjectLinkIndexer({ hostRoot, trigger: 'artifact_files_added_or_split' });

    assert.equal(result.mode, 'noop');
    assert.equal(result.outputs.graphJson, 'docs/index/project-link-graph.json');
    assert.ok(result.summary.nodes > 0);
});

test('run-project-link-indexer validates links without writing on diagnostic trigger', () => {
    const hostRoot = createHostFixture();
    writeFile(path.join(hostRoot, 'docs', 'brd', 'BRD-demo-20260601-1000.md'), '# BRD Demo\n\n- 缺失链接：[missing](missing.md)\n');

    const result = runProjectLinkIndexer({ hostRoot, trigger: 'need_broken_link_or_reverse_link_check' });

    assert.equal(result.mode, 'validate-only');
    assert.equal(fs.existsSync(path.join(hostRoot, 'docs', 'index', 'project-link-graph.json')), false);
    assert.ok(result.issues.some((item) => item.code === 'broken_link'));
});

test('route-check asks ai-project-manager to call project-link-indexer after BRD completion', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S1',
            recommended_stage: 'S2',
            current_round_deliverable: 'BRD 已完成'
        },
        planOverrides: {
            current_stage: 'S1',
            current_goal: '进入页面阶段'
        },
        logContent: '记录 S2 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFile(path.join(hostRoot, 'docs', 'brd', 'BRD-demo-20260601-1000.md'), '# BRD Demo\n');
    writeFile(path.join(hostRoot, 'docs', 'index', 'project-link-graph.json'), '{not json');

    const result = routeCheck({ hostRoot, targetStage: 'S2' });
    const linkAction = result.companionActions.find((item) => item.skill === 'project-link-indexer');

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'page-chief');
    assert.equal(result.blockingReasons.length, 0);
    assert.equal(linkAction.trigger, 'artifact_files_added_or_split');
    assert.match(linkAction.reason, /BRD/);
    assert.equal(Object.hasOwn(linkAction, 'mode'), false);
});

test('route-check asks ai-project-manager to call project-link-indexer after delivery plan is ready', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S3',
            recommended_stage: 'S4',
            current_round_deliverable: '开发计划已完成'
        },
        planOverrides: {
            current_stage: 'S3',
            current_goal: '进入开发执行'
        },
        logContent: '记录 S4 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeMultiFileDeliveryPlan(hostRoot);
    writeFile(path.join(hostRoot, 'docs', 'index', 'project-link-graph.json'), '{not json');

    const result = routeCheck({ hostRoot, targetStage: 'S4' });
    const linkAction = result.companionActions.find((item) => item.skill === 'project-link-indexer');

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'coding-standards');
    assert.equal(result.blockingReasons.length, 0);
    assert.equal(linkAction.trigger, 'artifact_files_added_or_split');
    assert.match(linkAction.reason, /开发计划/);
    assert.equal(Object.hasOwn(linkAction, 'mode'), false);
});

test('route-check prefers docs/brd and src/frontend/page-preview over legacy page directories and root-level artifacts', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S2',
            recommended_stage: 'S2',
            current_round_deliverable: '页面代码 / 页面交付清单 + 待确认项',
            largest_uncertainty: '页面环节待收口'
        },
        planOverrides: {
            current_stage: 'S2',
            current_goal: '完成页面环节收口',
            next_tasks: '进入 PRD 环节'
        },
        logContent: '记录 S2 阶段推进与页面环节收口'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });

    writeFile(
        path.join(hostRoot, 'docs', 'brd', 'BRD-demo-20260408-1000.md'),
        '# BRD\n\n- 页面方向已确认：是\n'
    );
    writeFile(
        path.join(hostRoot, 'src', 'frontend', 'page-preview', 'page-delivery-demo.md'),
        '# 页面交付清单\n\n| 页面 | 文件路径 |\n|---|---|\n| 首页 | demo-app/src/pages/home.vue |\n'
    );
    writeFile(path.join(hostRoot, 'demo-app', 'src', 'pages', 'home.vue'), '<template>home</template>\n');
    writeFile(path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-flow-demo.md'), '# flow\n');
    writeFile(
        path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-b-interaction-demo.md'),
        '| id | status |\n|---|---|\n| demo.home.button.1 | locked |\n'
    );
    writeFile(path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-delivery-demo.md'), '# delivery\n');
    writeFile(path.join(hostRoot, '可操作页面', 'page-delivery-demo.md'), '# 旧目录页面交付清单\n');

    writeFile(
        path.join(hostRoot, 'BRD-legacy-20260409-1200.md'),
        '# Legacy BRD\n'
    );
    writeFile(
        path.join(hostRoot, 'page-delivery-legacy.md'),
        '# 旧页面交付清单\n\n| 页面 | 文件路径 |\n|---|---|\n| 首页 | legacy/missing.vue |\n'
    );

    const result = routeCheck({ hostRoot, targetStage: 'S2' });

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'prd-chief');
    assert.equal(result.gateChecks.pageStageClosedForPrd.pass, true);
    assert.equal(result.gateChecks.pageStageClosedForPrd.evidence.brdPath, 'docs/brd/BRD-demo-20260408-1000.md');
    assert.equal(result.gateChecks.pageStageClosedForPrd.evidence.pageDeliveryPath, 'src/frontend/page-preview/page-delivery-demo.md');
});

test('route-check blocks S2 page work when BRD authority is missing', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S1',
            recommended_stage: 'S2',
            current_round_deliverable: '页面代码 / 页面交付清单'
        },
        planOverrides: {
            current_stage: 'S1',
            current_goal: '进入页面设计阶段',
            next_tasks: '调用 page-chief'
        },
        logContent: '记录 S2 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });

    const result = routeCheck({ hostRoot, targetStage: 'S2' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.brdReadyForPage.pass, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'brd_missing'));
});

test('route-check enters S7 when release signal and test execution reports are ready', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S6',
            recommended_stage: 'S7',
            current_round_deliverable: '安全扫描报告 + PASS / BLOCK / WAIVER 结论',
            largest_uncertainty: '完工前安全闸门待执行'
        },
        planOverrides: {
            current_stage: 'S6',
            current_goal: '完成最终安全检查并准备完工',
            next_tasks: '触发 security-scan'
        },
        logContent: '记录 S7 阶段切换与完工前安全扫描准备'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'reports', 'index.md'), '# 测试执行报告');
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'reports', '测试验收-核心流程.md'), '# 核心流程测试报告');

    const result = routeCheck({ hostRoot, targetStage: 'S7' });

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'security-scan');
    assert.equal(result.gateChecks.securityScanReady.pass, true);
});

test('route-check blocks S5 when PRD or verifiable build evidence is missing', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S4',
            recommended_stage: 'S5',
            current_round_deliverable: '验收文档 + 测试用例'
        },
        planOverrides: {
            current_stage: 'S4',
            current_goal: '准备生成测试用例'
        },
        logContent: '记录 S5 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });

    const result = routeCheck({ hostRoot, targetStage: 'S5' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.fullPrdReady.pass, false);
    assert.equal(result.gateChecks.buildAvailableForValidation.pass, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'full_prd_missing'));
    assert.ok(result.blockingReasons.some((item) => item.code === 'build_available_for_validation_missing'));
});

test('route-check enters S5 when full PRD and verifiable build evidence exist', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S4',
            recommended_stage: 'S5',
            current_round_deliverable: '验收文档 + 测试用例'
        },
        planOverrides: {
            current_stage: 'S4',
            current_goal: '开发完成，当前版本已具备可验证基础',
            next_tasks: '调用 test-case-chief'
        },
        logContent: '记录 S5 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFullPrdArtifacts(hostRoot);

    const result = routeCheck({ hostRoot, targetStage: 'S5' });

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'test-case-chief');
    assert.equal(result.gateChecks.fullPrdReady.pass, true);
    assert.equal(result.gateChecks.buildAvailableForValidation.pass, true);
});

test('route-check blocks S3 when foundation artifacts are missing', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S2',
            recommended_stage: 'S3',
            current_round_deliverable: '开发执行计划'
        },
        planOverrides: {
            current_stage: 'S2',
            current_goal: '准备进入开发计划阶段',
            next_tasks: '调用 delivery-planner'
        },
        logContent: '记录 S3 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFullPrdArtifacts(hostRoot);

    const result = routeCheck({ hostRoot, targetStage: 'S3' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.foundationReadyForDevelopmentPlan.pass, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'foundation_missing'));
});

test('route-check blocks S3 until every feature-list subprd is confirmed and exists', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S2',
            recommended_stage: 'S3',
            current_round_deliverable: '开发执行计划'
        },
        planOverrides: {
            current_stage: 'S2',
            current_goal: '准备进入开发计划阶段',
            next_tasks: '调用 delivery-planner'
        },
        logContent: '记录 S3 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFoundationArtifacts(hostRoot);
    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'prd-feature-list-demo.md'),
        `# 功能列表

## 功能总表

| # | 页面 | 区块 | 功能说明 | subprd文件 | 状态 |
|---|---|---|---|---|---|
| 1 | 操作页 | 核心操作 | 处理核心流程 | [01-subprd-core.md](subprd/01-subprd-core.md) | 已确认 |
| 2 | 操作页 | 重置开始 | 重新开始审核流程 | [02-subprd-reset.md](subprd/02-subprd-reset.md) | 待确认 |
`
    );
    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'),
        `# mainprd

## subprd索引

| # | 区块 | 所属页面 | subprd文件 | 状态 |
|---|---|---|---|---|
| 1 | 核心操作 | 操作页 | [01-subprd-core.md](subprd/01-subprd-core.md) | 已确认 |
| 2 | 重置开始 | 操作页 | [02-subprd-reset.md](subprd/02-subprd-reset.md) | 待确认 |
`
    );
    writeFile(path.join(hostRoot, 'docs', 'prd', 'subprd', '01-subprd-core.md'), '# 核心操作 subprd\n');

    const result = routeCheck({ hostRoot, targetStage: 'S3' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.foundationReadyForDevelopmentPlan.pass, true);
    assert.equal(result.gateChecks.fullPrdReady.pass, false);
    assert.equal(result.gateChecks.fullPrdReady.evidence.featureListItemCount, 2);
    assert.equal(result.gateChecks.fullPrdReady.evidence.mainprdIndexCount, 2);
    assert.equal(result.gateChecks.fullPrdReady.evidence.subprdCount, 1);
    assert.deepEqual(result.gateChecks.fullPrdReady.evidence.missingSubprd, ['docs/prd/subprd/02-subprd-reset.md']);
    assert.ok(result.blockingReasons.some((item) => item.code === 'full_prd_missing'));
    assert.match(result.nextAction, /停留 S2/);
    assert.doesNotMatch(result.nextAction, /可进入 S3/);
});

test('route-check rejects root-level subprd because specs must live under docs/prd/subprd', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S2',
            recommended_stage: 'S3',
            current_round_deliverable: '开发执行计划'
        },
        planOverrides: {
            current_stage: 'S2',
            current_goal: '准备进入开发计划阶段',
            next_tasks: '调用 delivery-planner'
        },
        logContent: '记录 S3 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFoundationArtifacts(hostRoot);
    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'prd-feature-list-demo.md'),
        `# 功能列表

## 功能总表

| # | 页面 | 区块 | 功能说明 | subprd文件 | 状态 |
|---|---|---|---|---|---|
| 1 | 操作页 | 核心操作 | 处理核心流程 | [01-subprd-core.md](01-subprd-core.md) | 已确认 |
`
    );
    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'),
        `# mainprd

## subprd索引

| # | 区块 | 所属页面 | subprd文件 | 状态 |
|---|---|---|---|---|
| 1 | 核心操作 | 操作页 | [01-subprd-core.md](01-subprd-core.md) | 已确认 |
`
    );
    writeFile(path.join(hostRoot, 'docs', 'prd', '01-subprd-core.md'), '# 核心操作 subprd\n');

    const result = routeCheck({ hostRoot, targetStage: 'S3' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.foundationReadyForDevelopmentPlan.pass, true);
    assert.equal(result.gateChecks.fullPrdReady.pass, false);
    assert.equal(result.gateChecks.fullPrdReady.evidence.subprdPathsValid, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'full_prd_missing'));
});

test('route-check rejects root-level foundation artifacts because foundation must live under docs/prd/foundation', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S2',
            recommended_stage: 'S3',
            current_round_deliverable: '开发执行计划'
        },
        planOverrides: {
            current_stage: 'S2',
            current_goal: '准备进入开发计划阶段',
            next_tasks: '调用 delivery-planner'
        },
        logContent: '记录 S3 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFullPrdArtifacts(hostRoot);
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation-glossary-demo.md'), '# 术语表\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation-schema-demo.md'), '# 数据结构\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation-api-demo.md'), '# 接口草案\n');
    writeFile(
        path.join(hostRoot, 'docs', 'prd', 'foundation-delivery-demo.md'),
        `# Foundation 交付清单

| 产物 | 文件路径 | 说明 |
|---|---|---|
| 术语表 | docs/prd/foundation-glossary-demo.md | 已确认 |
| 数据结构 | docs/prd/foundation-schema-demo.md | 已确认 |
| 接口草案 | docs/prd/foundation-api-demo.md | 已确认 |
`
    );

    const result = routeCheck({ hostRoot, targetStage: 'S3' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.fullPrdReady.pass, true);
    assert.equal(result.gateChecks.foundationReadyForDevelopmentPlan.pass, false);
    assert.equal(result.gateChecks.foundationReadyForDevelopmentPlan.evidence.foundationDeliveryExists, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'foundation_missing'));
});

test('route-check blocks S4 until delivery plan exists', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S3',
            recommended_stage: 'S4',
            current_round_deliverable: '当前任务的执行结果 + 任务状态更新'
        },
        planOverrides: {
            current_stage: 'S3',
            current_goal: '准备进入开发执行',
            in_progress: '整理核心需求'
        },
        logContent: '记录 S4 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });

    const result = routeCheck({ hostRoot, targetStage: 'S4' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.developmentPlanReady.pass, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'development_plan_missing'));
    assert.equal(result.routeTarget.skill, 'delivery-planner');
    assert.equal(result.routeTarget.recoveryFor, 'development_plan_missing');
    assert.match(result.nextAction, /docs\/plans\/delivery-plans/);
    assert.match(result.nextAction, /main-delivery-plan-<slug>\.md/);
    assert.doesNotMatch(result.nextAction, /可进入\s*S4/);
});

test('route-check enters S4 when delivery plan exists', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S3',
            recommended_stage: 'S4',
            current_round_deliverable: '当前任务的执行结果 + 任务状态更新'
        },
        planOverrides: {
            current_stage: 'S3',
            current_goal: '准备进入开发执行'
        },
        logContent: '记录 S4 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeMultiFileDeliveryPlan(hostRoot);

    const result = routeCheck({ hostRoot, targetStage: 'S4' });

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'coding-standards');
    assert.equal(result.gateChecks.developmentPlanReady.pass, true);
    assert.equal(
        result.gateChecks.developmentPlanReady.evidence.deliveryPlanPath,
        'docs/plans/delivery-plans/main-delivery-plan-demo.md'
    );
});

test('route-check blocks S4 when delivery plan status is inconsistent', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S4',
            recommended_stage: 'S4',
            current_round_deliverable: '当前任务的执行结果 + 任务状态更新'
        },
        planOverrides: {
            current_stage: 'S4',
            current_goal: '继续开发执行'
        },
        logContent: '记录 S4 阶段推进'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    const { mainPath } = writeMultiFileDeliveryPlan(hostRoot);
    const driftedMain = readFile(mainPath).replace(
        '`Phase 0 / T0.1 实现演示任务`',
        '`Phase 0 / T0.2 已不存在任务`'
    );
    writeFile(mainPath, driftedMain);

    const result = routeCheck({ hostRoot, targetStage: 'S4' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.developmentPlanReady.pass, false);
    assert.equal(result.gateChecks.developmentPlanReady.evidence.planConsistency.passed, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'development_plan_status_inconsistent'));
    assert.equal(result.routeTarget.skill, 'delivery-planner');
    assert.equal(result.routeTarget.recoveryFor, 'development_plan_status_inconsistent');
    assert.match(result.nextAction, /状态不一致/);
    assert.notEqual(result.routeTarget.skill, 'coding-standards');
});

test('route-check blocks S4 when delivery plan structure is invalid', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S3',
            recommended_stage: 'S4',
            current_round_deliverable: '当前任务的执行结果 + 任务状态更新'
        },
        planOverrides: {
            current_stage: 'S3',
            current_goal: '准备进入开发执行'
        },
        logContent: '记录 S4 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    const { mainPath } = writeMultiFileDeliveryPlan(hostRoot);
    writeFile(mainPath, '# 开发执行计划\n');

    const result = routeCheck({ hostRoot, targetStage: 'S4' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.developmentPlanReady.pass, false);
    assert.equal(result.gateChecks.developmentPlanReady.evidence.structureValid, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'development_plan_invalid'));
    assert.equal(result.routeTarget.skill, 'delivery-planner');
    assert.equal(result.routeTarget.recoveryFor, 'development_plan_invalid');
    assert.match(result.nextAction, /修复/);
    assert.match(result.nextAction, /docs\/plans\/delivery-plans/);
    assert.doesNotMatch(result.nextAction, /可进入\s*S4/);
});

test('route-check blocks S6 until reviewed test cases are ready', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S5',
            recommended_stage: 'S6',
            current_round_deliverable: '测试执行报告'
        },
        planOverrides: {
            current_stage: 'S5',
            current_goal: '准备执行测试'
        },
        logContent: '记录 S6 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'tc-main-demo.md'), '# TC 主索引\n');
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'core', 'tc-core.md'), '# 核心域 TC\n');

    const result = routeCheck({ hostRoot, targetStage: 'S6' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.testCasesReady.pass, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'test_cases_missing'));
});

test('route-check enters S6 when reviewed test cases are ready', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S5',
            recommended_stage: 'S6',
            current_round_deliverable: '测试执行报告'
        },
        planOverrides: {
            current_stage: 'S5',
            current_goal: '准备执行测试'
        },
        logContent: '记录 S6 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'tc-main-demo.md'), '# TC 主索引\n');
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'core', 'tc-core.md'), '# 核心域 TC\n');
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'tc-reviews', '20260522-issues.md'), '# TC 核查\n\n结论 = 已完工\n');

    const result = routeCheck({ hostRoot, targetStage: 'S6' });

    assert.equal(result.canEnter, true);
    assert.equal(result.routeTarget.skill, 'test-case-runner');
    assert.equal(result.gateChecks.testCasesReady.pass, true);
});

test('route-check rejects unfinished review conclusions that contain the word pass', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S5',
            recommended_stage: 'S6',
            current_round_deliverable: '测试执行报告'
        },
        planOverrides: {
            current_stage: 'S5',
            current_goal: '准备执行测试'
        },
        logContent: '记录 S6 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'tc-main-demo.md'), '# TC 主索引\n');
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'core', 'tc-core.md'), '# 核心域 TC\n');
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'tc-reviews', '20260601-issues.md'), '# TC 核查\n\n结论：未通过，需 writer 续改\n');

    const result = routeCheck({ hostRoot, targetStage: 'S6' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.testCasesReady.evidence.latestReviewDone, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'test_cases_missing'));
});

test('route-check chooses suffixed same-day review issue files as the latest review', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S5',
            recommended_stage: 'S6',
            current_round_deliverable: '测试执行报告'
        },
        planOverrides: {
            current_stage: 'S5',
            current_goal: '准备执行测试'
        },
        logContent: '记录 S6 阶段切换'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'tc-main-demo.md'), '# TC 主索引\n');
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'core', 'tc-core.md'), '# 核心域 TC\n');
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'tc-reviews', '20260601-issues.md'), '# TC 核查\n\n结论 = 已完工\n');
    writeFile(path.join(hostRoot, 'docs', 'test-case', 'tc-reviews', '20260601-issues-2.md'), '# TC 核查\n\n结论：需 writer 续改\n');

    const result = routeCheck({ hostRoot, targetStage: 'S6' });

    assert.equal(result.canEnter, false);
    assert.equal(result.gateChecks.testCasesReady.evidence.latestReviewPath, 'docs/test-case/tc-reviews/20260601-issues-2.md');
    assert.equal(result.gateChecks.testCasesReady.evidence.latestReviewDone, false);
});

test('route-check blocks S7 when release gate evidence is missing', () => {
    const hostRoot = createHostFixture({
        profileOverrides: {
            current_stage: 'S6',
            recommended_stage: 'S7',
            current_round_deliverable: '安全扫描报告 + PASS / BLOCK / WAIVER 结论'
        },
        planOverrides: {
            current_stage: 'S6',
            current_goal: '准备完工'
        },
        logContent: '记录 S7 阶段切换与完工前安全扫描准备'
    });
    generateHostRules({ hostRoot, dryRun: false, force: false });

    const result = routeCheck({ hostRoot, targetStage: 'S7' });

    assert.equal(result.canEnter, false);
    assert.ok(result.blockingReasons.some((item) => item.code === 'security_scan_inputs_missing'));
});

test('generate-host-rules syncs default rules into host docs/rules', () => {
    const hostRoot = makeTempDir('pm-suite-rules-');

    const result = generateHostRules({ hostRoot, dryRun: false, force: false });

    assert.ok(result.results.created.length > 0);
    assert.ok(fs.existsSync(path.join(hostRoot, 'docs', 'rules', 'devlog.md')));
    assert.ok(readFile(path.join(hostRoot, 'docs', 'rules', 'devlog.md')).includes('<!-- generated-by: ai-project-manager -->'));
});

test('install-suite-into-host creates host .agent directory when it does not exist', () => {
    const hostRoot = makeTempDir('pm-suite-install-host-');

    const result = installSuiteIntoHost({
        hostRoot,
        force: false,
        move: false,
        dryRun: false,
        json: false
    });

    const targetSuiteRoot = path.join(hostRoot, '.agent', 'project-manager-suite');
    const manifestPath = path.join(targetSuiteRoot, '.install-manifest.json');
    const lockPath = path.join(hostRoot, '.agent', 'project-manager-suite.lock.json');
    const packageMetadata = JSON.parse(readFile(path.join(CURRENT_SUITE_ROOT, 'package.json')));

    assert.equal(result.installMode, 'install');
    assert.equal(packageMetadata.version, '2.0.0');
    assert.ok(fs.existsSync(path.join(hostRoot, '.agent')));
    assert.ok(fs.existsSync(path.join(targetSuiteRoot, 'tools', 'bootstrap-host.mjs')));
    assert.ok(fs.existsSync(path.join(targetSuiteRoot, 'skills', '00-01-ai-project-manager', 'SKILL.md')));
    assert.ok(fs.existsSync(manifestPath));
    assert.ok(fs.existsSync(lockPath));

    const manifest = JSON.parse(readFile(manifestPath));
    const lock = JSON.parse(readFile(lockPath));

    assert.equal(manifest.install_mode, 'install');
    assert.equal(manifest.suite_name, 'project-manager-suite');
    assert.equal(manifest.suite_version, '2.0.0');
    assert.equal(manifest.target_path, '.agent/project-manager-suite');
    assert.equal(manifest.content_hash_algorithm, 'sha256-path-null-lf-v1');
    assert.match(manifest.content_sha256, /^[a-f0-9]{64}$/);
    assert.equal(manifest.generated_by, 'tools/install-suite-into-host.mjs');
    assert.equal(manifest.source_suite_root, undefined);
    assert.equal(manifest.target_suite_root, undefined);
    assert.ok(manifest.installed_files.every((filePath) => !path.isAbsolute(filePath)));
    assert.ok(!JSON.stringify(manifest).includes(hostRoot));
    assert.ok(!JSON.stringify(manifest).includes(CURRENT_SUITE_ROOT));

    assert.equal(lock.suite_name, manifest.suite_name);
    assert.equal(lock.suite_version, manifest.suite_version);
    assert.equal(lock.target_path, manifest.target_path);
    assert.equal(lock.content_hash_algorithm, manifest.content_hash_algorithm);
    assert.equal(lock.content_sha256, manifest.content_sha256);
    assert.equal(lock.generated_by, manifest.generated_by);
    assert.ok(!JSON.stringify(lock).includes(hostRoot));
    assert.ok(!JSON.stringify(lock).includes(CURRENT_SUITE_ROOT));
});

test('verify-suite-lock accepts an intact install and rejects content drift', () => {
    const hostRoot = makeTempDir('pm-suite-lock-host-');
    const verifierPath = path.join(CURRENT_SUITE_ROOT, 'tools', 'verify-suite-lock.mjs');

    installSuiteIntoHost({
        hostRoot,
        force: false,
        move: false,
        dryRun: false,
        json: false
    });

    const validResult = spawnSync(process.execPath, [verifierPath, hostRoot, '--json'], {
        encoding: 'utf8'
    });

    assert.equal(validResult.status, 0, validResult.stderr);
    assert.equal(JSON.parse(validResult.stdout).status, 'valid');

    const installedReadmePath = path.join(hostRoot, '.agent', 'project-manager-suite', 'README.md');
    const installedReadme = readFile(installedReadmePath);
    fs.writeFileSync(installedReadmePath, installedReadme.replace(/\r?\n/g, '\r\n'), 'utf8');

    const newlineOnlyResult = spawnSync(process.execPath, [verifierPath, hostRoot, '--json'], {
        encoding: 'utf8'
    });

    assert.equal(newlineOnlyResult.status, 0, newlineOnlyResult.stderr);
    assert.equal(JSON.parse(newlineOnlyResult.stdout).status, 'valid');

    fs.appendFileSync(
        installedReadmePath,
        '\ncontent drift\n',
        'utf8'
    );

    const driftResult = spawnSync(process.execPath, [verifierPath, hostRoot, '--json'], {
        encoding: 'utf8'
    });

    assert.equal(driftResult.status, 1);
    assert.equal(JSON.parse(driftResult.stdout).status, 'content_mismatch');
});

test('verify-suite-lock rejects manifest metadata and installed file list drift', () => {
    const hostRoot = makeTempDir('pm-suite-manifest-lock-host-');
    const verifierPath = path.join(CURRENT_SUITE_ROOT, 'tools', 'verify-suite-lock.mjs');

    installSuiteIntoHost({
        hostRoot,
        force: false,
        move: false,
        dryRun: false,
        json: false
    });

    const manifestPath = path.join(hostRoot, '.agent', 'project-manager-suite', '.install-manifest.json');
    const manifest = JSON.parse(readFile(manifestPath));
    manifest.suite_version = '9.9.9';
    writeJsonFile(manifestPath, manifest);

    const metadataDriftResult = spawnSync(process.execPath, [verifierPath, hostRoot, '--json'], {
        encoding: 'utf8'
    });

    assert.equal(metadataDriftResult.status, 1);
    assert.equal(JSON.parse(metadataDriftResult.stdout).status, 'manifest_mismatch');

    manifest.suite_version = '2.0.0';
    manifest.installed_files = manifest.installed_files.slice(1);
    writeJsonFile(manifestPath, manifest);

    const fileListDriftResult = spawnSync(process.execPath, [verifierPath, hostRoot, '--json'], {
        encoding: 'utf8'
    });

    assert.equal(fileListDriftResult.status, 1);
    assert.equal(JSON.parse(fileListDriftResult.stdout).status, 'manifest_file_list_mismatch');
});

test('install-suite-into-host reuses existing .agent directory without touching other host assets', () => {
    const hostRoot = makeTempDir('pm-suite-install-existing-agent-');
    const existingAgentFile = path.join(hostRoot, '.agent', 'custom-plugin.txt');

    writeFile(existingAgentFile, 'keep me');

    const result = installSuiteIntoHost({
        hostRoot,
        force: false,
        move: false,
        dryRun: false,
        json: false
    });

    const targetSuiteRoot = path.join(hostRoot, '.agent', 'project-manager-suite');

    assert.ok(result.directories.reused.includes(path.join(hostRoot, '.agent')));
    assert.ok(fs.existsSync(existingAgentFile));
    assert.equal(readFile(existingAgentFile), 'keep me');
    assert.ok(fs.existsSync(path.join(targetSuiteRoot, 'tools', 'install-suite-into-host.mjs')));
    assert.ok(fs.existsSync(path.join(targetSuiteRoot, '.install-manifest.json')));
});

test('install-suite-into-host upgrades an existing host-installed suite in place', () => {
    const hostRoot = makeTempDir('pm-suite-install-upgrade-');

    const firstResult = installSuiteIntoHost({
        hostRoot,
        force: false,
        move: false,
        dryRun: false,
        json: false
    });

    const secondResult = installSuiteIntoHost({
        hostRoot,
        force: false,
        move: false,
        dryRun: false,
        json: false
    });

    const manifestPath = path.join(hostRoot, '.agent', 'project-manager-suite', '.install-manifest.json');

    assert.equal(firstResult.installMode, 'install');
    assert.equal(secondResult.installMode, 'upgrade');
    assert.equal(JSON.parse(readFile(manifestPath)).install_mode, 'upgrade');
    assert.ok(secondResult.files.overwritten.length > 0);
});

test('bootstrap-host initializes container root and creates safe scaffold', () => {
    const workspaceRoot = makeTempDir('pm-suite-workspace-');
    const interviewJsonPath = path.join(workspaceRoot, 'interview.json');

    writeJsonFile(interviewJsonPath, buildStartupInterview());

    const result = bootstrapHost({
        hostRoot: workspaceRoot,
        projectName: '演示项目',
        targetStage: '',
        containerRoot: true,
        dryRun: false,
        json: false,
        forceRules: false,
        interviewComplete: true,
        interviewJsonPath,
        createProfileFile: false,
        createRulesFile: true,
        createPlanFile: false
    });

    const effectiveRoot = path.join(workspaceRoot, '演示项目');
    assert.equal(result.rootResolution.rootMode, 'container');
    assert.ok(fs.existsSync(path.join(effectiveRoot, 'docs', 'rules')));
    assert.ok(fs.existsSync(path.join(effectiveRoot, 'docs', 'plans', 'execution-plan.md')));
    assert.ok(fs.existsSync(path.join(effectiveRoot, '.agent', 'skills')));
    assert.ok(fs.existsSync(path.join(effectiveRoot, 'project-rules.md')));
    assert.ok(result.files.deferred.some((item) => item.reason === 'profile_creation_not_requested'));
});

test('bootstrap-host reuses current directory when it already matches the interview project name', () => {
    const workspaceRoot = makeTempDir('pm-suite-project-root-reuse-');
    const projectRoot = path.join(workspaceRoot, '演示项目');
    const interviewJsonPath = path.join(workspaceRoot, 'interview.json');

    fs.mkdirSync(projectRoot, { recursive: true });
    writeJsonFile(interviewJsonPath, buildStartupInterview());

    const result = bootstrapHost({
        hostRoot: projectRoot,
        projectName: '演示项目',
        targetStage: '',
        containerRoot: false,
        dryRun: false,
        json: false,
        forceRules: false,
        interviewComplete: true,
        interviewJsonPath,
        createProfileFile: false,
        createRulesFile: true,
        createPlanFile: false
    });

    assert.equal(result.rootResolution.rootMode, 'project');
    assert.equal(result.rootResolution.effectiveRoot, projectRoot);
    assert.ok(result.rootResolution.detectionEvidence.includes('current_dir_matches_project_name'));
    assert.ok(fs.existsSync(path.join(projectRoot, 'docs', 'rules')));
    assert.ok(fs.existsSync(path.join(projectRoot, 'docs', 'plans', 'execution-plan.md')));
    assert.ok(fs.existsSync(path.join(projectRoot, '.agent', 'skills')));
    assert.equal(fs.existsSync(path.join(projectRoot, '演示项目')), false);
});

test('bootstrap-host refuses to bootstrap a container root before startup interview is complete', () => {
    const workspaceRoot = makeTempDir('pm-suite-bootstrap-container-incomplete-');

    assert.throws(
        () =>
            bootstrapHost({
                hostRoot: workspaceRoot,
                targetStage: '',
                containerRoot: true,
                dryRun: false,
                json: false,
                forceRules: false,
                interviewComplete: false,
                createProfileFile: false,
                createRulesFile: true,
                createPlanFile: false
            }),
        /completed startup interview confirmation/
    );
});

test('bootstrap-host refuses to create project-profile.md with only interview-complete flag', () => {
    const workspaceRoot = makeTempDir('pm-suite-bootstrap-no-interview-');

    assert.throws(
        () =>
            bootstrapHost({
                hostRoot: workspaceRoot,
                projectName: '演示项目',
                targetStage: '',
                containerRoot: true,
                dryRun: false,
                json: false,
                forceRules: false,
                interviewComplete: true,
                createProfileFile: true,
                createRulesFile: false,
                createPlanFile: false
            }),
        /startup minimum interview fields/
    );
});

test('bootstrap-host refuses to create project-profile.md when interview JSON misses startup minimum fields', () => {
    const workspaceRoot = makeTempDir('pm-suite-bootstrap-missing-fields-');
    const interviewJsonPath = path.join(workspaceRoot, 'interview.json');

    writeJsonFile(interviewJsonPath, {
        project_name: '演示项目',
        project_one_liner: '帮助团队稳定推进项目'
    });

    assert.throws(
        () =>
            bootstrapHost({
                hostRoot: workspaceRoot,
                projectName: 'demo-host',
                targetStage: '',
                containerRoot: true,
                dryRun: false,
                json: false,
                forceRules: false,
                interviewComplete: true,
                interviewJsonPath,
                createProfileFile: true,
                createRulesFile: false,
                createPlanFile: false
            }),
        /Interview JSON is missing required startup fields/
    );
});

test('bootstrap-host creates project-profile.md only after receiving complete interview JSON', () => {
    const workspaceRoot = makeTempDir('pm-suite-bootstrap-complete-interview-');
    const interviewJsonPath = path.join(workspaceRoot, 'interview.json');

    writeJsonFile(interviewJsonPath, buildStartupInterview());

    const result = bootstrapHost({
        hostRoot: workspaceRoot,
        projectName: '演示项目',
        targetStage: '',
        containerRoot: true,
        dryRun: false,
        json: false,
        forceRules: false,
        interviewComplete: true,
        interviewJsonPath,
        createProfileFile: true,
        createRulesFile: true,
        createPlanFile: false
    });

    const effectiveRoot = path.join(workspaceRoot, '演示项目');
    const profileContent = readFile(path.join(effectiveRoot, 'project-profile.md'));

    assert.ok(fs.existsSync(path.join(effectiveRoot, 'project-profile.md')));
    assert.ok(result.files.created.includes(path.join(effectiveRoot, 'project-profile.md')));
    assert.ok(profileContent.includes('`【用户确认】` `演示项目`'));
    assert.ok(profileContent.includes('`【用户确认】` `帮助团队稳定推进项目`'));
    assert.ok(profileContent.includes('`【用户确认】` `运营人员`'));
});

test('validate-global-files accepts bootstrap-generated target user label', () => {
    const workspaceRoot = makeTempDir('pm-suite-bootstrap-validate-profile-');
    const interviewJsonPath = path.join(workspaceRoot, 'interview.json');

    writeJsonFile(interviewJsonPath, buildStartupInterview());

    bootstrapHost({
        hostRoot: workspaceRoot,
        projectName: '演示项目',
        targetStage: '',
        containerRoot: true,
        dryRun: false,
        json: false,
        forceRules: false,
        interviewComplete: true,
        interviewJsonPath,
        createProfileFile: true,
        createRulesFile: false,
        createPlanFile: false
    });

    const effectiveRoot = path.join(workspaceRoot, '演示项目');
    const result = validateGlobalFiles({ hostRoot: effectiveRoot });

    assert.ok(
        !result.issues.some(
            (issue) =>
                issue.roleId === 'project_profile' &&
                issue.code === 'missing_required_markers' &&
                issue.missingMarkers?.includes('目标使用者：')
        )
    );
    assert.ok(
        !result.issues.some(
            (issue) =>
                issue.roleId === 'project_profile' &&
                issue.code === 'missing_required_markers' &&
                issue.missingMarkers?.includes('目标用户：')
        )
    );
});

test('bootstrap-host rejects mismatched --project-name and interview project_name in container mode', () => {
    const workspaceRoot = makeTempDir('pm-suite-bootstrap-mismatch-name-');
    const interviewJsonPath = path.join(workspaceRoot, 'interview.json');

    writeJsonFile(interviewJsonPath, buildStartupInterview());

    assert.throws(
        () =>
            bootstrapHost({
                hostRoot: workspaceRoot,
                projectName: 'demo-host',
                targetStage: '',
                containerRoot: true,
                dryRun: false,
                json: false,
                forceRules: false,
                interviewComplete: true,
                interviewJsonPath,
                createProfileFile: false,
                createRulesFile: true,
                createPlanFile: false
            }),
        /must match interview project_name/
    );
});

test('bootstrap-host creates execution-plan.md as part of startup scaffold', () => {
    const workspaceRoot = makeTempDir('pm-suite-bootstrap-plan-default-');
    const interviewJsonPath = path.join(workspaceRoot, 'interview.json');

    writeJsonFile(interviewJsonPath, buildStartupInterview());

    const result = bootstrapHost({
        hostRoot: workspaceRoot,
        projectName: '演示项目',
        targetStage: '',
        containerRoot: true,
        dryRun: false,
        json: false,
        forceRules: false,
        interviewComplete: true,
        interviewJsonPath,
        createProfileFile: false,
        createRulesFile: true,
        createPlanFile: false
    });

    const effectiveRoot = path.join(workspaceRoot, '演示项目');
    assert.ok(fs.existsSync(path.join(effectiveRoot, 'docs', 'plans', 'execution-plan.md')));
    assert.ok(result.files.created.includes(path.join(effectiveRoot, 'docs/plans/execution-plan.md')));
});

test('route-check recognizes startup minimum fields from bootstrap-generated profile template', () => {
    const workspaceRoot = makeTempDir('pm-suite-bootstrap-route-check-');
    const interviewJsonPath = path.join(workspaceRoot, 'interview.json');

    writeJsonFile(interviewJsonPath, buildStartupInterview());

    bootstrapHost({
        hostRoot: workspaceRoot,
        projectName: '演示项目',
        targetStage: '',
        containerRoot: true,
        dryRun: false,
        json: false,
        forceRules: false,
        interviewComplete: true,
        interviewJsonPath,
        createProfileFile: true,
        createRulesFile: true,
        createPlanFile: false
    });

    const result = routeCheck({
        hostRoot: path.join(workspaceRoot, '演示项目')
    });

    assert.equal(result.gateChecks.startupMinimum.pass, true);
    assert.ok(!result.blockingReasons.some((item) => item.code === 'startup_minimum_missing'));
});

test('route-check CLI prints JSON when executed from the current suite path', () => {
    const hostRoot = createHostFixture();
    const routeCheckPath = path.join(CURRENT_SUITE_ROOT, 'tools', 'route-check.mjs');

    const output = execFileSync(process.execPath, [routeCheckPath, hostRoot, '--json'], { encoding: 'utf8' });
    const result = JSON.parse(output);

    assert.equal(result.hostRoot, hostRoot);
    assert.equal(result.gateChecks.startupMinimum.pass, true);
});

test('route-check CLI exits non-zero for blocked JSON checks', () => {
    const hostRoot = createHostFixture({ withProfile: false });
    const routeCheckPath = path.join(CURRENT_SUITE_ROOT, 'tools', 'route-check.mjs');

    const result = spawnSync(process.execPath, [routeCheckPath, hostRoot, '--json'], { encoding: 'utf8' });
    const parsed = JSON.parse(result.stdout);

    assert.notEqual(result.status, 0);
    assert.equal(parsed.canEnter, false);
    assert.ok(parsed.blockingReasons.some((item) => item.code === 'startup_minimum_missing'));
});

test('collect-upstream-context includes page-preview explainer outputs in slim flow', () => {
    const hostRoot = makeTempDir('pm-suite-collect-upstream-');
    const collectPath = path.join(
        CURRENT_SUITE_ROOT,
        'skills',
        '05-01-delivery-planner',
        'scripts',
        'collect-upstream-context.mjs'
    );

    writeFile(path.join(hostRoot, 'docs', 'prd', 'mainprd-ops-tool.md'), '# mainprd\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'subprd', '01-subprd-report.md'), '# 报表区块\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-schema-ops-tool.md'), '# Schema\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-api-ops-tool.md'), '# API\n');
    writeFile(path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-flow-ops-tool.md'), '# 用户流程\n');
    writeFile(
        path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-b-interaction-ops-tool.md'),
        '# 交互语义\n'
    );
    writeFile(path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-delivery-ops-tool.md'), '# 解释交付清单\n');

    const output = execFileSync(process.execPath, [collectPath, hostRoot, '--json'], { encoding: 'utf8' });
    const result = JSON.parse(output);

    assert.equal(result.canProceed, true);
    assert.deepEqual(
        result.explainers.map((item) => item.type).sort(),
        ['b-interaction', 'delivery', 'flow']
    );
    assert.ok(
        result.explainers.every((item) => item.path.includes(path.join('src', 'frontend', 'page-preview')))
    );
});

test('collect-upstream-context reads foundation artifacts from docs/prd/foundation', () => {
    const hostRoot = makeTempDir('pm-suite-collect-foundation-dir-');
    const collectPath = path.join(
        CURRENT_SUITE_ROOT,
        'skills',
        '05-01-delivery-planner',
        'scripts',
        'collect-upstream-context.mjs'
    );

    writeFile(path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'), '# mainprd\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'subprd', '01-subprd-core.md'), '# 核心区块\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-glossary-demo.md'), '# 术语表\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-schema-demo.md'), '# Schema\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-api-demo.md'), '# API\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-delivery-demo.md'), '# Foundation 交付清单\n');

    const output = execFileSync(process.execPath, [collectPath, hostRoot, '--json'], { encoding: 'utf8' });
    const result = JSON.parse(output);

    assert.equal(result.canProceed, true);
    assert.deepEqual(
        result.foundations.map((item) => item.type).sort(),
        ['api', 'delivery', 'glossary', 'schema']
    );
    assert.ok(result.foundations.every((item) => item.path.includes(path.join('docs', 'prd', 'foundation'))));
});

test('collect-upstream-context recognizes numbered subprd files', () => {
    const hostRoot = makeTempDir('pm-suite-collect-numbered-subprd-');
    const collectPath = path.join(
        CURRENT_SUITE_ROOT,
        'skills',
        '05-01-delivery-planner',
        'scripts',
        'collect-upstream-context.mjs'
    );

    writeFile(path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'), '# mainprd\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'subprd', '01-subprd-user-management.md'), '# 用户管理\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-schema-demo.md'), '# Schema\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-api-demo.md'), '# API\n');

    const output = execFileSync(process.execPath, [collectPath, hostRoot, '--json'], { encoding: 'utf8' });
    const result = JSON.parse(output);

    assert.equal(result.canProceed, true);
    assert.equal(result.subprd.length, 1);
    assert.equal(result.subprd[0].block, 'user-management');
    assert.equal(result.subprd[0].order, 1);
    assert.ok(result.subprd[0].path.includes(path.join('docs', 'prd', 'subprd', '01-subprd-user-management.md')));
});

test('validate-plan-structure accepts the multi-file delivery plan structure', () => {
    const hostRoot = makeTempDir('pm-suite-multi-delivery-plan-');
    const { mainPath } = writeMultiFileDeliveryPlan(hostRoot);
    const validatorPath = path.join(
        CURRENT_SUITE_ROOT,
        'skills',
        '05-01-delivery-planner',
        'scripts',
        'validate-plan-structure.mjs'
    );

    const output = execFileSync(process.execPath, [validatorPath, mainPath, '--json'], { encoding: 'utf8' });
    const result = JSON.parse(output);

    assert.equal(result.passed, true);
    assert.equal(result.mode, 'multi-file');
    assert.equal(result.totalTasksFound, 1);
    assert.equal(result.kanbanPath.endsWith('task-kanban-demo.md'), true);
});

test('check-plan-consistency accepts aligned main plan, kanban and current sub plan', () => {
    const hostRoot = makeTempDir('pm-suite-plan-consistency-valid-');
    const { mainPath, subPath } = writeMultiFileDeliveryPlan(hostRoot);

    const result = checkPlanConsistency({ planPath: mainPath });

    assert.equal(result.passed, true);
    assert.equal(result.activeTaskId, 'T0.1');
    assert.equal(result.activeSubPlanPath, subPath);
    assert.equal(result.sources.mainPlan.path, mainPath);
    assert.equal(result.sources.taskKanban.path.endsWith('task-kanban-demo.md'), true);
    assert.equal(result.sources.subPlan.path, subPath);
});

test('check-plan-consistency rejects cockpit active task drift', () => {
    const hostRoot = makeTempDir('pm-suite-plan-consistency-cockpit-drift-');
    const { mainPath } = writeMultiFileDeliveryPlan(hostRoot);
    writeFile(
        mainPath,
        readFile(mainPath).replace('`Phase 0 / T0.1 实现演示任务`', '`Phase 0 / T0.2 已不存在任务`')
    );

    const result = checkPlanConsistency({ planPath: mainPath });

    assert.equal(result.passed, false);
    assert.equal(result.activeTaskId, 'T0.1');
    assert.ok(result.errors.some((item) => item.type === 'cockpit_active_task_mismatch'));
});

test('check-plan-consistency rejects current sub plan status drift', () => {
    const hostRoot = makeTempDir('pm-suite-plan-consistency-subplan-drift-');
    const { mainPath, subPath } = writeMultiFileDeliveryPlan(hostRoot);
    writeFile(subPath, readFile(subPath).replace('**状态**：进行中', '**状态**：待开发'));

    const result = checkPlanConsistency({ planPath: mainPath });

    assert.equal(result.passed, false);
    assert.ok(result.errors.some((item) => item.type === 'current_sub_plan_status_mismatch'));
});

test('check-plan-consistency rejects multiple in-progress tasks', () => {
    const hostRoot = makeTempDir('pm-suite-plan-consistency-multiple-current-');
    const { mainPath, kanbanPath } = writeMultiFileDeliveryPlan(hostRoot);
    const planDir = path.dirname(mainPath);
    const secondSubPath = path.join(planDir, 'sub-delivery-plan-demo-T0.2-second-task.md');

    writeFile(
        mainPath,
        readFile(mainPath).replace(
            '| T0.1 | [sub-delivery-plan-demo-T0.1-demo-task.md](sub-delivery-plan-demo-T0.1-demo-task.md) | 进行中 |',
            '| T0.1 | [sub-delivery-plan-demo-T0.1-demo-task.md](sub-delivery-plan-demo-T0.1-demo-task.md) | 进行中 |\n| T0.2 | [sub-delivery-plan-demo-T0.2-second-task.md](sub-delivery-plan-demo-T0.2-second-task.md) | 进行中 |'
        )
    );
    writeFile(
        kanbanPath,
        readFile(kanbanPath) +
            '| T0.2 | [sub-delivery-plan-demo-T0.2-second-task.md](sub-delivery-plan-demo-T0.2-second-task.md) | AI | T0.1 | 进行中 | - | second |\n'
    );
    writeFile(
        secondSubPath,
        buildSubDeliveryPlanContent('demo')
            .replaceAll('T0.1', 'T0.2')
            .replaceAll('实现演示任务', '实现第二任务')
            .replaceAll('demo-task', 'second-task')
    );

    const result = checkPlanConsistency({ planPath: mainPath });

    assert.equal(result.passed, false);
    assert.ok(result.errors.some((item) => item.type === 'multiple_active_tasks'));
});

test('check-plan-consistency rejects missing current sub plan', () => {
    const hostRoot = makeTempDir('pm-suite-plan-consistency-missing-subplan-');
    const { mainPath, subPath } = writeMultiFileDeliveryPlan(hostRoot);
    fs.unlinkSync(subPath);

    const result = checkPlanConsistency({ planPath: mainPath });

    assert.equal(result.passed, false);
    assert.ok(result.errors.some((item) => item.type === 'missing_current_sub_plan'));
});

test('validate-plan-structure rejects kanban tasks that do not have matching sub delivery plans', () => {
    const hostRoot = makeTempDir('pm-suite-missing-sub-delivery-plan-');
    const { mainPath, kanbanPath } = writeMultiFileDeliveryPlan(hostRoot);
    writeFile(
        kanbanPath,
        `# Demo Task Kanban

| Task | 子开发计划 | Owner | 前置 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|---|---|
| T0.2 | [sub-delivery-plan-demo-T0.2-missing-task.md](sub-delivery-plan-demo-T0.2-missing-task.md) | AI | 无 | 待开发 | - | missing |
`
    );
    const validatorPath = path.join(
        CURRENT_SUITE_ROOT,
        'skills',
        '05-01-delivery-planner',
        'scripts',
        'validate-plan-structure.mjs'
    );

    const result = spawnSync(process.execPath, [validatorPath, mainPath, '--json'], { encoding: 'utf8' });
    const report = JSON.parse(result.stdout);

    assert.equal(result.status, 2);
    assert.equal(report.passed, false);
    assert.ok(report.errors.some((item) => item.type === 'missing_sub_delivery_plan' && item.taskId === 'T0.2'));
});

test('delivery plan templates satisfy the multi-file structure validator', () => {
    const templateDir = path.join(CURRENT_SUITE_ROOT, 'skills', '05-01-delivery-planner', 'templates');
    const hostRoot = makeTempDir('pm-suite-delivery-template-');
    const planDir = path.join(hostRoot, 'docs', 'plans', 'delivery-plans');
    const mainPath = path.join(planDir, 'main-delivery-plan-demo.md');
    const kanbanPath = path.join(planDir, 'task-kanban-demo.md');
    const subPath = path.join(planDir, 'sub-delivery-plan-demo-T0.1-demo-task.md');

    writeFile(mainPath, readFile(path.join(templateDir, 'main-delivery-plan-template.md')));
    writeFile(kanbanPath, readFile(path.join(templateDir, 'task-kanban-template.md')));
    writeFile(subPath, readFile(path.join(templateDir, 'sub-delivery-plan-template.md')));

    const validatorPath = path.join(
        CURRENT_SUITE_ROOT,
        'skills',
        '05-01-delivery-planner',
        'scripts',
        'validate-plan-structure.mjs'
    );

    const output = execFileSync(process.execPath, [validatorPath, mainPath, '--json'], { encoding: 'utf8' });
    const result = JSON.parse(output);

    assert.equal(result.passed, true);
    assert.equal(result.mode, 'multi-file');
});

test('delivery-planner sub plan template includes status-sync closure as task completion work', () => {
    const template = readFile(
        path.join(CURRENT_SUITE_ROOT, 'skills', '05-01-delivery-planner', 'templates', 'sub-delivery-plan-template.md')
    );
    const skill = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '05-01-delivery-planner', 'SKILL.md'));

    assert.ok(template.includes('完成收尾：状态同步'));
    assert.ok(template.includes('route-check.mjs <host> --target-stage S4 --json'));
    assert.ok(skill.includes('每个子开发计划最后必须包含'));
    assert.ok(skill.includes('未完成状态同步收尾前，不得标记 Task 已完成'));
});

test('verify-task-context blocks tasks that declare no real PRD links', () => {
    const hostRoot = makeTempDir('pm-suite-task-context-empty-prd-');
    const planPath = path.join(hostRoot, 'docs', 'plans', 'delivery-plans', 'sub-delivery-plan-demo-T0.1-empty-prd.md');

    writeFile(
        planPath,
        `# Demo Plan

### T0.1 实现演示任务

**PRD 双链·读**：
- 待补

**核心文件**：
- \`src/demo.js\`
`
    );

    const result = verifyTask(planPath, 'T0.1');

    assert.equal(result.canExecute, false);
    assert.deepEqual(result.prdLinksFound, []);
    assert.ok(result.missingFiles.includes('PRD 双链·读'));
});

test('verify-task-context resolves a task from main delivery plan through kanban to sub delivery plan', () => {
    const hostRoot = makeTempDir('pm-suite-task-context-main-plan-');
    const { mainPath, subPath } = writeMultiFileDeliveryPlan(hostRoot);
    writeFile(path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'), '# mainprd\n\n## 1\nDemo requirement.\n');

    const result = verifyTask(mainPath, 'T0.1');

    assert.equal(result.canExecute, true);
    assert.equal(result.taskTitle, '实现演示任务');
    assert.equal(result.taskPlanPath, subPath);
    assert.deepEqual(result.prdLinksFound, ['mainprd-demo.md']);
});

test('BRD D.5 is retriggered when locked fields change after a previous pass', () => {
    const hostRoot = makeTempDir('pm-suite-brd-d5-');
    const ledgerPath = path.join(hostRoot, 'ledger-state-demo.json');
    const queryPath = path.join(CURRENT_SUITE_ROOT, 'skills', '02-01-brd-writer', 'scripts', 'ledger-query.mjs');
    const ledger = createEmptyLedger('演示项目', 'demo', 'operational');

    ledger.header.current_phase = 'C';
    ledger.header.current_round = 6;
    ledger.header.d5_state = {
        last_result: 'passed',
        last_triggered_at_round: 3,
        fields_changed_since_last_d5: true
    };
    for (const field of ledger.fields) {
        field.status = 'locked';
        field.value = field.value ?? `value-${field.id}`;
        field.lock_round = field.lock_round ?? 6;
    }

    writeLedger(ledgerPath, ledger, 'demo');

    const output = execFileSync(process.execPath, [queryPath, 'progress', '--ledger', ledgerPath], { encoding: 'utf8' });
    const result = JSON.parse(output);

    assert.equal(result.open_fields, 0);
    assert.equal(result.should_trigger_d5, true);
});

test('skill docs avoid stale lifecycle filenames and unreachable stage names', () => {
    const runnerSkill = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '08-01-test-case-runner', 'SKILL.md'));
    const acceptanceSkill = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '08-02-test-and-acceptance', 'SKILL.md'));
    const devlogSkill = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '00-02-project-devlog', 'SKILL.md'));
    const pageDesignerSkill = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '03-02-page-designer', 'SKILL.md'));

    assert.ok(runnerSkill.includes('docs/test-case/tc-main-<slug>.md'));
    assert.ok(!runnerSkill.includes('tc-主文档.md'));
    assert.ok(!acceptanceSkill.includes('S9 / S10'));
    assert.match(acceptanceSkill, /S6\s*\/\s*S7/);
    assert.ok(devlogSkill.includes('logs/YYYYMMDD_refactor_log_<用户名>.md'));
    assert.match(pageDesignerSkill, /--persist[^\n]*--output-dir\s+<宿主项目>/);
});

test('ai-project-manager protocol points to multi-file delivery plans', () => {
    const files = [
        path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'assets', 'global-files', 'execution-plan.md'),
        path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'references', 'core', 'global-files-protocol.md'),
        path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'references', 'core', 'runtime.md'),
        path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'references', 'core', 'routing.md')
    ];
    const combined = files.map((file) => readFile(file)).join('\n');

    for (const file of files) {
        const content = readFile(file);
        assert.ok(content.includes('main-delivery-plan-<slug>.md'), `${file} must name the main delivery plan`);
        assert.ok(content.includes('task-kanban-<slug>.md'), `${file} must name the task kanban`);
        assert.ok(
            content.includes('sub-delivery-plan-<slug>-<TaskID>-<short-name>.md') ||
                content.includes('sub-delivery-plan-<slug>-T0.1-<short-name>.md'),
            `${file} must name sub delivery plans`
        );
    }

    assert.equal(/(^|[^a-z-])delivery-plan-<slug>\.md/.test(combined), false);
    assert.equal(/docs\/plans\/delivery-plan-/.test(combined), false);
});

test('implementation and test chiefs point to multi-file delivery plans', () => {
    const files = [
        path.join(CURRENT_SUITE_ROOT, 'skills', '06-01-coding-standards', 'SKILL.md'),
        path.join(CURRENT_SUITE_ROOT, 'skills', '07-01-test-case-chief', 'SKILL.md')
    ];
    const combined = files.map((file) => readFile(file)).join('\n');

    for (const file of files) {
        const content = readFile(file);
        assert.ok(content.includes('main-delivery-plan-<slug>.md'), `${file} must name the main delivery plan`);
        assert.ok(content.includes('task-kanban-<slug>.md'), `${file} must name the task kanban`);
        assert.ok(
            content.includes('sub-delivery-plan-<slug>-<TaskID>-<short-name>.md') ||
                content.includes('sub-delivery-plan-<slug>-T0.1-<short-name>.md'),
            `${file} must name sub delivery plans`
        );
    }

    assert.equal(/(^|[^a-z-])delivery-plan-<slug>\.md/.test(combined), false);
    assert.equal(/docs\/plans\/delivery-plan-/.test(combined), false);
});

test('pipeline places foundation-builder outputs under docs/prd/foundation', () => {
    const pipeline = readFile(path.join(CURRENT_SUITE_ROOT, 'PIPELINE.md'));

    for (const artifact of ['glossary', 'schema', 'api', 'delivery']) {
        assert.ok(
            pipeline.includes(
                `foundation-${artifact}-<slug>.md\` | \`<host>/docs/prd/foundation/\``
            ),
            `foundation-${artifact} must use docs/prd/foundation`
        );
        assert.equal(
            pipeline.includes(
                `foundation-${artifact}-<slug>.md\` | \`<host>/docs/prd/\``
            ),
            false,
            `foundation-${artifact} must not use docs/prd root`
        );
    }
});

test('ai-project-manager protocol defines project-link-indexer companion dispatch', () => {
    const runtime = readFile(
        path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'references', 'core', 'runtime.md')
    );
    const routing = readFile(
        path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'references', 'core', 'routing.md')
    );
    const pipeline = readFile(path.join(CURRENT_SUITE_ROOT, 'PIPELINE.md'));
    const skill = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '00-03-project-link-indexer', 'SKILL.md'));

    assert.ok(runtime.includes('companionActions'));
    assert.ok(runtime.includes('主入口只判断调起场景'));
    assert.ok(routing.includes('project-link-indexer'));
    assert.ok(pipeline.includes('主入口按场景调起 `project-link-indexer`'));
    assert.ok(pipeline.includes('索引器自行决定 build / refresh / noop'));
    assert.ok(skill.includes('run-project-link-indexer.mjs'));
});

test('ai-project-manager protocol owns baseline refresh orchestration', () => {
    const runtime = readFile(
        path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'references', 'core', 'runtime.md')
    );
    const routing = readFile(
        path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'references', 'core', 'routing.md')
    );
    const pipeline = readFile(path.join(CURRENT_SUITE_ROOT, 'PIPELINE.md'));

    assert.ok(runtime.includes('历史项目标准化模式'));
    assert.ok(runtime.includes('baseline 刷新由 `ai-project-manager` 负责'));
    assert.ok(routing.includes('推荐缺口已被对应产物满足时，主入口先刷新 baseline'));
    assert.ok(routing.includes('下游补档 skill 不感知 baseline'));
    assert.ok(pipeline.includes('baseline-audit 是可反复刷新的当前缺口状态'));
});

test('ai-project-manager protocol requires delivery-planner consistency gate before S4 coding', () => {
    const runtime = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'references', 'core', 'runtime.md'));
    const routing = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '00-01-ai-project-manager', 'references', 'core', 'routing.md'));
    const deliveryPlanner = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '05-01-delivery-planner', 'SKILL.md'));
    const codingStandards = readFile(path.join(CURRENT_SUITE_ROOT, 'skills', '06-01-coding-standards', 'SKILL.md'));

    assert.ok(runtime.includes('s4_pre_coding_plan_consistency_check'));
    assert.ok(runtime.includes('delivery-planner/scripts/check-plan-consistency.mjs'));
    assert.ok(routing.includes('s4_pre_coding_plan_consistency_check'));
    assert.ok(deliveryPlanner.includes('s4_pre_coding_plan_consistency_check'));
    assert.ok(codingStandards.includes('s4_pre_coding_plan_consistency_check'));
    assert.ok(codingStandards.includes('正式开发计划文件组三者状态回写由 ai-project-manager 调度 delivery-planner 执行'));
    assert.equal(codingStandards.includes('直接在对应子开发计划和任务看板原地修改'), false);
});

test('devlog-sync creates daily log, appends updates, and updates candidate pool', () => {
    const hostRoot = makeTempDir('pm-suite-devlog-');

    const firstResult = devlogSync({
        hostRoot,
        actor: 'tester',
        date: '2026-04-06',
        time: '10:00',
        title: '阶段切换回写',
        goal: '补齐阶段切换日志',
        action: '写入结构化日志',
        result: '阶段切换前必须先日志回写，建议提炼为规则',
        files: 'project-profile.md,docs/plans/execution-plan.md',
        stage: 'S1',
        conclusion: '日志闭环已补齐',
        next: '继续 BRD 收敛||补齐验收标准',
        planPath: '',
        reflection: '阶段切换前必须先日志回写，建议提炼为规则',
        ruleScope: '全局',
        ruleTarget: 'project-rules.md',
        ruleCheck: '进入子能力前检查最近日志是否记录阶段切换',
        ruleTitle: '阶段切换前必须先日志回写',
        dryRun: false,
        json: false
    });

    assert.equal(firstResult.createdLog, true);
    assert.equal(firstResult.updatedCandidatePool, true);
    assert.ok(fs.existsSync(path.join(hostRoot, firstResult.logFile)));
    assert.ok(fs.existsSync(path.join(hostRoot, firstResult.candidatePoolFile)));

    const secondResult = devlogSync({
        hostRoot,
        actor: 'tester',
        date: '2026-04-06',
        time: '11:30',
        title: '补充更新',
        goal: '追加同日日志',
        action: '继续记录推进状态',
        result: '追加成功',
        files: 'logs/20260406_refactor_log_tester.md',
        stage: 'S1',
        conclusion: '追加完成',
        next: '继续推进',
        planPath: '',
        reflection: '',
        ruleScope: '',
        ruleTarget: '',
        ruleCheck: '',
        ruleTitle: '',
        dryRun: false,
        json: false
    });

    assert.equal(secondResult.appendedLog, true);
    assert.equal(secondResult.mergedLog, false);
    assert.ok(readFile(path.join(hostRoot, secondResult.logFile)).includes('## 补充更新 1'));
});

test('devlog-sync writes to the devlog directory configured in project-profile', () => {
    const hostRoot = makeTempDir('pm-suite-devlog-configured-');
    const configuredProfile = buildProfileContent().replace(
        '- 状态入口：logs/',
        '- 最近状态入口：`【系统推断】 docs/devlog/`'
    );
    writeFile(path.join(hostRoot, 'project-profile.md'), configuredProfile);
    writeFile(path.join(hostRoot, 'docs', 'plans', 'execution-plan.md'), buildPlanContent());

    const result = devlogSync({
        hostRoot,
        actor: 'tester',
        date: '2026-04-16',
        time: '10:00',
        title: '宿主日志路径适配',
        goal: '把开发日志与运行日志分离',
        action: '读取项目画像中的最近状态入口',
        result: '开发日志写入可跟踪目录',
        files: 'project-profile.md',
        stage: 'S0.5',
        conclusion: '路径适配完成',
        next: '继续项目治理',
        planPath: '',
        reflection: '',
        ruleScope: '',
        ruleTarget: '',
        ruleCheck: '',
        ruleTitle: '',
        dryRun: false,
        json: false
    });

    assert.match(result.logFile, /^docs\/devlog\/20260416_refactor_log_.+\.md$/);
    assert.ok(fs.existsSync(path.join(hostRoot, result.logFile)));
    assert.equal(fs.existsSync(path.join(hostRoot, 'logs')), false);
});

test('devlog-sync rejects an absolute devlog directory from project-profile', () => {
    const hostRoot = makeTempDir('pm-suite-devlog-absolute-');
    const configuredProfile = buildProfileContent().replace(
        '- 状态入口：logs/',
        '- 最近状态入口：`【系统推断】 C:\\outside\\devlog\\`'
    );
    writeFile(path.join(hostRoot, 'project-profile.md'), configuredProfile);
    writeFile(path.join(hostRoot, 'docs', 'plans', 'execution-plan.md'), buildPlanContent());

    assert.throws(
        () =>
            devlogSync({
                hostRoot,
                actor: 'tester',
                date: '2026-04-16',
                time: '10:00',
                title: '非法日志路径',
                goal: '验证宿主边界',
                action: '尝试读取绝对路径配置',
                result: '应阻止写入',
                files: 'project-profile.md',
                stage: 'S0.5',
                conclusion: '',
                next: '',
                planPath: '',
                reflection: '',
                ruleScope: '',
                ruleTarget: '',
                ruleCheck: '',
                ruleTitle: '',
                dryRun: true,
                json: false
            }),
        /host-relative path/
    );
});

test('devlog-sync merges decision-like same-stage updates into the latest task block', () => {
    const hostRoot = makeTempDir('pm-suite-devlog-merge-');

    const firstResult = devlogSync({
        hostRoot,
        actor: 'tester',
        date: '2026-04-15',
        time: '10:00',
        title: 'S1 需求收敛',
        goal: '收敛首页服务表达',
        action: '建立首页服务信息框架',
        result: '已明确首页核心结构',
        files: 'project-profile.md,docs/plans/execution-plan.md',
        stage: 'S1',
        conclusion: '需求收敛启动',
        next: '继续确认提醒规则',
        planPath: '',
        reflection: '',
        ruleScope: '',
        ruleTarget: '',
        ruleCheck: '',
        ruleTitle: '',
        dryRun: false,
        json: false
    });

    const secondResult = devlogSync({
        hostRoot,
        actor: 'tester',
        date: '2026-04-15',
        time: '10:20',
        title: '确认首页文案策略',
        goal: '收敛首页动态文案口径',
        action: '确认不同车辆状态显示不同提示文案',
        result: '首页文案采用轻量动态变化',
        files: 'project-profile.md,docs/plans/execution-plan.md,docs/brd/BRD-demo.md',
        stage: 'S1',
        conclusion: '',
        next: '',
        planPath: '',
        reflection: '',
        ruleScope: '',
        ruleTarget: '',
        ruleCheck: '',
        ruleTitle: '',
        dryRun: false,
        json: false
    });

    const logContent = readFile(path.join(hostRoot, firstResult.logFile));

    assert.equal(secondResult.appendedLog, false);
    assert.equal(secondResult.mergedLog, true);
    assert.ok(!logContent.includes('## 补充更新 1'));
    assert.ok(logContent.includes('- **同主题补充**：'));
    assert.ok(logContent.includes('10:20 确认首页文案策略'));
    assert.ok(logContent.includes('docs/brd/BRD-demo.md'));
});

test('devlog-sync uses git user name for log file naming while preserving actor display text', () => {
    const hostRoot = makeTempDir('pm-suite-devlog-git-user-');

    writeFile(path.join(hostRoot, 'project-profile.md'), buildProfileContent());
    writeFile(path.join(hostRoot, 'docs', 'plans', 'execution-plan.md'), buildPlanContent());

    execFileSync('git', ['init'], { cwd: hostRoot, stdio: 'ignore' });
    execFileSync('git', ['config', 'user.name', 'tutoumao'], { cwd: hostRoot, stdio: 'ignore' });

    const result = devlogSync({
        hostRoot,
        actor: '我 + AI',
        date: '2026-04-08',
        time: '10:00',
        title: '启动项目骨架',
        goal: '建立项目画像与计划入口',
        action: '执行 bootstrap 并补齐基础结构',
        result: '骨架创建完成',
        files: 'project-profile.md,docs/plans/execution-plan.md',
        stage: 'S0',
        conclusion: '基础骨架已可继续推进',
        next: '继续访谈',
        planPath: '',
        reflection: '',
        ruleScope: '',
        ruleTarget: '',
        ruleCheck: '',
        ruleTitle: '',
        dryRun: false,
        json: false
    });

    const logPath = path.join(hostRoot, result.logFile);

    assert.equal(result.actor, '我 + AI');
    assert.equal(result.actorFileKey, 'tutoumao');
    assert.equal(result.logFile, 'logs/20260408_refactor_log_tutoumao.md');
    assert.ok(fs.existsSync(logPath));
    assert.ok(readFile(logPath).includes('> 操作人：我 + AI'));
});

test('devlog-sync falls back to git user name for actor display on Windows-like environments', () => {
    const hostRoot = makeTempDir('pm-suite-devlog-default-git-user-');

    writeFile(path.join(hostRoot, 'project-profile.md'), buildProfileContent());
    writeFile(path.join(hostRoot, 'docs', 'plans', 'execution-plan.md'), buildPlanContent());

    execFileSync('git', ['init'], { cwd: hostRoot, stdio: 'ignore' });
    execFileSync('git', ['config', 'user.name', 'tutoumao'], { cwd: hostRoot, stdio: 'ignore' });

    const result = devlogSync({
        hostRoot,
        actor: '',
        date: '2026-04-08',
        time: '10:00',
        title: '启动项目骨架',
        goal: '建立项目画像与计划入口',
        action: '执行 bootstrap 并补齐基础结构',
        result: '骨架创建完成',
        files: 'project-profile.md,docs/plans/execution-plan.md',
        stage: 'S0',
        conclusion: '基础骨架已可继续推进',
        next: '继续访谈',
        planPath: '',
        reflection: '',
        ruleScope: '',
        ruleTarget: '',
        ruleCheck: '',
        ruleTitle: '',
        dryRun: false,
        json: false
    });

    const logPath = path.join(hostRoot, result.logFile);

    assert.equal(result.actor, 'tutoumao');
    assert.equal(result.actorFileKey, 'tutoumao');
    assert.ok(readFile(logPath).includes('> 操作人：tutoumao'));
});

test('bootstrap text treats startup intent as an automatic ai-project-manager entry', () => {
    const claudeBootstrap = buildClaudeHookBootstrap(CURRENT_SUITE_ROOT);
    const openCodeBootstrap = buildOpenCodeBootstrap({
        suiteRoot: CURRENT_SUITE_ROOT,
        configDir: '/tmp/codex-config'
    });

    assert.ok(claudeBootstrap.includes('默认直接由 `ai-project-manager` 接管'));
    assert.ok(claudeBootstrap.includes('不要再次询问是否要按这套流程开始'));
    assert.ok(claudeBootstrap.includes('不得先进入 `superpower` 等通用增强类 skill'));
    assert.ok(openCodeBootstrap.includes('不要再确认是否启用它'));
    assert.ok(openCodeBootstrap.includes('不要先进入 `superpower` 等通用增强类 skill'));
});
