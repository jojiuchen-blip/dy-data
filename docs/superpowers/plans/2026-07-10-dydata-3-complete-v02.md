# DYDATA-3 Complete V0.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 V0.2 候选页升级为与 V0.1 同等完整、默认展示品牌橙且不进入业务运行时的独立设计规范。

**Architecture:** 以 V0.1 HTML 和 token schema 为结构基线，复制完整信息架构后覆盖候选品牌角色，并把现有橙色试验内容吸收到颜色和组件章节。静态测试对比 V0.1/V0.2 的章节、组件和页面模板，防止候选规范再次退化成单页样张。

**Tech Stack:** 单文件 HTML/CSS/JavaScript、JSON、pytest、Playwright CLI、Vite build。

## Global Constraints

- V0.2 继续 `light-only`。
- 不修改 `apps/web/src/design-tokens.css` 或任何业务 UI。
- 成功、警告、错误、信息色保持 V0.1 原语义。
- DYDATA-4 在“确认进入阶段 2”前保持未启动。

---

### Task 1: 建立完整候选 token schema

**Files:**
- Modify: `docs/design-system/tokens.v0.2-candidate.json`
- Test: `tests/test_design_system_docs.py`

**Interfaces:**
- Consumes: `docs/design-system/tokens.json` 的完整顶层 schema。
- Produces: 包含 `meta`、`principles`、`tokens`、`components`、`pageTemplates`、`enforcement`、`candidateDecision` 和 `approvalGate` 的候选 JSON。

- [ ] **Step 1: 扩展失败测试**

```python
assert set(candidate) >= {
    "meta", "principles", "tokens", "components", "pageTemplates",
    "enforcement", "candidateDecision", "approvalGate",
}
assert set(candidate["components"]) == set(active["components"])
assert set(candidate["pageTemplates"]) == set(active["pageTemplates"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_design_system_docs.py -k candidate -q`

Expected: FAIL，当前候选 JSON 缺少完整 token、组件和页面模板。

- [ ] **Step 3: 从 V0.1 schema 生成完整候选 JSON**

保留所有非品牌尺寸和行为规则，更新候选 meta、品牌角色、按钮状态、语义边界和阶段门禁。

- [ ] **Step 4: 运行候选 JSON 测试**

Run: `python -m pytest tests/test_design_system_docs.py -k candidate -q`

Expected: PASS。

### Task 2: 将候选 HTML 升级为完整规范

**Files:**
- Modify: `docs/design-system/candidate-v0.2.html`
- Test: `tests/test_design_system_docs.py`

**Interfaces:**
- Consumes: V0.1 的完整章节结构和 V0.2 候选 token。
- Produces: 独立可打开的 V0.2 完整规范页，默认候选橙色，保留绿色比较切换。

- [ ] **Step 1: 增加章节覆盖失败测试**

```python
for heading in COMPLETE_V02_HEADINGS:
    assert heading in candidate_html
for component in COMPLETE_V02_COMPONENT_LABELS:
    assert component in candidate_html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_design_system_docs.py -k candidate_html -q`

Expected: FAIL，当前候选页缺少排版、间距、组件、图标、表格和页面模板章节。

- [ ] **Step 3: 以 V0.1 为结构基线重建候选页**

完整保留 V0.1 章节和组件样板；更新标题、候选状态、颜色 token、品牌组件状态、候选说明和人工确认门禁。比较切换只修改 CSS 自定义属性，不修改持久状态。

- [ ] **Step 4: 运行文档测试**

Run: `python -m pytest tests/test_design_system_docs.py -q`

Expected: PASS。

### Task 3: 防退化与视觉验收

**Files:**
- Modify: `tests/test_design_system_enforcement.py`
- Verify: `docs/design-system/candidate-v0.2.html`

**Interfaces:**
- Consumes: 完整 V0.2 HTML/JSON。
- Produces: 结构覆盖、运行时隔离和响应式视觉证据。

- [ ] **Step 1: 增加运行时隔离与结构门禁**

```python
assert "tokens.v0.2-candidate.json" not in runtime_source
assert "candidate-v0.2.html" not in runtime_source
assert candidate["meta"]["runtimeApplied"] is False
```

- [ ] **Step 2: 运行设计系统门禁**

Run: `python -m pytest tests/test_design_system_docs.py tests/test_design_system_enforcement.py -q`

Expected: PASS。

- [ ] **Step 3: Playwright 三档检查**

在 390x844、768x1024、1440x1100 检查 `scrollWidth - innerWidth == 0`、唯一 H1、控制台 0 errors，并保存截图到已忽略的 `output/playwright/`。

- [ ] **Step 4: 完整验证**

Run: `python -m pytest`

Expected: `262 passed` 或更多，无失败。

Run: `npm --prefix apps/web run build`

Expected: TypeScript 和 Vite production build 成功。

- [ ] **Step 5: 更新 Linear**

在 DYDATA-3 记录文件、测试、三档视觉结果和仍未进入业务运行时的事实；状态保持 In Review，等待阶段 2 明确确认。
