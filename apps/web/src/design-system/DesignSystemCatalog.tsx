import { useMemo, useState, type ReactNode } from "react";
import manifestSource from "../../../../docs/design-system/components.json";
import { Button, IconButton } from "../components/Button";
import {
  CycleJitterChart,
  MonthlyRainfallChart,
} from "../components/charts/SalesCharts";
import {
  type ChipTone,
  CountPill,
  FilterChip,
  RoleBadge,
  StatusChip,
} from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import { DefinitionList } from "../components/DefinitionList";
import { ConfirmDialog, Dialog } from "../components/Dialog";
import { FilterBar, FilterField } from "../components/Filters";
import {
  CheckboxField,
  DateField,
  FieldInput,
  FieldTextarea,
  MultiSelectField,
  PasswordField,
  SelectField,
  TextareaField,
  TextField,
} from "../components/FormControls";
import { MetricCard } from "../components/MetricCard";
import { ResourceNotice, ResourcePanel } from "../components/ResourceState";
import { SearchableStoreSelect } from "../components/SearchableStoreSelect";
import {
  SegmentedControl,
  SummaryFilter,
  Tabs,
} from "../components/SelectionControls";
import { SolarIcon } from "../components/SolarIcon";
import { SpaceAiSignature } from "../components/SpaceAiSignature";
import { TablePagination } from "../components/TablePagination";
import { TertiaryNav } from "../components/TertiaryNav";
import { ThemePicker } from "../components/ThemePicker";
import { TooltipLabel } from "../components/TooltipLabel";
import type {
  SalesCycleDistributionRow,
  SalesTrendRow,
} from "../types/dashboard";

interface ManifestComponent {
  accessibility: string;
  category: string;
  description: string;
  exportName: string;
  family: string;
  id: string;
  implementationPath: string;
  name: string;
  previewAnchor: string;
  responsive: string;
  states: string[];
  status: string;
  tokens: string[];
  useWhen: string;
  avoidWhen: string;
}

interface ComponentManifest {
  components: ManifestComponent[];
  designSystemVersion: string;
  updatedAt: string;
}

interface CatalogRow {
  channel: string;
  name: string;
  status: string;
  tone: ChipTone;
}

const manifest = manifestSource as ComponentManifest;

const familyLabels: Record<string, string> = {
  Actions: "操作",
  Brand: "品牌",
  "Data display": "数据展示",
  Feedback: "反馈",
  Fields: "表单",
  Foundations: "基础",
  Navigation: "导航",
  Overlays: "弹层",
};

const componentLabels: Record<string, string> = {
  button: "按钮（Button）",
  chips: "标签体系（StatusChip 等）",
  "data-table": "数据表格（DataTable）",
  "chart-figure": "业务图表（ChartFigure）",
  "definition-list": "定义列表（DefinitionList）",
  dialog: "弹层与确认弹层（Dialog / ConfirmDialog）",
  "icon-button": "图标按钮（IconButton）",
  "field-input": "基础输入控件（FieldInput / FieldTextarea）",
  "filter-bar": "筛选器（FilterBar / FilterField）",
  "metric-card": "指标卡（MetricCard）",
  "multi-select-field": "多选字段（MultiSelectField）",
  "resource-state": "资源状态（ResourceNotice / ResourcePanel）",
  "searchable-store-select": "可检索门店选择器（SearchableStoreSelect）",
  "select-field": "单选字段（SelectField）",
  "selection-controls": "选择与切换（Tabs / SegmentedControl / SummaryFilter）",
  shell: "全局页面壳层（Shell）",
  "solar-icon": "Solar 图标",
  "space-ai-signature": "SPACE AI Native 项目署名",
  "table-pagination": "表格分页（TablePagination）",
  "tertiary-nav": "三级导航（TertiaryNav）",
  "text-fields": "完整字段（文本 / 日期 / 密码 / 多行 / 复选）",
  "theme-picker": "主题切换（ThemePicker）",
  "tooltip-label": "辅助说明（TooltipLabel）",
};

