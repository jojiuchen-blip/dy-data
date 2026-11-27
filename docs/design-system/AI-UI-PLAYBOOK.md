# dy-data AI 前端视觉速查手册（AI-UI-PLAYBOOK）

> 面向 **Codex CLI / Antigravity** 协作者的轻量执行契约。写任何页面或板块前必须先读本页；完整 Token 定义见 `tokens.json`，组件预览见 `runtime-catalog.html`。

## 一、五条不可突破铁律

1. **0 新增页面私有 CSS**：新增或改写业务页面禁止新建 `*.css` 文件，禁止在 `styles.css` 追加页面私有类或裸 `px` 间距/字号/圆角，禁止写任何颜色字面量（hex/rgb/hsl/oklch）。
2. **只拼白名单原语，严禁卡套卡**：板块统一使用 `apps/web/src/components/layout` 原语；`<SectionCard>` 内禁止再嵌套 `<SectionCard>`，内部分组用 `tone="recessed"` 或分割线。
3. **保留既有核心规范（红线）**：
   - **图标**：唯一入口 `SolarIcon`（`apps/web/src/components/SolarIcon.tsx`），线性默认、`bold-duotone` 仅用于激活主导航/品牌；禁止直接导入 `@iconify/*` 或手绘 `<svg>` / Unicode 假图标。
   - **表格与表头锁定**：唯一入口 `DataTable`（`apps/web/src/components/DataTable.tsx`），自动保留表头锁定（`position: sticky; top: 0`）与冻结首列（`sticky: true`）；明细长表必须使用 `SectionCard workspace` + `stickyHeader="container"` + `TablePagination`，外层视口不纵向滚动。
   - **图表**：唯一入口 `EChartsFigure`（`apps/web/src/components/charts/`）且必须来自 `index.html#chart-gallery`。
   - **品牌署名**：仅用 `BrandAttribution`，禁止 UI 字体替排或改色。
   - **控件**：业务页禁止原生 `<input>` / `<textarea>` / `<button>` / `<select>` / `<table>` / `<div onClick>`；文件上传必须用 `FileDropzone`。
4. **温润现代克制原则**：同一主视图（弹窗外）最多 **1 个** `variant="primary"` 品牌橙主按钮；提示条用 `CalloutBanner` 柔和浅底，不堆砌粗橙边框。
5. **财务级表格语义对齐**：
   - 文本/名称：`align: "left"`
   - 编码/SAP/SKU/发票号：`align: "left", mono: true, nowrap: true`
   - 金额/数量：`align: "right", numeric: true`（自动等宽数字 + 不折行）
   - 账期/日期：`nowrap: true`（禁止把 `2026-08` 折成两行）
   - 状态列：统一使用 `<StatusChip tone="...">`，禁止裸黑字混排。

## 二、白名单组合原语速查

```tsx
import {
  PageHeader,     // 页眉：eyebrow / 唯一 H1 title / description / meta / actions
  SectionCard,    // 板块容器：title / description / actions / tone="default|recessed" / workspace
  MetricStrip,    // 指标卡栅格：columns={3|4|5|6}，内部放 MetricCard
  CalloutBanner,  // 提醒横幅：tone="neutral|info|warm|warning|success|danger|brand"
  SplitWorkspace, // 双栏工作区：ratio="balanced|detail-form|main-aside"
  KeyValueGrid,   // 只读资料清单：支持 mono / numeric / SolarIcon 单行复制
  FileDropzone,   // 文件拖拽/选择上传（替代原生 input type="file"）
  SwitchField,    // 品牌橙语义开关（role="switch"）
} from "../components/layout";
```

基础零件继续使用：`Button` / `IconButton`、`TextField` / `DateField` / `SelectField` / `MultiSelectField` / `CheckboxField`、`FilterBar` / `FilterField`、`Tabs` / `SegmentedControl` / `TertiaryNav`、`MetricCard`、`StatusChip` / `CountPill`、`DataTable` / `TablePagination`、`Dialog` / `ConfirmDialog`、`ResourceNotice` / `ResourcePanel`。

## 三、四套标准页面配方（先选配方再写代码）

### 配方 1：经营 / 财务列表页（如 `FinanceFeePage`）
```tsx
<div className="page-stack">
  <PageHeader eyebrow="模块名" title="页面标题" description="一句业务口径" actions={<>次按钮 + 唯一主按钮</>} />
  <ResourceNotice loading={loading} error={error} />
  <MetricStrip columns={4}>{/* 4 张等高 MetricCard */}</MetricStrip>
  <FilterBar>{/* 筛选字段 + 右侧重置 */}</FilterBar>
  <SectionCard title="明细列表" actions={<>导出/历史版本</>}>
    <DataTable columns={semanticColumns} rows={rows} />
    <TablePagination {...paginationProps} />
  </SectionCard>
</div>
```

### 配方 2：流程与表单工作区（如 `StoreInvoicePage`）
```tsx
<div className="page-stack">
  <PageHeader eyebrow="模块名" title="操作标题" />
  <CalloutBanner tone="warm">关键时效或规则提醒</CalloutBanner>
  {/* 可选：StoreFinanceTimeline 进度条 */}
  <SplitWorkspace ratio="detail-form">
    <SectionCard title="左栏：只读参考资料"><KeyValueGrid items={items} /></SectionCard>
    <SectionCard title="右栏：登记/提交表单">{/* FormControls + 唯一主按钮 */}</SectionCard>
  </SplitWorkspace>
</div>
```

### 配方 3：多区块后台配置页（如 `AdminSkuRulesPage`）
- 按任务频次使用 `Tabs` 或 `SegmentedControl` 分区，**禁止在一页竖排超过 3 张高操作密度大卡**；低频历史兼容区默认收口到独立 Tab 或折叠区。
- 批量文件导入统一放进 `Dialog` 抽屉或独立 `SectionCard`，内部文件选择必须使用 `FileDropzone`。

### 配方 4：桌面定高明细工作台（如 `/clues/details`、`/details`）
- 外层保留 `page-frame--data-workspace` 视口定高，`SectionCard workspace` 包裹 `DataTable stickyHeader="container"`，分页 `TablePagination` 放在滚动容器外底部常驻可见。

## 四、提交前必跑检查

```powershell
npm --prefix apps/web run build
python -m pytest -q tests/test_design_system_docs.py tests/test_design_system_enforcement.py tests/test_frontend_theme_brand.py tests/test_frontend_user_facing_contracts.py
```

涉及布局或新板块时，另需用 Playwright 核对 1440 / 768 / 390 与浅色/深色双主题无溢出、无套娃框、无表头遮挡。
