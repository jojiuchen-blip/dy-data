import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { routeCheck } from '../tools/route-check.mjs';

const TEST_FILE_PATH = fileURLToPath(import.meta.url);
const SUITE_ROOT = path.resolve(path.dirname(TEST_FILE_PATH), '..');
const PRD_CHECK = path.join(SUITE_ROOT, 'skills', '04-03-prd-writer', 'scripts', 'prd-check.mjs');

function makeTempDir(prefix) {
    return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function writeFile(targetPath, content) {
    fs.mkdirSync(path.dirname(targetPath), { recursive: true });
    fs.writeFileSync(targetPath, content, 'utf8');
}

function readFile(targetPath) {
    return fs.readFileSync(targetPath, 'utf8');
}

function runPrdCheck(args, { expectFailure = false } = {}) {
    try {
        const stdout = execFileSync('node', [PRD_CHECK, ...args, '--json'], {
            cwd: SUITE_ROOT,
            encoding: 'utf8',
            stdio: ['ignore', 'pipe', 'pipe']
        });
        const parsed = JSON.parse(stdout);
        if (expectFailure) {
            assert.fail('expected prd-check to fail');
        }
        return parsed;
    } catch (error) {
        const output = error.stdout || error.stderr || '';
        let parsed = null;
        try {
            parsed = JSON.parse(output);
        } catch {}
        if (!expectFailure) {
            throw error;
        }
        if (!parsed) {
            throw error;
        }
        return parsed;
    }
}

function featureList({ missingPanorama = false, missingDetailsAnchor = false, localPanoramaNumbers = false } = {}) {
    const panorama = missingPanorama ? '' : `
---

## 页面布局全景

### 首页（路由: /home）

\`\`\`
┌────────────┐
│ ① 欢迎区   │
├────────────┤
│ ② 列表区   │
└────────────┘
\`\`\`

### 设置页（路由: /settings）

\`\`\`
┌────────────┐
│ ${localPanoramaNumbers ? '①' : '③'} 设置区   │
└────────────┘
\`\`\`
`;
    const detailAnchor = missingDetailsAnchor ? '' : '**涉及使用者**：运营人员';

    return `# 功能列表 - Demo

> 生成时间: 2026-06-12 10:00
> 来源: prd-writer Phase 2

---

## 产品背景与定位

### 产品是什么

Demo 是一个运营工作台。

### 使用者

| 使用者 | 使用场景 |
|--------|---------|
| **运营人员** | 查看和配置内容 |

---

## 功能总表

| # | 页面 | 区块 | 功能说明 | subprd文件 | 状态 |
|---|------|------|---------|-------------|------|
| 1 | 首页 | 欢迎区 | 展示欢迎信息 | [01-subprd-welcome.md](subprd/01-subprd-welcome.md) | 已确认 |
| 2 | 首页 | 列表区 | 展示内容列表 | [02-subprd-list.md](subprd/02-subprd-list.md) | 已确认 |
| 3 | 设置页 | 设置区 | 配置展示规则 | [03-subprd-settings.md](subprd/03-subprd-settings.md) | 已确认 |
${panorama}
---

## 区块详情

### ① 欢迎区

**所属页面**：首页（路由: /home）

**布局**：

\`\`\`
┌────────────┐
│ 欢迎文案    │
└────────────┘
\`\`\`

**业务逻辑**：
- 展示欢迎信息

${detailAnchor}

---

### ② 列表区

**所属页面**：首页（路由: /home）

**布局**：

\`\`\`
┌────────────┐
│ 内容列表    │
└────────────┘
\`\`\`

**业务逻辑**：
- 展示内容列表

**涉及使用者**：运营人员

---

### ① 设置区

**所属页面**：设置页（路由: /settings）

**布局**：

\`\`\`
┌────────────┐
│ 开关控件    │
└────────────┘
\`\`\`

**业务逻辑**：
- 配置展示规则

**涉及使用者**：运营人员
`;
}

function mainprd({ dangerousTable = false, status = '已确认' } = {}) {
    const extra = dangerousTable
        ? `
## 一致性追溯表

| # | 区块 | subprd 文件 | 存在 |
|---|------|-----------|------|
| 1 | 欢迎区 | 01-subprd-welcome.md | ✓ |
`
        : `
## 一致性自查结果

- 检查时间: 2026-06-12 10:00
- P1 数据链路覆盖: 3/3 (100%)
- P2 接口引用覆盖: 3/3 (100%)
- P3 术语覆盖: 已人工复核
- P4 功能列表→subprd: 3/3 (100%)
- P5 mainprd 索引完整: ✓
- P6 交互语义一致: 3/3 (100%)
- P8 流程覆盖: 已人工复核
- P9 功能子区域 ↔ 验收对应性: 3/3 (100%)
- 需回溯 foundation-builder: 无

## 待回溯缺口

| 缺口 | 类型 | 回溯目标 | 状态 |
|---|---|---|---|
| 无 | — | — | resolved |
`;

    return `# Demo — mainprd

> 生成时间: 2026-06-12 10:00
> 来源: prd-writer Phase 3
> 技术栈: Vue 3

---

## 上游引用

| 产物 | 文件 | 来源 Skill |
|------|------|-----------|
| 功能列表 | [prd-feature-list-demo.md](prd-feature-list-demo.md) | prd-writer |
| 用户流程 | [explainer-flow-demo.md](../../src/frontend/page-preview/explainer-flow-demo.md) | page-explainer |
| 交互语义 | [explainer-b-interaction-demo.md](../../src/frontend/page-preview/explainer-b-interaction-demo.md) | page-explainer |
| 术语表 | [foundation-glossary-demo.md](foundation/foundation-glossary-demo.md) | foundation-builder |
| 数据库 Schema | [foundation-schema-demo.md](foundation/foundation-schema-demo.md) | foundation-builder |
| API 接口 | [foundation-api-demo.md](foundation/foundation-api-demo.md) | foundation-builder |

---

## subprd索引

| # | 区块 | 所属页面 | subprd文件 | 状态 |
|---|------|---------|-----------|------|
| 1 | 欢迎区 | 首页 | [01-subprd-welcome.md](subprd/01-subprd-welcome.md) | ${status} |
| 2 | 列表区 | 首页 | [02-subprd-list.md](subprd/02-subprd-list.md) | ${status} |
| 3 | 设置区 | 设置页 | [03-subprd-settings.md](subprd/03-subprd-settings.md) | ${status} |

---

## 全局设计规则

| 规则 | 说明 |
|------|------|
| 空状态 | 展示空状态文案 |
${extra}`;
}

function subprd(order, name, apiPath, field, interactionId, { omitAcceptance = false } = {}) {
    const acceptance = omitAcceptance
        ? ''
        : `
### 4.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 展示${name} | 接口成功 | 页面展示${name} |
`;

    return `# PRD ${order}: ${name}

> **文档版本**: 1.0 | **最后更新**: 2026-06-12
> **关联文档**: [mainprd](../mainprd-demo.md)

---

## §1 文档范围

本文档覆盖**${name}**。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|------|---------|---------|
| R1 | ${name} | 完成${name}能力 | §4 |

---

## §2 页面整体布局

\`\`\`
┌────────────┐
│ ${name}     │ ← 本文档 §4
└────────────┘
\`\`\`

---

## §4 ${name}

### 4.1 用户体验

**数据来源**：\`GET ${apiPath}\` 返回的 \`${field}\`

**交互语义引用**：\`${interactionId}\`

**布局**：

\`\`\`
┌────────────┐
│ ${name}     │
└────────────┘
\`\`\`

**前端职责**：仅渲染返回字段

### 4.3 数据链路

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| ${name} | \`${field}\` | 直透 | \`demo_items.${field}\` | — |

### 4.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 数据缺失 | 返回空值 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 字段为空 | 展示占位 |

${acceptance}
`;
}

function writeHappyHost() {
    const hostRoot = makeTempDir('prd-check-');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'prd-feature-list-demo.md'), featureList());
    writeFile(path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'), mainprd());
    writeFile(path.join(hostRoot, 'docs', 'prd', 'subprd', '01-subprd-welcome.md'), subprd(1, '欢迎区', '/api/welcome/{id}', 'title', 'home.welcome.open.1'));
    writeFile(path.join(hostRoot, 'docs', 'prd', 'subprd', '02-subprd-list.md'), subprd(2, '列表区', '/api/list', 'summary', 'home.list.refresh.1'));
    writeFile(path.join(hostRoot, 'docs', 'prd', 'subprd', '03-subprd-settings.md'), subprd(3, '设置区', '/api/settings/:id', 'enabled', 'settings.toggle.change.1'));

    writeFile(path.join(hostRoot, 'src', 'frontend', 'page-preview', 'page-delivery-demo.md'), `# 页面交付

| 页面 | 路由 | 文件路径 |
|---|---|---|
| 首页 | /home | app/src/Home.vue |
| 设置页 | /settings | app/src/Settings.vue |
| 工单卡片组件 | component:ticket-card | app/src/components/TicketCard.vue |
| Mock 数据 | data:mock-items | app/src/data/mockItems.js |
`);
    writeFile(path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-flow-demo.md'), '# 用户流程\n');
    writeFile(path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-b-interaction-demo.md'), `# 交互语义

| id | source_page | source_module | trigger | system_behavior | status |
|---|---|---|---|---|---|
| home.welcome.open.1 | 首页 | 欢迎区 | 打开页面 | 展示欢迎 | locked |
| home.list.refresh.1 | 首页 | 列表区 | 刷新 | 更新列表 | locked |
| settings.toggle.change.1 | 设置页 | 设置区 | 切换 | 保存配置 | locked |
`);

    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-glossary-demo.md'), '# 术语表\n');
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-schema-demo.md'), `# 数据库 Schema

## 全表总览

| # | 表名 | 说明 |
|---|---|---|
| 1 | \`demo_items\` | 内容 |

### 1.1 \`demo_items\`

| 字段 | 类型 | 说明 |
|---|---|---|
| \`title\` | varchar | 标题 |
| \`summary\` | varchar | 摘要 |
| \`enabled\` | boolean | 是否启用 |
`);
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-api-demo.md'), `# API 接口

## 接口总览

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 1 | GET | /api/welcome/:id | 欢迎 |
| 2 | GET | /api/list | 列表 |
| 3 | GET | /api/settings/{id} | 设置 |
`);
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-delivery-demo.md'), `# Foundation 交付清单

## 一致性自查结果

- 结论: ✓

| 产物 | 文件路径 | 说明 |
|---|---|---|
| 术语表 | docs/prd/foundation/foundation-glossary-demo.md | 已确认 |
| 数据库 Schema | docs/prd/foundation/foundation-schema-demo.md | 已确认 |
| API 接口 | docs/prd/foundation/foundation-api-demo.md | 已确认 |
`);
    return hostRoot;
}

test('structure detects a feature-list missing the page layout panorama with repair metadata', () => {
    const hostRoot = writeHappyHost();
    const featurePath = path.join(hostRoot, 'docs', 'prd', 'prd-feature-list-demo.md');
    writeFile(featurePath, featureList({ missingPanorama: true }));

    const result = runPrdCheck(['structure', '--file', featurePath], { expectFailure: true });

    assert.equal(result.ok, false);
    assert.ok(result.issues.some((issue) => issue.ruleId === 'feature-list.required-section'));
    const issue = result.issues.find((item) => item.ruleId === 'feature-list.required-section');
    assert.equal(issue.severity, 'fail');
    assert.match(issue.fixHint, /页面布局全景/);
    assert.match(issue.nextCommand, /structure/);
});

test('crosscheck passes the happy-path mock fixture', () => {
    const hostRoot = writeHappyHost();

    const result = runPrdCheck(['crosscheck', '--host-dir', hostRoot, '--slug', 'demo']);

    assert.equal(result.ok, true);
    assert.equal(result.summary.fail, 0);
    assert.equal(result.summary.needs_ai_review, 0);
});

test('crosscheck catches feature-list/mainprd status drift with a stable rule id', () => {
    const hostRoot = writeHappyHost();
    writeFile(path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'), mainprd({ status: '待确认' }));

    const result = runPrdCheck(['crosscheck', '--host-dir', hostRoot, '--slug', 'demo'], { expectFailure: true });

    assert.equal(result.ok, false);
    assert.ok(result.issues.some((issue) => issue.ruleId === 'crosscheck.index-row-drift'));
});

test('structure detects missing feature-list detail anchors', () => {
    const hostRoot = writeHappyHost();
    const featurePath = path.join(hostRoot, 'docs', 'prd', 'prd-feature-list-demo.md');
    writeFile(featurePath, featureList({ missingDetailsAnchor: true }));

    const result = runPrdCheck(['structure', '--file', featurePath], { expectFailure: true });

    assert.equal(result.ok, false);
    assert.ok(result.issues.some((issue) => issue.ruleId === 'feature-list.detail-anchor-missing'));
});

test('structure detects page panorama numbers that reset per page instead of using global block ids', () => {
    const hostRoot = writeHappyHost();
    const featurePath = path.join(hostRoot, 'docs', 'prd', 'prd-feature-list-demo.md');
    writeFile(featurePath, featureList({ localPanoramaNumbers: true }));

    const result = runPrdCheck(['structure', '--file', featurePath], { expectFailure: true });

    assert.equal(result.ok, false);
    assert.ok(result.issues.some((issue) => issue.ruleId === 'feature-list.panorama-block-ids'));
    const issue = result.issues.find((item) => item.ruleId === 'feature-list.panorama-block-ids');
    assert.match(issue.expected, /③/);
    assert.match(issue.actual, /①/);
});

test('crosscheck catches page-delivery pages missing from the feature list', () => {
    const hostRoot = writeHappyHost();
    writeFile(path.join(hostRoot, 'src', 'frontend', 'page-preview', 'page-delivery-demo.md'), `# 页面交付

| 页面 | 路由 | 文件路径 |
|---|---|---|
| 首页 | /home | app/src/Home.vue |
| 设置页 | /settings | app/src/Settings.vue |
| 报表页 | /reports | app/src/Reports.vue |
`);

    const result = runPrdCheck(['crosscheck', '--host-dir', hostRoot, '--slug', 'demo'], { expectFailure: true });

    assert.equal(result.ok, false);
    assert.ok(result.issues.some((issue) => issue.ruleId === 'crosscheck.page-coverage-missing'));
});

test('crosscheck catches missing schema fields referenced by subprd data links', () => {
    const hostRoot = writeHappyHost();
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-schema-demo.md'), `# 数据库 Schema

### 1.1 \`demo_items\`

| 字段 | 类型 | 说明 |
|---|---|---|
| \`title\` | varchar | 标题 |
`);

    const result = runPrdCheck(['crosscheck', '--host-dir', hostRoot, '--slug', 'demo'], { expectFailure: true });

    assert.equal(result.ok, false);
    assert.ok(result.issues.some((issue) => issue.ruleId === 'crosscheck.schema-field-missing'));
});

