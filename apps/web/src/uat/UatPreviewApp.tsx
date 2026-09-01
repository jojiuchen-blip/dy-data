import { useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { Dialog } from "../components/Dialog";
import {
  DateField,
  SelectField,
  TextareaField,
  TextField,
} from "../components/FormControls";
import { TertiaryNav, type TertiaryNavItem } from "../components/TertiaryNav";

type UatRoute =
  | "/ranking"
  | "/settlement"
  | "/settlement/invoice"
  | "/settlement/invoice/status";

const routes: Array<{ label: string; path: UatRoute }> = [
  { label: "全国门店榜单", path: "/ranking" },
  { label: "单店分账", path: "/settlement" },
  { label: "开票确认", path: "/settlement/invoice" },
  { label: "发票状态查看", path: "/settlement/invoice/status" },
];

const buyerReference = [
  ["名称", "比亚迪汽车销售有限公司"],
  ["纳税人识别号", "914403007604674476"],
  ["地址", "深圳市坪山新区坪山街道比亚迪路3005号"],
  ["电话", "0755-89888888"],
  ["开户行及账号", "农行龙岗支行 41022900040008463"],
  ["项目名称", "推广服务费"],
  ["税收分类编码", "3079900000000000000"],
  ["税率", "6%"],
  ["价税合计", "尚未生成"],
] as const;

const rankingMetrics = [
  "销售金额（累计）",
  "核销金额（累计）",
  "当期推广服务费",
  "累计推广服务费",
];

const rankingBasisOptions = rankingMetrics.map((label) => ({
  label,
  value: label,
}));

const settlementMetrics = [
  "销售金额",
  "核销金额",
  "当期推广服务费",
  "累计推广服务费",
  "当期管理服务费",
  "累计管理服务费",
];

const statusMetrics = [
  "账单总额",
  "已确认金额",
  "已开票金额",
  "审核通过/已结算金额",
  "待开票金额",
];

type InvoiceRhythmStep =
  | "month-end"
  | "system-check"
  | "bill-confirmation"
  | "auto-confirmation"
  | "invoice-submission"
  | "factory-review"
  | "settled";

const invoiceRhythm: Array<{
  description: string;
  id: InvoiceRhythmStep;
  label: string;
}> = [
  { description: "每月最后一日", id: "month-end", label: "月度结束" },
  { description: "次月1日", id: "system-check", label: "系统核查" },
  { description: "次月1—6日", id: "bill-confirmation", label: "账单确认" },
  { description: "次月6日24:00", id: "auto-confirmation", label: "自动确认" },
  { description: "当月10日前", id: "invoice-submission", label: "发票提交" },
  { description: "以厂端结果为准", id: "factory-review", label: "厂端审核" },
  { description: "以实际结算为准", id: "settled", label: "审核通过/已结算" },
];

function isRoute(value: string): value is UatRoute {
  return routes.some((route) => route.path === value);
}

function readRoute(): UatRoute {
  const candidate = window.location.hash.slice(1);
  return isRoute(candidate) ? candidate : "/ranking";
}

function MetricRail({ labels }: { labels: string[] }) {
  return (
    <section
      aria-label="金额指标"
      className={`uat-metric-rail uat-metric-rail--${labels.length}`}
    >
      {labels.map((label) => (
        <article className="uat-metric-card" key={label}>
          <span>{label}</span>
          <strong>暂无数据</strong>
        </article>
      ))}
    </section>
  );
}

function EmptyTable({ columns }: { columns: string[] }) {
  const tableColumns: Column<Record<string, never>>[] = columns.map((column, index) => ({
    key: `${column}-${index}`,
    title: column,
    render: () => null,
  }));

  return (
    <div className="uat-table-wrap">
      <DataTable
        columns={tableColumns}
        emptyText="暂无数据"
        mobileCard={false}
        rows={[]}
        tableClassName="uat-table"
      />
    </div>
  );
}

function ReadOnlyFilters({ children }: { children: React.ReactNode }) {
  return <section className="uat-filter-grid">{children}</section>;
}

function RankingPage() {
  const [rankingBasis, setRankingBasis] = useState("");

  return (
    <>
      <PageHeading title="全国门店月度榜单" />
      <ReadOnlyFilters>
        <SelectField
          label="统计方式"
          onChange={() => undefined}
          options={[]}
          placeholder="暂无数据"
          readOnly
          value=""
        />
        <SelectField
          label="账期"
          onChange={() => undefined}
          options={[]}
          placeholder="暂无数据"
          readOnly
          value=""
        />
        <SelectField
          label="产品范围"
          onChange={() => undefined}
          options={[]}
          placeholder="暂无数据"
          readOnly
          value=""
        />
        <TextField disabled label="搜索门店" placeholder="暂无数据" />
      </ReadOnlyFilters>
      <MetricRail labels={rankingMetrics} />
      <section className="uat-section" aria-labelledby="ranking-title">
        <div className="uat-section-heading">
          <h2 id="ranking-title">门店排名</h2>
          <SelectField
            label="排行依据"
            onChange={setRankingBasis}
            options={rankingBasisOptions}
            placeholder="请选择"
            value={rankingBasis}
          />
        </div>
        <EmptyTable
          columns={[
            "排名",
            "门店",
            "销售金额（累计）",
            "核销金额（累计）",
            "当期推广服务费",
            "累计推广服务费",
          ]}
        />
      </section>
    </>
  );
}

type FeeDetailTab = "promotion" | "management";

const disputeTypeOptions = [
  { label: "费率错误", value: "RATE_ERROR" },
  { label: "订单/数据遗漏", value: "DATA_MISSING" },
  { label: "金额错误", value: "AMOUNT_ERROR" },
  { label: "其他", value: "OTHER" },
];

function SettlementPage() {
  const [feeDirection, setFeeDirection] = useState<FeeDetailTab>("promotion");

  return (
    <>
      <PageHeading title="单店分账" />
      <ReadOnlyFilters>
        <SelectField
          label="账期"
          onChange={() => undefined}
          options={[]}
          placeholder="暂无数据"
          readOnly
          value=""
        />
        <SelectField
          label="门店"
          onChange={() => undefined}
          options={[]}
          placeholder="暂无数据"
          readOnly
          value=""
        />
      </ReadOnlyFilters>
      <MetricRail labels={settlementMetrics} />
      <section aria-label="当前账单确认" className="uat-confirmation-grid">
        <ConfirmationPanel
          action="进入推广费开票"
          title="推广服务费确认"
        />
        <ConfirmationPanel title="管理服务费确认" />
      </section>
      <FeeDetails activeTab={feeDirection} onActiveTabChange={setFeeDirection} />
      <DisputeSection feeDirection={feeDirection} />
    </>
  );
}

const feeDetailTabs: Array<{ id: FeeDetailTab; label: string }> = [
  { id: "promotion", label: "推广费明细" },
  { id: "management", label: "管理费明细" },
];

function FeeDetails({
  activeTab,
  onActiveTabChange,
}: {
  activeTab: FeeDetailTab;
  onActiveTabChange: (tab: FeeDetailTab) => void;
}) {
  const activeDetail = feeDetailTabs.find((tab) => tab.id === activeTab)!;

  return (
    <section className="uat-section uat-fee-details" aria-labelledby="fee-details-title">
      <div className="uat-section-heading uat-section-heading--tabs">
        <h2 id="fee-details-title">费用明细</h2>
        <div aria-label="费用明细类型" className="uat-fee-tabs" role="tablist">
          {feeDetailTabs.map((tab) => {
            const selected = tab.id === activeTab;
            return (
              <Button
                aria-controls={`fee-detail-panel-${tab.id}`}
                aria-selected={selected}
                className={selected ? "is-selected" : undefined}
                id={`fee-detail-tab-${tab.id}`}
                key={tab.id}
                onClick={() => onActiveTabChange(tab.id)}
                role="tab"
                size="sm"
                variant={selected ? "primary" : "secondary"}
              >
                {tab.label}
              </Button>
            );
          })}
        </div>
      </div>
      <div
        aria-labelledby={`fee-detail-tab-${activeDetail.id}`}
        className="uat-detail-empty"
        id={`fee-detail-panel-${activeDetail.id}`}
        role="tabpanel"
        tabIndex={0}
      >
        <p>暂无数据</p>
      </div>
    </section>
  );
}

type DisputeStep = "empty" | "confirm" | "form";

type DisputeFormState = {
  contactName: string;
  contactPhone: string;
  description: string;
  disputedAmount: string;
  disputeType: string;
  orders: string;
};

function DisputeSection({ feeDirection }: { feeDirection: FeeDetailTab }) {
  const [step, setStep] = useState<DisputeStep>("empty");
  const [form, setForm] = useState<DisputeFormState>({
    contactName: "",
    contactPhone: "",
    description: "",
    disputedAmount: "",
    disputeType: "",
    orders: "",
  });
  const directionLabel = feeDirection === "promotion" ? "推广服务费" : "管理服务费";
  const updateField = (field: keyof DisputeFormState, value: string) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  return (
    <section
      className={`uat-dispute-section${step === "empty" ? "" : " uat-dispute-section--open"}`}
      aria-label="账单异议"
    >
      {step === "empty" ? (
        <div className="uat-dispute-entry">
          <span className="uat-dispute-label">账单异议</span>
          <span className="uat-dispute-empty">暂无可发起的账单异议</span>
          <Button
            className="uat-dispute-trigger"
            onClick={() => setStep("confirm")}
            size="sm"
            variant="text"
          >
            发起账单异议
          </Button>
        </div>
      ) : null}

      <Dialog
        actions={
          <div className="uat-dispute-dialog__actions">
            <Button onClick={() => setStep("empty")} size="sm" variant="secondary">
              取消
            </Button>
            <Button onClick={() => setStep("form")} size="sm" variant="primary">
              确认发起
            </Button>
          </div>
        }
        backdropClassName="uat-dispute-modal"
        onClose={() => setStep("empty")}
        open={step === "confirm"}
        panelClassName="uat-dispute-dialog"
        title="确认发起账单异议"
      >
        <span className="uat-dispute-eyebrow">提交前确认</span>
        <p>发起异议前请准备充分资料，是否发起？</p>
      </Dialog>

      <Dialog
        backdropClassName="uat-dispute-modal"
        onClose={() => setStep("empty")}
        open={step === "form"}
        panelClassName="uat-dispute-form"
        title={`发起${directionLabel}账单异议`}
      >
        <div className="uat-dispute-form__heading">
          <div>
            <span className="uat-dispute-eyebrow">异常分支</span>
          </div>
          <Button onClick={() => setStep("empty")} size="sm" variant="text">
            返回账单详情
          </Button>
        </div>
        <p className="uat-dispute-form__direction">
          当前费用方向：<strong>{directionLabel}</strong>（由费用明细页签确定）
        </p>
        <div className="uat-form-grid uat-dispute-form-grid">
          <SelectField
            label="异议类型"
            onChange={(value) => updateField("disputeType", value)}
            options={disputeTypeOptions}
            value={form.disputeType}
          />
          <TextField
            data-api-field="disputedAmountCent"
            inputMode="decimal"
            label="争议金额"
            onChange={(event) => updateField("disputedAmount", event.target.value)}
            placeholder="请填写"
            value={form.disputedAmount}
          />
          <TextField
            data-api-field="contactName"
            label="联系人"
            onChange={(event) => updateField("contactName", event.target.value)}
            placeholder="请填写"
            value={form.contactName}
          />
          <TextField
            data-api-field="contactPhone"
            inputMode="tel"
            label="手机号"
            onChange={(event) => updateField("contactPhone", event.target.value)}
            placeholder="请填写"
            value={form.contactPhone}
          />
          <TextareaField
            data-api-field="orders"
            fieldClassName="uat-dispute-form__wide"
            helperText="提交时由服务端校验订单归属、券范围和争议金额合计。"
            label="争议订单"
            onChange={(event) => updateField("orders", event.target.value)}
            placeholder="请填写需核对的订单或券范围"
            value={form.orders}
          />
          <TextareaField
            data-api-field="description"
            fieldClassName="uat-dispute-form__wide"
            label="问题说明"
            onChange={(event) => updateField("description", event.target.value)}
            placeholder="请填写问题说明"
            value={form.description}
          />
          <TextField
            data-api-field="evidence"
            disabled
            fieldClassName="uat-dispute-form__wide"
            helperText="证明资料需先取得受控对象键；当前环境不上传文件。"
            label="证明材料"
            type="file"
          />
        </div>
        <div className="uat-dispute-form__actions">
          <span>暂无正式账单或受控证明资料，当前不能提交异议。</span>
          <Button disabled size="md" variant="primary">
            提交异议并开始检测
          </Button>
        </div>
      </Dialog>
    </section>
  );
}

function ConfirmationPanel({
  action,
  title,
}: {
  action?: string;
  title: string;
}) {
  return (
    <section className="uat-confirmation-panel">
      <div>
        <h2>{title}</h2>
        <strong>尚未生成</strong>
      </div>
      {action ? (
        <Button disabled size="md" variant="primary">
          {action}
        </Button>
      ) : null}
    </section>
  );
}

function InvoiceRhythm({ currentStep }: { currentStep?: InvoiceRhythmStep }) {
  return (
    <section className="uat-invoice-rhythm" aria-label="开票时间节奏">
      <ol>
        {invoiceRhythm.map((step) => {
          const isCurrent = step.id === currentStep;
          return (
            <li
              aria-current={isCurrent ? "step" : undefined}
              className={`uat-invoice-rhythm__step${isCurrent ? " is-current" : ""}`}
              key={step.id}
            >
              <strong>{step.label}</strong>
              <span>{step.description}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function InvoicePage() {
  const [copyMessage, setCopyMessage] = useState("");
  const copyReference = async () => {
    const text = buyerReference.map(([label, value]) => `${label}：${value}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopyMessage("已复制开票信息。");
    } catch {
      setCopyMessage("当前环境无法复制，请手动填写。");
    }
  };

  return (
    <>
      <PageHeading title="开票确认" />
      <section className="uat-invoice-notice" aria-label="开票提醒">
        <p>门店前往开票系统开具数电专票，再将发票信息上传系统，否则将无法收款。</p>
        <p>当月10号前开票提交，当月结算；10号后开票提交将在下月结算。</p>
      </section>
      <InvoiceRhythm currentStep="invoice-submission" />
      <section className="uat-invoice-grid">
        <article className="uat-invoice-panel" aria-labelledby="buyer-reference-title">
          <div className="uat-panel-heading">
            <h2 id="buyer-reference-title">收票方与开票信息</h2>
            <Button onClick={() => void copyReference()} size="sm" variant="secondary">
              复制全部开票信息
            </Button>
          </div>
          <dl className="uat-reference-list">
            {buyerReference.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          {copyMessage ? <p className="uat-copy-message" role="status">{copyMessage}</p> : null}
        </article>

        <article className="uat-invoice-panel" aria-labelledby="invoice-form-title">
          <div className="uat-panel-heading">
            <h2 id="invoice-form-title">填写数电专票信息</h2>
          </div>
          <div className="uat-form-grid">
            <TextField label="购买方名称" placeholder="请填写" />
            <TextField inputMode="tel" label="填写人电话" placeholder="请填写" />
            <TextField inputMode="decimal" label="税率" placeholder="请填写" />
            <DateField label="开票日期" />
            <TextField inputMode="numeric" label="20 位数电专票号码" placeholder="请填写" />
            <TextField inputMode="decimal" label="不含税金额" placeholder="请填写" step="0.001" type="number" />
            <TextField inputMode="decimal" label="税额" placeholder="请填写" step="0.001" type="number" />
            <TextField inputMode="decimal" label="价税合计" placeholder="请填写" step="0.001" type="number" />
          </div>
          <Button className="uat-submit" disabled size="md" variant="primary">
            校验并登记发票
          </Button>
        </article>
      </section>
    </>
  );
}

function InvoiceStatusPage() {
  return (
    <>
      <PageHeading title="发票状态查看" />
      <section className="uat-search-row">
        <TextField label="发票号码" placeholder="请输入完整发票号码" readOnly />
        <Button disabled size="md" variant="secondary">
          服务端精确查询
        </Button>
      </section>
      <MetricRail labels={statusMetrics} />
      <StatusSection columns={["账期", "发票号码", "发票状态", "审核结果", "原因", "结算归属"]} title="推广发票记录" />
      <StatusSection columns={["服务名称", "账期", "发票号码", "开票日期", "发票状态"]} title="管理服务费发票信息" />
      <StatusSection columns={["来源账期", "差额原因", "差额金额", "目标账期"]} title="差额台账" />
    </>
  );
}

function StatusSection({ columns, title }: { columns: string[]; title: string }) {
  return (
    <section className="uat-section" aria-labelledby={`${title}-title`}>
      <h2 id={`${title}-title`}>{title}</h2>
      <EmptyTable columns={columns} />
    </section>
  );
}

function PageHeading({ title }: { title: string }) {
  return (
    <header className="uat-page-heading">
      <p>门店端</p>
      <h1>{title}</h1>
    </header>
  );
}

function PageContent({ route }: { route: UatRoute }) {
  if (route === "/settlement") return <SettlementPage />;
  if (route === "/settlement/invoice") return <InvoicePage />;
  if (route === "/settlement/invoice/status") return <InvoiceStatusPage />;
  return <RankingPage />;
}

export function UatPreviewApp() {
  const [route, setRoute] = useState<UatRoute>(readRoute);

  useEffect(() => {
    const handleRouteChange = () => setRoute(readRoute());
    window.addEventListener("hashchange", handleRouteChange);
    return () => window.removeEventListener("hashchange", handleRouteChange);
  }, []);

  const navItems = useMemo<TertiaryNavItem[]>(
    () =>
      routes.map((item) => ({
        current: item.path === route,
        href: `#${item.path}`,
        label: item.label,
      })),
    [route],
  );

  return (
    <div className="uat-shell">
      <aside className="uat-rail" aria-label="主模块导航">
        <div className="uat-brand">经营引擎</div>
        <nav className="uat-rail-nav" aria-label="系统模块">
          <span>线索中心</span>
          <span>核销表现</span>
          <strong>订单分佣</strong>
          <span>后台</span>
        </nav>
      </aside>
      <div className="uat-workspace">
        <header className="uat-topbar">
          <TertiaryNav items={navItems} label="订单分佣导航" />
        </header>
        <main className="uat-page-frame">
          <PageContent route={route} />
        </main>
      </div>
    </div>
  );
}
