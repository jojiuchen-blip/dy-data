# dy-data V0.2 Tertiary Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved page-local underline tertiary navigation pattern to the V0.2 design-system token source, complete HTML gallery, decision log, and regression tests without changing runtime business pages.

**Architecture:** Extend the existing `components.navigation` contract instead of creating a competing navigation namespace. The HTML preview renders route-like `<nav><a>` examples for settlement pages, entity details, and mobile overflow; pytest validates semantics, state styling, token values, and responsive targets.

**Tech Stack:** Standalone HTML/CSS, JSON design tokens, Python pytest, Playwright browser QA.

## Global Constraints

- This phase changes only V0.2 visual-system artifacts and tests; do not modify `apps/web/src`, runtime routes, backend APIs, or permissions.
- Tertiary navigation represents stable subpages with stable URLs; filters and transient display modes must not use this component.
- Use `<nav aria-label="..."><a href="..." aria-current="page">`; do not use `role="tablist"`, fake clickable spans, or buttons.
- Desktop item height is `38px`; mobile touch target is at least `44px`.
- Current state uses deep-orange text plus a `2px` brand-orange underline; hover uses soft orange and focus uses the global focus ring.
- Groups contain 2–5 items. Mobile may scroll the navigation row horizontally without causing page-level horizontal overflow.
- Tertiary navigation is not independently sticky and does not change table sticky offsets.
- V0.2 remains light-only.

---

### Task 1: Machine-readable tertiary navigation contract

**Files:**
- Modify: `tests/test_design_system_docs.py`
- Modify: `docs/design-system/tokens.v0.2-candidate.json`

**Interfaces:**
- Consumes: existing `candidate["components"]["navigation"]` and `candidate["pageTemplates"]` objects.
- Produces: `components.navigation.tertiary` and `pageTemplates.tertiaryNavigation` contracts used by the HTML preview test and future runtime migration.

- [ ] **Step 1: Write the failing token contract test**

Add after `test_candidate_component_navigation_and_elevation_samples_follow_tokens`:

```python
def test_candidate_tertiary_navigation_contract_is_route_based_and_responsive() -> None:
    candidate = json.loads(read_text(CANDIDATE_TOKENS_PATH))

    tertiary = candidate["components"]["navigation"]["tertiary"]
    assert tertiary == {
        "semanticRole": "local page navigation",
        "structure": "nav > a",
        "currentState": "aria-current=page",
        "desktopItemHeight": "38px",
        "mobileMinTarget": "44px",
        "activeText": "#d63b00",
        "activeIndicator": "2px solid #fe5205",
        "hoverBackground": "#fff4ef",
        "itemRange": "2-5",
        "mobileOverflow": "horizontal scroll with current item visible",
        "sticky": "not independently sticky",
        "forbiddenUses": [
            "filters",
            "transient display modes",
            "tablist without stable URLs",
        ],
    }

    template = candidate["pageTemplates"]["tertiaryNavigation"]
    assert template["desktopPlacement"] == "after page heading and before filters or content"
    assert template["detailPlacement"] == "after entity heading and summary"
    assert template["mobilePlacement"] == "after page heading and before content"
    assert template["routingRule"] == "Every item has a stable URL and supports refresh, deep links, and browser history."
    assert template["stickyRule"] == "Do not add an independent sticky layer or change table sticky offsets."
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests\test_design_system_docs.py::test_candidate_tertiary_navigation_contract_is_route_based_and_responsive -q
```

Expected: FAIL with `KeyError: 'tertiary'`.

- [ ] **Step 3: Add the component and page-template tokens**

Inside `components.navigation`, after `desktopSubnav`, add:

```json
"tertiary": {
  "semanticRole": "local page navigation",
  "structure": "nav > a",
  "currentState": "aria-current=page",
  "desktopItemHeight": "38px",
  "mobileMinTarget": "44px",
  "activeText": "#d63b00",
  "activeIndicator": "2px solid #fe5205",
  "hoverBackground": "#fff4ef",
  "itemRange": "2-5",
  "mobileOverflow": "horizontal scroll with current item visible",
  "sticky": "not independently sticky",
  "forbiddenUses": [
    "filters",
    "transient display modes",
    "tablist without stable URLs"
  ]
},
```

Inside `pageTemplates`, before `listPage`, add:

```json
"tertiaryNavigation": {
  "appliesTo": [
    "stable subpages inside one secondary workspace",
    "entity detail subpages"
  ],
  "desktopPlacement": "after page heading and before filters or content",
  "detailPlacement": "after entity heading and summary",
  "mobilePlacement": "after page heading and before content",
  "routingRule": "Every item has a stable URL and supports refresh, deep links, and browser history.",
  "stickyRule": "Do not add an independent sticky layer or change table sticky offsets."
},
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```powershell
python -m pytest tests\test_design_system_docs.py::test_candidate_tertiary_navigation_contract_is_route_based_and_responsive -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit the token contract**