test('crosscheck catches missing API paths referenced by subprd files', () => {
    const hostRoot = writeHappyHost();
    writeFile(path.join(hostRoot, 'docs', 'prd', 'foundation', 'foundation-api-demo.md'), `# API 接口

## 接口总览

| # | 方法 | 路径 | 说明 |
|---|---|---|---|
| 1 | GET | /api/welcome/:id | 欢迎 |
`);

    const result = runPrdCheck(['crosscheck', '--host-dir', hostRoot, '--slug', 'demo'], { expectFailure: true });

    assert.equal(result.ok, false);
    assert.ok(result.issues.some((issue) => issue.ruleId === 'crosscheck.api-path-missing'));
});

test('crosscheck catches invalid or unlocked interaction ids', () => {
    const hostRoot = writeHappyHost();
    writeFile(path.join(hostRoot, 'src', 'frontend', 'page-preview', 'explainer-b-interaction-demo.md'), `# 交互语义

| id | source_page | source_module | trigger | system_behavior | status |
|---|---|---|---|---|---|
| home.welcome.open.1 | 首页 | 欢迎区 | 打开页面 | 展示欢迎 | open |
| home.list.refresh.1 | 首页 | 列表区 | 刷新 | 更新列表 | locked |
| settings.toggle.change.1 | 设置页 | 设置区 | 切换 | 保存配置 | locked |
`);

    const result = runPrdCheck(['crosscheck', '--host-dir', hostRoot, '--slug', 'demo'], { expectFailure: true });

    assert.equal(result.ok, false);
    assert.ok(result.issues.some((issue) => issue.ruleId === 'crosscheck.interaction-id-invalid'));
});