const stateLabels: Record<string, string> = {
  active: "按下",
  brand: "品牌",
  busy: "处理中",
  "bold-duotone": "双色粗体",
  closed: "关闭",
  confirm: "确认",
  checked: "已选中",
  current: "当前页",
  danger: "危险",
  default: "默认",
  disabled: "禁用",
  empty: "空状态",
  error: "错误",
  fallback: "降级数据",
  "first-page": "首页",
  "focus-visible": "键盘聚焦",
  horizontal: "横排",
  hover: "悬停",
  info: "信息",
  "invalid-page": "无效页码",
  "last-page": "末页",
  light: "浅色",
  linear: "线性",
  linked: "可跳转",
  loading: "加载中",
  "middle-page": "中间页",
  neutral: "中性",
  open: "展开",
  readOnly: "只读",
  ready: "就绪",
  selected: "已选",
  stacked: "纵排",
  success: "成功",
  system: "跟随系统",
  typing: "输入中",
  warning: "警告",
  dark: "深色",
};

const iconLabels = {
  copy: "复制",
  details: "详情",
  eye: "查看",
  eyeClosed: "隐藏",
  filter: "筛选",
  logout: "退出",
  settings: "设置",
} as const;

const getComponentLabel = (component: ManifestComponent) => componentLabels[component.id] ?? component.name;
const getFamilyLabel = (family: string) => familyLabels[family] ?? family;
const getStateLabel = (state: string) => stateLabels[state] ?? state;

const sampleColumns: Column<CatalogRow>[] = [
  { key: "channel", title: "联系方式", width: 160, sticky: true, render: (row) => row.channel },
  { key: "status", title: "线索状态", width: 130, render: (row) => <StatusChip tone={row.tone}>{row.status}</StatusChip> },
  { key: "name", title: "商品名称", align: "left", minWidth: 260, render: (row) => <strong>{row.name}</strong> },
  { key: "action", title: "操作", width: 110, render: () => <Button size="sm" variant="text">查看详情</Button> },
];

const sampleRows: CatalogRow[] = [
  { channel: "139****8502", name: "精诚养车基础保养套餐", status: "待跟进", tone: "info" },
  { channel: "159****2267", name: "无骨雨刮赠送副胶条", status: "已跟进", tone: "success" },
  { channel: "137****8842", name: "精洗内饰护理双次卡", status: "已跟进", tone: "success" },
  { channel: "136****7019", name: "米其林轮胎到店安装服务", status: "已核销", tone: "success" },
  { channel: "135****9320", name: "精诚养车四轮定位检测", status: "主动战败", tone: "warning" },
  { channel: "138****1186", name: "全车打蜡洗美套餐", status: "超期失效", tone: "danger" },
];

const sampleTrendRows: SalesTrendRow[] = [
  { month: "2026-01", order_count: 128, verify_order_count: 96 },
  { month: "2026-02", order_count: 152, verify_order_count: 113 },
  { month: "2026-03", order_count: 146, verify_order_count: 121 },
  { month: "2026-04", order_count: 178, verify_order_count: 139 },
  { month: "2026-05", order_count: 169, verify_order_count: 148 },
  { month: "2026-06", order_count: 201, verify_order_count: 166 },
];

