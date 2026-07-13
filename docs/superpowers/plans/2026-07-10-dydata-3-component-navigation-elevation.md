# DYDATA-3 组件、导航与层级规范 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不触及业务运行时的前提下，为 V0.2 候选规范补齐指标卡、导航和阴影层级，并提供四模块移动导航样板。

**Architecture:** 候选 JSON 先成为组件状态、导航断点和层级 token 的机器可读来源；候选 HTML 再以相同 token 呈现状态矩阵和移动样板。测试同时校验结构、色值和运行时隔离，确保此项仍是 DYDATA-3 的设计确认工作，不是 DYDATA-4 的业务迁移。

**Tech Stack:** 单文件 HTML/CSS/JavaScript、JSON、pytest、Playwright CLI。

## Global Constraints

- V0.2 保持 `light-only`。
- 不修改 `apps/web/src/design-tokens.css`、`apps/web/src`、路由和业务页面。
- 成功、警告、错误、信息色保持现有语义。
- 移动导航新增项仅用于候选样板，不代表业务路由已经变更。
- 所有候选阴影使用中性黑透明值，并配合 `1px` 边线。

---

### Task 1: 定义候选组件与层级 token

**Files:**
- Modify: `docs/design-system/tokens.v0.2-candidate.json`
- Test: `tests/test_design_system_docs.py`

**Interfaces:**
- Consumes: V0.2 候选颜色、圆角、控件高度和既有语义色。
- Produces: `components.metricCard` 状态定义、`components.navigation` 断点定义、`tokens.shadow` 的五层候选 token。

- [ ] **Step 1: 写失败测试**

```python
assert candidate["components"]["metricCard"]["states"] == [
    "standard", "primary", "semantic", "loading"
]
assert candidate["components"]["navigation"]["mobileBottomItems"] == [
    "数据表现", "结算", "线索", "后台"
]
assert set(candidate["tokens"]["shadow"]) == {
    "shadowNone", "shadowCard", "shadowPopover", "shadowDialog", "shadowWorkbench"
}
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/test_design_system_docs.py -k component_navigation_elevation -q`

Expected: FAIL，候选 JSON 尚未定义完整的组件状态、四项底部导航和五层阴影。

- [ ] **Step 3: 写入最小 token 实现**

将需求文档中的状态、尺寸、色值和阴影角色写入候选 JSON；每个阴影 token 写清使用范围，且不保留 `rgb(31 43 36`、`rgb(23 33 28` 等旧绿色阴影。

- [ ] **Step 4: 运行 token 测试**

Run: `python -m pytest tests/test_design_system_docs.py -k component_navigation_elevation -q`

Expected: PASS。

### Task 2: 扩充候选 HTML 组件状态矩阵

**Files:**
- Modify: `docs/design-system/candidate-v0.2.html`
- Test: `tests/test_design_system_docs.py`

**Interfaces:**
- Consumes: Task 1 的候选 token 命名和用途。
- Produces: 指标卡、导航和阴影的可见样板，并由同一 CSS 自定义属性驱动。

- [ ] **Step 1: 写失败测试**

```python
for label in ("标准指标", "重点指标", "语义指标", "加载指标"):
    assert label in html
for label in ("数据表现", "结算", "线索", "后台"):
    assert label in html
for label in ("Level 0", "Level 1", "Level 2", "Level 3", "Level 4"):
    assert label in html
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/test_design_system_docs.py -k component_navigation_elevation_preview -q`

Expected: FAIL，候选 HTML 尚无完整状态矩阵和四模块底部导航。

- [ ] **Step 3: 写入组件样板**

在“组件家族”中扩充四种 MetricCard；在“页面骨架”中展示桌面 Rail、顶部二级、移动顶部二级与四项移动底部导航；新增 Elevation 区，展示每层对应组件和边线/阴影关系。复用现有 Solar 风格 SVG 样板，不引入新图标库。

- [ ] **Step 4: 收敛阴影消费点**

候选 HTML 的筛选面板与指标卡改用 `shadowCard`，下拉菜单使用 `shadowPopover`，Dialog 使用 `shadowDialog`，线索跟进工作台使用 `shadowWorkbench`；普通表格和 Chip 使用 `shadowNone`。

- [ ] **Step 5: 运行文档测试**

Run: `python -m pytest tests/test_design_system_docs.py -q`

Expected: PASS。

### Task 3: 响应式验证与阶段记录

**Files:**
- Modify: `tests/test_design_system_docs.py`
- Verify: `docs/design-system/candidate-v0.2.html`

**Interfaces:**
- Consumes: Task 1 和 Task 2 的样板。
- Produces: 响应式、候选隔离和控制台检查证据。

- [ ] **Step 1: 写断点约束测试**

```python
assert "min-height: var(--touch-target);" in mobile_navigation_css
assert "数据表现" in mobile_navigation_html
assert "business UI" not in runtime_changes
```

- [ ] **Step 2: 运行文档与门禁测试**

Run: `python -m pytest tests/test_design_system_docs.py tests/test_design_system_enforcement.py -q`

Expected: PASS。

- [ ] **Step 3: Playwright 视觉检查**

在 `390x844`、`768x1024`、`1440x1100` 打开候选 HTML，检查 `scrollWidth - innerWidth == 0`、移动底部四项可见、唯一 H1、控制台 0 errors；截图保存到已忽略的 `output/playwright/`。

- [ ] **Step 4: 更新 Linear**

在 DYDATA-3 回填文件、测试、三档视觉结果和“仍未修改业务运行时”的事实。保持 In Review，等待用户确认候选效果。

### Task 4: 提交候选规范变更

**Files:**
- Modify: `docs/design-system/candidate-v0.2.html`
- Modify: `docs/design-system/tokens.v0.2-candidate.json`
- Modify: `tests/test_design_system_docs.py`

- [ ] **Step 1: 检查 diff**

Run: `git diff --check`

Expected: 无空白错误。

- [ ] **Step 2: 提交阶段变更**

```powershell
git add docs/design-system/candidate-v0.2.html docs/design-system/tokens.v0.2-candidate.json tests/test_design_system_docs.py
git commit -m "docs: define candidate navigation and elevation"
```

- [ ] **Step 3: 保持阶段门禁**

不推送或切换业务 UI，直到用户确认候选效果和 DYDATA-3 的阶段 2 入口。