test('structure catches subprd functional sections missing X.6 acceptance', () => {
    const hostRoot = writeHappyHost();
    const subprdPath = path.join(hostRoot, 'docs', 'prd', 'subprd', '01-subprd-welcome.md');
    writeFile(subprdPath, subprd(1, '欢迎区', '/api/welcome/{id}', 'title', 'home.welcome.open.1', { omitAcceptance: true }));

    const result = runPrdCheck(['structure', '--file', subprdPath], { expectFailure: true });

    assert.equal(result.ok, false);
    assert.ok(result.issues.some((issue) => issue.ruleId === 'subprd.functional-subsection'));
});

test('set-status updates both indexes and sync-index restores the mainprd table from feature-list', () => {
    const hostRoot = writeHappyHost();
    const mainPath = path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md');
    writeFile(mainPath, mainprd({ status: '待确认' }));

    const setResult = runPrdCheck([
        'set-status',
        '--host-dir',
        hostRoot,
        '--slug',
        'demo',
        '--block',
        '2',
        '--status',
        '已确认'
    ]);
    assert.equal(setResult.ok, true);

    const syncResult = runPrdCheck(['sync-index', '--host-dir', hostRoot, '--slug', 'demo']);
    assert.equal(syncResult.ok, true);

    const mainContent = readFile(mainPath);
    assert.match(mainContent, /\| 2 \| 列表区 \| 首页 \| \[02-subprd-list\.md\]\(subprd\/02-subprd-list\.md\) \| 已确认 \|/);
});

test('route-check is not polluted by safe PRD self-check tables', async () => {
    const hostRoot = writeHappyHost();

    const result = await routeCheck({
        hostRoot,
        targetStage: 'S3',
        json: true
    });

    assert.equal(result.gateChecks.fullPrdReady.pass, true);
});

test('route-check dangerous-table fixture proves why PRD self-check tables must avoid index headers', async () => {
    const hostRoot = writeHappyHost();
    writeFile(path.join(hostRoot, 'docs', 'prd', 'mainprd-demo.md'), mainprd({ dangerousTable: true }));

    const result = await routeCheck({
        hostRoot,
        targetStage: 'S3',
        json: true
    });

    assert.equal(result.gateChecks.fullPrdReady.pass, false);
    assert.ok(result.gateChecks.fullPrdReady.evidence.unconfirmedRows.some((row) => row.status === '未标记'));
});