const sampleCycleRows: SalesCycleDistributionRow[] = [
  {
    avg_days: 3.4,
    count: 4,
    max_days: 7,
    median_days: 3,
    min_days: 1,
    product_type: "保养服务",
    q1_days: 2,
    q3_days: 5,
    sample_points: [
      { cycle_days: 1, order_id: "CATALOG-001", sale_time: "2026-06-01", verify_time: "2026-06-02" },
      { cycle_days: 3, order_id: "CATALOG-002", sale_time: "2026-06-02", verify_time: "2026-06-05" },
      { cycle_days: 5, order_id: "CATALOG-003", sale_time: "2026-06-04", verify_time: "2026-06-09" },
      { cycle_days: 7, order_id: "CATALOG-004", sale_time: "2026-06-08", verify_time: "2026-06-15" },
    ],
  },
  {
    avg_days: 5.3,
    count: 4,
    max_days: 10,
    median_days: 5,
    min_days: 2,
    product_type: "洗美服务",
    q1_days: 3,
    q3_days: 8,
    sample_points: [
      { cycle_days: 2, order_id: "CATALOG-005", sale_time: "2026-06-01", verify_time: "2026-06-03" },
      { cycle_days: 4, order_id: "CATALOG-006", sale_time: "2026-06-03", verify_time: "2026-06-07" },
      { cycle_days: 6, order_id: "CATALOG-007", sale_time: "2026-06-05", verify_time: "2026-06-11" },
      { cycle_days: 10, order_id: "CATALOG-008", sale_time: "2026-06-08", verify_time: "2026-06-18" },
    ],
  },
];

function ActionPreview() {
  return (
    <div className="catalog-preview-row">
      <Button icon="filter" variant="primary">应用筛选</Button>
      <Button variant="secondary">清空筛选</Button>
      <Button variant="soft">实时数据</Button>
      <Button variant="danger">删除规则</Button>
      <Button loading variant="primary">保存中</Button>
      <Button disabled variant="secondary">不可用</Button>
    </div>
  );
}

function IconActionPreview() {
  return (
    <div className="catalog-preview-row">
      <IconButton icon="eye" label="查看完整号码" />
      <IconButton icon="copy" label="复制号码" />
      <IconButton icon="close" label="关闭弹层" />
      <IconButton disabled icon="trash" label="删除不可用" variant="danger" />
    </div>
  );
}

function SelectPreview() {
  const [value, setValue] = useState("all");
  return (
    <div className="catalog-field-grid">
      <SelectField
        label="省份"
        onChange={setValue}
        options={[
          { label: "全部", value: "all" },
          { label: "浙江", meta: "12,482", value: "zhejiang" },
          { label: "江苏", meta: "4,206", value: "jiangsu" },
        ]}
        value={value}
      />
      <SelectField
        error="截止日期不能早于起始日期。"
        label="错误态"
        onChange={() => undefined}
        options={[{ label: "2026/06/20", value: "date" }]}
        value="date"
      />
    </div>
  );
}

function FieldInputPreview() {
  return (
    <div className="catalog-field-grid">
      <label className="filter-field">
        <span>关键词</span>
        <FieldInput defaultValue="精诚养车" type="search" />
      </label>
      <label className="filter-field">
        <span>补充说明</span>
        <FieldTextarea defaultValue="已有字段结构迁移时，可先复用基础输入控件。" rows={3} />
      </label>
    </div>
  );
}

function TextFieldsPreview() {
  const [name, setName] = useState("精诚养车杭州城东店");
  const [date, setDate] = useState("2026-07-28");
  const [password, setPassword] = useState("design-system");
  const [note, setNote] = useState("用户可理解的说明，不展示内部生产标签。");
  const [enabled, setEnabled] = useState(true);

  return (
    <div className="catalog-field-grid">
      <TextField label="门店名称" onChange={(event) => setName(event.target.value)} value={name} />
      <DateField label="生效日期" onChange={(event) => setDate(event.target.value)} value={date} />
      <PasswordField helperText="密码默认隐藏，不回显内部凭据。" label="访问密码" onChange={(event) => setPassword(event.target.value)} value={password} />
      <TextField error="请输入完整名称。" label="错误状态" value="" readOnly />
      <TextareaField label="备注" onChange={(event) => setNote(event.target.value)} rows={3} value={note} />
      <CheckboxField checked={enabled} description="用于可逆、非危险的二元设置。" label="启用自动同步" onChange={(event) => setEnabled(event.target.checked)} />
    </div>
  );
}

function MultiSelectPreview() {
  const [value, setValue] = useState(["pending", "followed"]);
  return (
    <MultiSelectField
      helperText="多值筛选保留清晰的已选摘要。"
      label="线索状态"
      onChange={setValue}
      options={[
        { label: "待跟进", value: "pending" },
        { label: "已跟进", value: "followed" },
        { label: "已核销", value: "verified" },
      ]}
      value={value}
    />
  );
}

