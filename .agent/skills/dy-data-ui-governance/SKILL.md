---
name: dy-data-ui-governance
description: Mandatory UI and visual-system governance skill for Codex and Antigravity collaborators working in apps/web/. Enforces Warm Modern layout primitives, 4 page recipes, zero new page-private CSS, and preserves SolarIcon, DataTable sticky headers, ChartFigure, and BrandAttribution contracts.
---

# dy-data UI 视觉一致性治理技能（Codex & Antigravity 共享）

凡涉及 `apps/web/` 下新增页面、新增板块、调整表单/表格/卡片布局或修改样式，**必须先执行本技能**，再编写任何前端代码。

## 强制执行流程

### 1. 读取速查契约（低成本、高命中）
先阅读 `docs/design-system/AI-UI-PLAYBOOK.md`（约 110 行），无需盲读 8,000+ 行 `styles.css`。若需查阅单个组件 Props 或 Token，再按需检索 `docs/design-system/components.json` 与 `apps/web/src/design-tokens.css`。

### 2. 选配方、拼原语（禁止自由造布局 CSS）
1. 从 `AI-UI-PLAYBOOK.md` 的 **4 套标准页面配方** 中选定当前任务对应的骨架：
   - 配方 1：经营 / 财务列表页
   - 配方 2：流程与表单工作区
   - 配方 3：多区块后台配置页
   - 配方 4：桌面定高明细工作台（长表必选）
2. 页面结构统一从 `apps/web/src/components/layout` 组合原语（`PageHeader`、`SectionCard`、`MetricStrip`、`CalloutBanner`、`SplitWorkspace`、`KeyValueGrid`、`FileDropzone`、`SwitchField`）。
3. **默认 0 新增 `.css` 文件**：CI 棘轮门禁已冻结历史 CSS 白名单，新增页面私有 `.css` 会直接失败。若确实需要新的跨页通用原语，必须先新增到 `apps/web/src/components/layout/`、登记到 `docs/design-system/components.json`、在 `DesignSystemCatalog.tsx` 补真实预览并执行 `npm --prefix apps/web run build:design-system`。

### 3. 严格保留的核心规范（不得破坏）
- **图标**：只能通过 `SolarIcon` 引用（默认线性，`bold-duotone` 仅用于激活主导航/品牌），严禁在页面直接写 `<svg>` 或导入 `@iconify/*`。
- **表格与表头锁定**：只能使用 `DataTable`，完整保留 `sticky` 首列冻结、`stickyHeader="container"` 表头锁定和 `TablePagination` 外置分页；金额/数量列必须声明 `align: "right", numeric: true`，编码列声明 `mono: true, nowrap: true`，账期/日期列声明 `nowrap: true`，状态列用 `StatusChip`。
- **图表与品牌**：图表统一走 `EChartsFigure` 且登记于 `chart-gallery/`；署名统一走 `BrandAttribution`。
- **反漂移红线**：
  - 禁止 `<SectionCard>` 嵌套 `<SectionCard>`（内部分组改用 `tone="recessed"`）。
  - 同一主视图（弹窗外）最多 1 个 `variant="primary"` 品牌橙主按钮。
  - 禁止裸 `<input>` / `<textarea>` / `<button>` / `<select>` / `<table>` / `<div onClick>` / 原生文件选择框。
  - 禁止在任何业务 TS/TSX/CSS 中写颜色字面量（hex/rgb/hsl/oklch）。

### 4. 提交前必跑验证
```powershell
npm --prefix apps/web run build
python -m pytest -q tests/test_design_system_docs.py tests/test_design_system_enforcement.py tests/test_frontend_theme_brand.py tests/test_frontend_user_facing_contracts.py
```

若改动了页面结构或新增板块，须在本地或测试环境核验 **1440 / 768 / 390** 宽度及 **浅色 / 深色** 双主题的渲染效果，确认无横向溢出、无套娃框、表头锁定与分页正常后再提交 PR。