```powershell
git add -- docs/design-system/tokens.v0.2-candidate.json tests/test_design_system_docs.py
git diff --cached --check
git commit -m "docs: define V0.2 tertiary navigation contract"
```

---

### Task 2: Complete HTML gallery and responsive examples

**Files:**
- Modify: `tests/test_design_system_docs.py`
- Modify: `docs/design-system/candidate-v0.2.html`

**Interfaces:**
- Consumes: `components.navigation.tertiary`, existing V0.2 color, spacing, typography, focus, and mobile breakpoint tokens.
- Produces: visible `TertiaryNav / 三级导航` samples for page, detail, mobile, and component states.

- [ ] **Step 1: Write the failing HTML semantics and state test**

Add after the token contract test:

```python
def test_candidate_tertiary_navigation_gallery_uses_links_and_complete_states() -> None:
    html = read_text(CANDIDATE_HTML_PATH)

    assert "TertiaryNav / 三级导航" in html
    assert 'class="tertiary-nav-showcase"' in html
    assert 'aria-label="结算数据子页面"' in html
    assert 'aria-label="账号详情子页面"' in html
    assert 'class="tertiary-nav tertiary-nav--mobile"' in html
    assert 'href="#settlement-ranking" aria-current="page"' in html
    assert 'href="#account-profile" aria-current="page"' in html
    assert 'class="tertiary-nav__item is-hover"' in html
    assert 'class="tertiary-nav__item is-focus"' in html
    assert 'class="tertiary-nav__item is-disabled" aria-disabled="true"' in html
    assert 'role="tablist"' not in html

    base = re.search(
        r"\.tertiary-nav__item \{(?P<css>.*?)\n\s*\}", html, re.DOTALL
    )
    current = re.search(
        r"\.tertiary-nav__item\[aria-current=\"page\"\] \{(?P<css>.*?)\n\s*\}",
        html,
        re.DOTALL,
    )
    mobile = re.search(
        r"@media \(max-width: 920px\).*?\.tertiary-nav__item \{(?P<css>.*?)\n\s*\}",
        html,
        re.DOTALL,
    )
    assert base is not None
    assert "min-height: 38px;" in base.group("css")
    assert current is not None
    assert "border-bottom-color: var(--brand-accent);" in current.group("css")
    assert "color: var(--brand-primary);" in current.group("css")
    assert mobile is not None
    assert "min-height: var(--touch-target);" in mobile.group("css")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests\test_design_system_docs.py::test_candidate_tertiary_navigation_gallery_uses_links_and_complete_states -q
```

Expected: FAIL because `TertiaryNav / 三级导航` is absent.

- [ ] **Step 3: Add the reusable gallery CSS**

Add near the existing `.subnav-item` rules:

```css
.tertiary-nav-showcase {
  display: grid;
  gap: 18px;
}

.tertiary-nav-context {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.tertiary-nav-context__heading {
  display: grid;
  gap: 3px;
}

.tertiary-nav {
  display: flex;
  align-items: end;
  gap: 4px;
  min-width: 0;
  overflow-x: auto;
  border-bottom: 1px solid var(--line);
  scrollbar-width: thin;
}

.tertiary-nav__item {
  display: inline-flex;
  min-height: 38px;
  flex: 0 0 auto;
  align-items: center;
  border-bottom: 2px solid transparent;
  padding: 0 10px;
  color: var(--muted);
  font-size: var(--font-body);
  font-weight: var(--weight-medium);
  text-decoration: none;
  white-space: nowrap;
}

.tertiary-nav__item:hover,
.tertiary-nav__item.is-hover {
  background: var(--brand-soft);
  color: var(--ink);
}

.tertiary-nav__item:focus-visible,
.tertiary-nav__item.is-focus {
  position: relative;
  z-index: 1;
  box-shadow: var(--focus-ring);
}

.tertiary-nav__item[aria-current="page"] {
  border-bottom-color: var(--brand-accent);
  color: var(--brand-primary);
  font-weight: var(--weight-bold);
}

.tertiary-nav__item.is-disabled {
  color: var(--muted);
  opacity: 0.48;
  pointer-events: none;
}

.tertiary-nav-state-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
```

Inside the existing `@media (max-width: 920px)` block add:

```css
.tertiary-nav--mobile {
  margin-inline: -14px;
  padding-inline: 14px;
}

.tertiary-nav__item {
  min-height: var(--touch-target);
}
```

- [ ] **Step 4: Add page, detail, mobile, and state samples**

Add a wide component card after `NavigationItem / 导航项`:

```html
<article class="component-card component-card--wide">
  <h3>TertiaryNav / 三级导航</h3>
  <div class="tertiary-nav-showcase">
    <section class="tertiary-nav-context" aria-labelledby="tertiary-settlement-title">
      <div class="tertiary-nav-context__heading">
        <strong id="tertiary-settlement-title">页面型 · 结算数据</strong>
        <span>二级工作区合并后，三级入口仍保持独立 URL。</span>
      </div>
      <nav class="tertiary-nav" aria-label="结算数据子页面">
        <a class="tertiary-nav__item" href="#settlement-ranking" aria-current="page">全国门店榜单</a>
        <a class="tertiary-nav__item" href="#settlement-stores">单店结算</a>
        <a class="tertiary-nav__item" href="#settlement-orders">订单明细</a>
      </nav>
    </section>
    <section class="tertiary-nav-context" aria-labelledby="tertiary-account-title">
      <div class="tertiary-nav-context__heading">
        <strong id="tertiary-account-title">详情型 · 账号详情</strong>
        <span>位于实体标题和摘要之后、详情正文之前。</span>
      </div>
      <nav class="tertiary-nav" aria-label="账号详情子页面">
        <a class="tertiary-nav__item" href="#account-profile" aria-current="page">基本信息</a>
        <a class="tertiary-nav__item" href="#account-permissions">权限配置</a>
        <a class="tertiary-nav__item" href="#account-activity">操作记录</a>
      </nav>
    </section>
    <section class="tertiary-nav-context">
      <strong>组件状态</strong>
      <div class="tertiary-nav-state-row">
        <a class="tertiary-nav__item" href="#state-default">默认</a>
        <a class="tertiary-nav__item is-hover" href="#state-hover">Hover</a>
        <a class="tertiary-nav__item is-focus" href="#state-focus">Focus</a>
        <a class="tertiary-nav__item" href="#state-current" aria-current="page">当前</a>
        <span class="tertiary-nav__item is-disabled" aria-disabled="true">禁用</span>
      </div>
    </section>
    <section class="tertiary-nav-context">
      <strong>移动端 · 横向导航</strong>
      <nav class="tertiary-nav tertiary-nav--mobile" aria-label="移动端结算数据子页面">
        <a class="tertiary-nav__item" href="#mobile-ranking" aria-current="page">全国门店榜单</a>
        <a class="tertiary-nav__item" href="#mobile-stores">单店结算</a>
        <a class="tertiary-nav__item" href="#mobile-orders">订单明细</a>
      </nav>
    </section>
  </div>
  <p>三级导航只承载稳定子页面；筛选条件使用 FilterChip，临时展示模式使用 segmented control。普通页面随内容滚动，明细工作台通过内部表格滚动自然保持可见。</p>
</article>
```

- [ ] **Step 5: Add the decision-log row**

Add before the “设计规范执行” row:

```html
<tr>
  <td>三级导航</td>
  <td>页面标题下方的水平链接；2–5 项；桌面 38px，移动 44px；当前项为深橙文字和 2px 品牌橙下划线</td>
  <td><span class="status-chip success">V0.2 候选已确认</span></td>
  <td>只用于稳定 URL 子页面，不用于筛选、临时视图或第四级导航。</td>
</tr>
```

- [ ] **Step 6: Run the focused and design-system tests**

Run:

```powershell
python -m pytest tests\test_design_system_docs.py::test_candidate_tertiary_navigation_gallery_uses_links_and_complete_states -q
python -m pytest tests\test_design_system_docs.py tests\test_design_system_enforcement.py -q
```

Expected: focused test `1 passed`; design-system suite all passes.

- [ ] **Step 7: Commit the gallery**

```powershell
git add -- docs/design-system/candidate-v0.2.html tests/test_design_system_docs.py
git diff --cached --check
git commit -m "docs: preview V0.2 tertiary navigation"
```

---

### Task 3: Visual and full regression verification

**Files:**
- Verify: `docs/design-system/candidate-v0.2.html`
- Verify: `docs/design-system/tokens.v0.2-candidate.json`
- Verify: `tests/test_design_system_docs.py`

**Interfaces:**
- Consumes: completed token and gallery contracts from Tasks 1–2.
- Produces: verified V0.2 documentation ready for human visual review.

- [ ] **Step 1: Run complete automated verification**

```powershell
python -m pytest -q
npm --prefix apps/web run build
git diff --check
```

Expected: all pytest tests pass, Vite build succeeds, and `git diff --check` prints no errors.

- [ ] **Step 2: Inspect desktop, tablet, and mobile rendering**

Serve the design-system directory and inspect `candidate-v0.2.html#components` at `1440x1000`, `768x1024`, and `390x844`.

For each width verify:

```text
- page-type, detail-type, state, and mobile samples are visible
- the active underline stays 2px and does not shift layout
- focus ring is not clipped
- long labels remain complete
- only the tertiary row scrolls horizontally at 390px
- document scrollWidth equals clientWidth
- no tertiary item overlaps adjacent content
```

- [ ] **Step 3: Confirm runtime scope remains untouched**

```powershell
git diff --name-only -- apps/web/src
```

Expected: no output.

- [ ] **Step 4: Record final status**

Report the exact test counts, build result, visual widths checked, modified files, and that business UI migration remains deferred.