function SearchablePreview() {
  const [value, setValue] = useState("hz");
  return (
    <div className="catalog-searchable-preview">
      <FilterField label="门店">
        <SearchableStoreSelect
          allowEmpty
          onChange={setValue}
          options={[
            { label: "精诚养车杭州城东店", value: "hz" },
            { label: "精诚养车宁波海曙店", value: "nb" },
            { label: "比亚迪汽车王朝网浙江旗舰店", value: "byd" },
          ]}
          value={value}
        />
      </FilterField>
    </div>
  );
}

function FilterBarPreview() {
  const [province, setProvince] = useState("all");
  const [status, setStatus] = useState("pending");
  return (
    <FilterBar className="catalog-filter-bar">
      <SelectField
        label="省份"
        onChange={setProvince}
        options={[{ label: "全部", value: "all" }, { label: "浙江", value: "zhejiang" }]}
        value={province}
      />
      <SelectField
        label="线索状态"
        onChange={setStatus}
        options={[{ label: "待跟进", value: "pending" }, { label: "已跟进", value: "followed" }]}
        value={status}
      />
      <Button variant="secondary">清空筛选</Button>
    </FilterBar>
  );
}

function SelectionControlsPreview() {
  const [tab, setTab] = useState("overview");
  const [mode, setMode] = useState("month");
  const [summary, setSummary] = useState("all");
  return (
    <div className="catalog-selection-stack">
      <Tabs
        ariaLabel="线索模块视图"
        onChange={setTab}
        options={[{ label: "线索看板", value: "overview" }, { label: "线索明细", value: "details" }]}
        value={tab}
      />
      <SegmentedControl
        ariaLabel="统计周期"
        onChange={setMode}
        options={[{ label: "按月", value: "month" }, { label: "按季度", value: "quarter" }]}
        value={mode}
      />
      <SummaryFilter
        ariaLabel="反馈状态"
        onChange={setSummary}
        options={[{ count: 24, label: "全部", value: "all" }, { count: 6, label: "待处理", value: "pending" }]}
        value={summary}
      />
    </div>
  );
}

function ChipsPreview() {
  return (
    <div className="catalog-preview-row">
      <StatusChip tone="info">待跟进</StatusChip>
      <StatusChip tone="success">已跟进</StatusChip>
      <StatusChip tone="warning">待再分配</StatusChip>
      <StatusChip tone="danger">错误</StatusChip>
      <CountPill>共 22,332 条</CountPill>
      <RoleBadge tone="brand">最高管理员</RoleBadge>
      <FilterChip>省份：浙江</FilterChip>
    </div>
  );
}

function MetricPreview() {
  return (
    <div className="catalog-metric-grid">
      <MetricCard label="线索总数" meta="筛选范围内订单粒度" value="22,525" />
      <MetricCard label="可跟进线索" meta="仍需门店处理" value="21,732" />
      <MetricCard label="待处理" meta="战败或超期" value="126" />
    </div>
  );
}

function ChartFigurePreview() {
  return (
    <div className="catalog-chart-grid">
      <section aria-label="月度趋势图预览">
        <strong>月度下单与核销趋势</strong>
        <MonthlyRainfallChart rows={sampleTrendRows} />
      </section>
      <section aria-label="核销周期分布图预览">
        <strong>核销周期分布</strong>
        <CycleJitterChart rows={sampleCycleRows} />
      </section>
    </div>
  );
}

function TablePreview() {
  return (
    <DataTable
      columns={sampleColumns}
      mobileCard={false}
      rows={sampleRows}
      stickyHeader="container"
    />
  );
}

function PaginationPreview() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  return (
    <TablePagination
      onPageChange={setPage}
      onPageSizeChange={setPageSize}
      page={page}
      pageSize={pageSize}
      pageSizeOptions={[20, 50, 100]}
      rowsOnPage={20}
      total={22332}
      totalPages={Math.ceil(22332 / pageSize)}
    />
  );
}

