# DYDATA-5 Mobile Page Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the V0.2 candidate specification show genuine clue and order mobile page templates at 390px and 768px while keeping desktop wide-table samples out of narrow layouts.

**Architecture:** Keep desktop and mobile demonstrations as separate semantic groups in the same standalone HTML. CSS breakpoint swapping hides desktop-only samples at `max-width: 920px`; mobile templates use cards, filter states, compact paging, top subnavigation, and four-item bottom navigation. Static pytest assertions protect the contract and Playwright verifies rendered geometry.

**Tech Stack:** Standalone HTML/CSS, JSON design tokens, Python pytest, Playwright CLI.

## Global Constraints

- Do not modify `apps/web/src` or runtime UI.
- Do not change V0.2 color, typography, radius, shadow, or component contracts.
- Desktop wide tables remain desktop-only and are never compressed into mobile layouts.
- Mobile touch targets are at least 44px.
- Do not commit or push until the user explicitly requests it.

---

### Task 1: Lock the responsive page-template contract

**Files:**
- Modify: `tests/test_design_system_docs.py`
- Test: `tests/test_design_system_docs.py`

**Interfaces:**
- Consumes: `docs/design-system/candidate-v0.2.html` class and copy hooks.
- Produces: `test_candidate_mobile_page_templates_replace_desktop_workspaces_on_narrow_screens`.

- [ ] **Step 1: Write the failing test**

```python
def test_candidate_mobile_page_templates_replace_desktop_workspaces_on_narrow_screens() -> None:
    html = read_text(CANDIDATE_HTML_PATH)

    assert 'class="desktop-template-stack"' in html
    assert 'class="mobile-template-stack"' in html
    assert 'class="mobile-data-page mobile-data-page--clues"' in html
    assert 'class="mobile-data-page mobile-data-page--orders"' in html
    assert 'class="mobile-filter-panel is-expanded"' in html
    assert html.count('class="mobile-record-card') >= 4
    assert html.count('class="mobile-data-pager"') == 2
    assert html.count('class="mobile-navigation-item') >= 12
    assert "桌面模板仅在 921px 以上展示" in html
    assert "上一页" in html and "下一页" in html

    narrow_media = html.split("@media (max-width: 920px)", 1)[1]
    assert ".desktop-template-stack" in narrow_media
    assert "display: none;" in narrow_media
    assert ".mobile-template-stack" in narrow_media
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_design_system_docs.py::test_candidate_mobile_page_templates_replace_desktop_workspaces_on_narrow_screens -q`

Expected: FAIL because the new semantic groups and mobile page templates do not exist.

---

### Task 2: Implement the mobile page-template samples

**Files:**
- Modify: `docs/design-system/candidate-v0.2.html`
- Modify: `docs/design-system/tokens.v0.2-candidate.json`
- Test: `tests/test_design_system_docs.py`

**Interfaces:**
- Consumes: existing `StatusChip`, `FilterChip`, `Button`, mobile navigation, spacing, color, and shadow tokens.
- Produces: `.desktop-template-stack`, `.mobile-template-stack`, `.mobile-data-page`, `.mobile-filter-panel`, `.mobile-record-card`, and `.mobile-data-pager` preview contracts.

- [ ] **Step 1: Group desktop-only samples**

Wrap the existing desktop Shell and both `.data-workspace-demo` blocks in:

```html
<div class="desktop-template-stack" aria-label="桌面页面骨架样板">
  <!-- existing desktop shell and desktop data workspaces -->
</div>
```

At `max-width: 920px`, set `.desktop-template-stack { display: none; }` and show a concise `.desktop-template-note` explaining that desktop samples are available above 920px.

- [ ] **Step 2: Add the clue mobile page template**

Create `.mobile-data-page--clues` with:

```html
<div class="mobile-data-page mobile-data-page--clues">
  <div class="mobile-subnav-demo">线索看板 / 线索明细</div>
  <main class="mobile-data-page__body">
    <header class="mobile-data-page__heading">线索跟进列表 / 共 22,525 条</header>
    <button class="mobile-filter-trigger" type="button">筛选 · 已选 2 项</button>
    <div class="mobile-filter-summary">省份：浙江 / 状态：待跟进</div>
    <div class="mobile-record-list">two clue cards</div>
    <div class="mobile-data-pager">上一页 / editable page / 下一页</div>
  </main>
  <div class="mobile-nav-demo">数据表现 / 结算 / 线索 / 后台</div>
</div>
```

Each clue card exposes status, round, contact, product, follow-up time, created time, and a full-width detail action.

- [ ] **Step 3: Add the order mobile page template**

Create `.mobile-data-page--orders` with settlement subnavigation, an expanded `.mobile-filter-panel.is-expanded`, two order cards, the same compact pager contract, and the four-item bottom navigation with settlement active.

- [ ] **Step 4: Add responsive styling**

```css
.mobile-template-stack {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 390px));
  justify-content: center;
  gap: 16px;
}

@media (max-width: 920px) {
  .desktop-template-stack { display: none; }
  .mobile-template-stack { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 640px) {
  .mobile-template-stack { grid-template-columns: 1fr; }
}
```

All mobile controls use `min-height: var(--touch-target)`, record cards use `min-width: 0`, and pager labels use `white-space: nowrap`.

- [ ] **Step 5: Record machine-readable mobile template rules**

Add a `pageTemplates.mobileDetailWorkspace` rule to `tokens.v0.2-candidate.json` with breakpoint `920px`, presentation `record-cards`, pager controls `previous/page-input/next`, top subnavigation, and four bottom navigation modules. This follows the candidate JSON's existing page-template ownership boundary instead of inventing a component token namespace.

- [ ] **Step 6: Run the targeted test and verify GREEN**

Run: `python -m pytest tests/test_design_system_docs.py::test_candidate_mobile_page_templates_replace_desktop_workspaces_on_narrow_screens -q`

Expected: PASS.

---

### Task 3: Browser and regression verification

**Files:**
- Verify: `docs/design-system/candidate-v0.2.html`
- Verify: `apps/web/src/**` remains unchanged

**Interfaces:**
- Consumes: rendered candidate HTML.
- Produces: screenshots and geometry evidence under ignored `output/playwright/`.

- [ ] **Step 1: Run static and full tests**

```powershell
python -m pytest tests/test_design_system_docs.py tests/test_design_system_enforcement.py -q
python -m pytest -q
npm --prefix apps/web run build
git diff --check
```

Expected: all tests and build pass; `git diff --name-only -- apps/web/src` is empty.

- [ ] **Step 2: Verify 390px and 768px**

Use Playwright CLI to confirm:

- `.desktop-template-stack` is hidden.
- `.mobile-template-stack`, both mobile page samples, record cards, compact pagers, top subnavigation, and four-item bottom navigation are visible.
- Page and each `.mobile-data-page` have `scrollWidth == clientWidth`.
- Console errors equal 0.

- [ ] **Step 3: Verify 1440px**

Confirm desktop Shell and both desktop data workspaces remain visible, mobile samples remain available as references, and there is no global horizontal overflow.

- [ ] **Step 4: Update Linear**

Add a DYDATA-5 comment with changed files, 390/768/1440 evidence, test results, and confirmation that runtime UI was untouched. Move to `In Review` only after all checks pass.