function DialogPreview() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  return (
    <>
      <div className="catalog-preview-row">
        <Button onClick={() => setDialogOpen(true)} variant="primary">打开详情弹层</Button>
        <Button onClick={() => setConfirmOpen(true)} variant="danger">打开危险确认</Button>
      </div>
      <Dialog
        actions={<Button onClick={() => setDialogOpen(false)} variant="primary">完成</Button>}
        description="真实 Dialog 组件会管理焦点、Esc、背景隔离和关闭回焦。"
        onClose={() => setDialogOpen(false)}
        open={dialogOpen}
        title="线索详情"
      >
        <p>弹层内容继续使用 Field、DefinitionList 和 Button 等基础组件。</p>
      </Dialog>
      <ConfirmDialog
        confirmLabel="删除规则"
        danger
        description="不可逆操作必须明确对象与后果。"
        message="删除后该 SKU 将不再按当前分佣规则参与计算。"
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => setConfirmOpen(false)}
        open={confirmOpen}
        title="删除分佣规则？"
      />
    </>
  );
}

function ResourcePreview() {
  return (
    <div className="catalog-resource-stack">
      <ResourceNotice fallbackReason="服务暂不可用，当前展示演示数据。" />
      <ResourcePanel>正在加载最新数据...</ResourcePanel>
      <ResourcePanel tone="error">数据加载失败，请稍后重试。</ResourcePanel>
    </div>
  );
}

function TertiaryPreview() {
  return (
    <TertiaryNav
      items={[
        { current: true, href: "#catalog-tertiary-nav", label: "核销概览" },
        { href: "#catalog-tertiary-nav", label: "趋势分析" },
        { href: "#catalog-tertiary-nav", label: "门店结构" },
        { disabled: true, href: "#catalog-tertiary-nav", label: "预测" },
      ]}
      label="指标分析视图"
    />
  );
}

function ThemePickerPreview() {
  return <ThemePicker />;
}

function TooltipPreview() {
  return (
    <div className="catalog-preview-row">
      <TooltipLabel description="已完成核销且满足当前归属规则的订单金额。" label="核销收入" />
      <TooltipLabel description="从销售订单生成到完成核销的平均天数。" label="平均核销周期" />
    </div>
  );
}

function DefinitionPreview() {
  return (
    <DefinitionList
      definitions={[
        { key: "scope", label: "产品范围", description: "用于界定统计口径覆盖的商品集合。" },
        { key: "verified", label: "核销收入", description: "按已完成核销且满足归属规则的订单统计。" },
      ]}
      title="指标口径"
    />
  );
}

function IconPreview() {
  const icons = ["eye", "eyeClosed", "copy", "details", "filter", "settings", "logout"] as const;
  return (
    <div className="catalog-icon-grid">
      {icons.map((name) => (
        <span key={name}><SolarIcon name={name === "settings" ? "rules" : name} size={22} />{iconLabels[name]}</span>
      ))}
    </div>
  );
}

function SignaturePreview() {
  return (
    <div className="catalog-signature-row">
      <SpaceAiSignature />
      <SpaceAiSignature variant="stacked" />
    </div>
  );
}

const previews: Record<string, () => ReactNode> = {
  button: ActionPreview,
  "icon-button": IconActionPreview,
  "field-input": FieldInputPreview,
  "select-field": SelectPreview,
  "text-fields": TextFieldsPreview,
  "multi-select-field": MultiSelectPreview,
  "searchable-store-select": SearchablePreview,
  "filter-bar": FilterBarPreview,
  "selection-controls": SelectionControlsPreview,
  chips: ChipsPreview,
  "metric-card": MetricPreview,
  "chart-figure": ChartFigurePreview,
  "data-table": TablePreview,
  "table-pagination": PaginationPreview,
  dialog: DialogPreview,
  "resource-state": ResourcePreview,
  "tertiary-nav": TertiaryPreview,
  "theme-picker": ThemePickerPreview,
  "tooltip-label": TooltipPreview,
  "definition-list": DefinitionPreview,
  "solar-icon": IconPreview,
  "space-ai-signature": SignaturePreview,
};

function ComponentSpecCard({ component }: { component: ManifestComponent }) {
  const Preview = previews[component.id];
  return (
    <article className="catalog-component" id={component.previewAnchor}>
      <header className="catalog-component__header">
        <div>
          <span className="catalog-component__family">{getFamilyLabel(component.family)}</span>
          <h2>{getComponentLabel(component)}</h2>
          <p>{component.description}</p>
        </div>
        <StatusChip tone={component.status === "stable" ? "success" : "warning"}>{component.status === "stable" ? "已稳定" : "待完善"}</StatusChip>
      </header>
      <div className="catalog-component__preview" aria-label={`${getComponentLabel(component)}真实组件预览`}>
        {Preview ? <Preview /> : <p className="catalog-no-preview">该组件已登记，交互预览将在实际业务页面中验收。</p>}
      </div>
      <div className="catalog-component__guidance">
        <div><strong>适用</strong><p>{component.useWhen}</p></div>
        <div><strong>避免</strong><p>{component.avoidWhen}</p></div>
        <div><strong>状态</strong><p>{component.states.map(getStateLabel).join(" / ")}</p></div>
        <div><strong>可访问性</strong><p>{component.accessibility}</p></div>
        <div><strong>响应式</strong><p>{component.responsive}</p></div>
        <div><strong>运行时来源</strong><p><code>{component.implementationPath}#{component.exportName}</code></p></div>
      </div>
    </article>
  );
}

export function DesignSystemCatalog() {
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const components = useMemo(
    () => manifest.components.filter((component) => {
      if (!normalizedQuery) return true;
      return [
        component.name,
        getComponentLabel(component),
        component.family,
        getFamilyLabel(component.family),
        component.description,
        component.useWhen,
        component.avoidWhen,
        ...component.states.map(getStateLabel),
      ]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    }),
    [normalizedQuery],
  );
  const families = [...new Set(manifest.components.map((component) => component.family))];

  return (
    <div className="catalog-shell">
      <aside className="catalog-sidebar">
        <a className="catalog-back" href="./index.html#components">返回规范总览</a>
        <div className="catalog-sidebar__title">
          <strong>真实组件展厅</strong>
          <span>V{manifest.designSystemVersion} · {manifest.updatedAt}</span>
        </div>
        <label className="catalog-search">
          <span>检索组件</span>
          <FieldInput onChange={(event) => setQuery(event.target.value)} placeholder="名称、用途或状态" type="search" value={query} />
        </label>
        <nav aria-label="组件家族">
          {families.map((family) => (
            <div className="catalog-nav-group" key={family}>
              <strong>{getFamilyLabel(family)}</strong>
              {manifest.components.filter((component) => component.family === family).map((component) => (
                <a href={`#${component.previewAnchor}`} key={component.id}>{getComponentLabel(component)}</a>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <main className="catalog-main">
        <header className="catalog-hero">
          <div>
            <span>运行中组件</span>
            <h1>组件清单与真实运行时展厅</h1>
            <p>以下预览直接导入 <code>apps/web/src/components</code>，样式来自业务运行时设计变量与样式表。</p>
          </div>
          <CountPill tone="brand">{components.length} / {manifest.components.length} 个组件</CountPill>
        </header>
        <section className="catalog-contract" aria-label="组件说明模板">
          <strong>统一说明结构</strong>
          <span>用途 → 真实预览 → 适用 → 避免 → 状态 → 可访问性 → 响应式 → 运行时来源</span>
        </section>
        <div className="catalog-list">
          {components.length ? components.map((component) => <ComponentSpecCard component={component} key={component.id} />) : (
            <ResourcePanel tone="error">未找到匹配组件，请调整检索词。</ResourcePanel>
          )}
        </div>
      </main>
    </div>
  );
}
