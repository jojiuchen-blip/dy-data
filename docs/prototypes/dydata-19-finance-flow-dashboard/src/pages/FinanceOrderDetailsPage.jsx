import { useMemo, useState } from "react";
import { WorkbenchToolbar } from "../components/DataWorkbench.jsx";
import { StatusTag } from "../components/StatusTag.jsx";
import { financeOrderDetails } from "../data/financeData.js";
import { exportAllFields } from "../domain/csvExport.js";
import { money } from "../domain/financeRules.js";

const fieldDefinitions = {
  "账期": "正常明细按原业务时间归属；退款负数行按退款时间所在月份归属。",
  "账单归属门店": "来源于订单归属结果，展示门店名称及门店ID。",
  "服务店名称": "由财务基础信息模板按门店ID映射；历史账期保留当时快照。",
  "有效 SAP": "来源于基础信息或SAP差异确认结果，仅影响后续新账期。",
  "订单": "来源于抖音订单明细的订单ID。",
  "券": "来源于抖音订单明细的券ID。",
  "状态": "依次展示订单状态和券状态。",
  "商品": "来源于订单商品名称。",
  "SKU ID": "来源于订单明细中的SKU唯一标识。",
  "商品类型": "来源于商品分类配置。",
  "销售渠道": "来源于订单销售渠道，当前包括直播和短视频。",
  "销售门店": "来源于订单销售归属门店。",
  "核销门店": "来源于券核销记录中的实际核销门店。",
  "销售时间": "来源于订单支付或销售成功时间。",
  "核销时间": "来源于券核销成功时间。",
  "退款时间": "仅退款负数行有值；用于计算退款所属账期。",
  "实收金额": "正常交易为正数；退款生成独立负数行，不覆盖原交易。",
  "实际费率": "取订单命中且在业务发生时有效的费率版本。",
  "原始费用": "按该行实收金额乘以实际费率，以分为单位四舍五入。",
  "对应发票号码": "随对应账期最新发票状态更新。",
  "发票提交时间": "门店在系统提交推广费发票信息的成功时间；管理费取财务导入时间。",
  "发票审核状态": "展示当前最新厂家审核或开票处理状态。",
  "发票结算日期": "审核通过或厂家扣款完成后更新；审核不通过时为空。",
  "审核不通过原因": "仅发票审核不通过时填写。",
};

function statusTone(status) {
  if (status.includes("不通过") || status === "未结算") return "danger";
  if (status.includes("通过") || status === "已结算" || status === "已开票") return "success";
  return "warning";
}

function inDateRange(value, from, to) {
  if (!from && !to) return true;
  if (!value || value === "—") return false;
  const date = value.slice(0, 10);
  return (!from || date >= from) && (!to || date <= to);
}

function FieldHeader({ label, onOpen }) {
  return (
    <th aria-label={label}>
      <span className="field-header">
        <span>{label}</span>
        <button type="button" aria-label={`查看${label}字段说明`} title="查看字段来源与计算逻辑" onClick={() => onOpen(label)}>!</button>
      </span>
    </th>
  );
}

function FinanceOrderDetailsPage({ direction, returnPage, onNavigate, onDirectionChange }) {
  const [search, setSearch] = useState("");
  const [period, setPeriod] = useState("全部账期");
  const [channel, setChannel] = useState("全部渠道");
  const [invoiceStatus, setInvoiceStatus] = useState("全部状态");
  const [settlementStatus, setSettlementStatus] = useState("全部状态");
  const [submittedFrom, setSubmittedFrom] = useState("");
  const [submittedTo, setSubmittedTo] = useState("");
  const [verifiedFrom, setVerifiedFrom] = useState("");
  const [verifiedTo, setVerifiedTo] = useState("");
  const [activeField, setActiveField] = useState(null);
  const [exportNotice, setExportNotice] = useState("");

  const sourceRows = financeOrderDetails.filter((row) => row.feeDirection === direction);
  const rows = useMemo(() => sourceRows.filter((row) => {
    const haystack = `${row.billingStoreId}${row.billingStoreName}${row.serviceStoreName}${row.effectiveSap}${row.orderId}${row.couponId}${row.productName}${row.skuId}${row.invoiceNumber}`.toLowerCase();
    return haystack.includes(search.toLowerCase())
      && (period === "全部账期" || row.period === period)
      && (channel === "全部渠道" || row.saleChannel === channel)
      && (invoiceStatus === "全部状态" || row.invoiceAuditStatus === invoiceStatus)
      && (settlementStatus === "全部状态" || row.settlementStatus === settlementStatus)
      && inDateRange(row.submittedAt, submittedFrom, submittedTo)
      && inDateRange(row.verifyTime, verifiedFrom, verifiedTo);
  }), [sourceRows, search, period, channel, invoiceStatus, settlementStatus, submittedFrom, submittedTo, verifiedFrom, verifiedTo]);

  const hasActiveFilters = Boolean(
    search.trim()
      || period !== "全部账期"
      || channel !== "全部渠道"
      || invoiceStatus !== "全部状态"
      || settlementStatus !== "全部状态"
      || submittedFrom
      || submittedTo
      || verifiedFrom
      || verifiedTo,
  );

  function exportDetails() {
    const count = exportAllFields(rows, `${direction}-订单明细.csv`);
    setExportNotice(hasActiveFilters
      ? `已导出符合当前筛选条件的数据，共 ${count} 条`
      : `已导出全部数据，共 ${count} 条`);
  }

  const headers = Object.keys(fieldDefinitions);

  return (
    <section className="business-page" aria-labelledby="finance-order-details-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">{onDirectionChange ? "财务二级页面" : "财务三级页面"} · 全量门店订单核算</span>
          <h1 id="finance-order-details-title">{direction}订单明细</h1>
          <p>沿用门店订单明细；退款独立生成实收金额为负数的新行，发票状态更新后同步刷新对应订单记录。</p>
        </div>
        <div className="page-heading__actions">
          {returnPage ? <button type="button" className="button button--secondary" onClick={() => onNavigate?.(returnPage)}>返回{direction}</button> : null}
          <button type="button" className="button button--primary" onClick={exportDetails}>导出数据</button>
        </div>
      </header>

      {onDirectionChange ? (
        <div className="segmented-tabs page-tabs order-detail-tabs" role="tablist" aria-label="订单明细类型">
          <button type="button" role="tab" aria-selected={direction === "推广服务费"} onClick={() => onDirectionChange("推广服务费")}>推广服务费明细</button>
          <button type="button" role="tab" aria-selected={direction === "管理服务费"} onClick={() => onDirectionChange("管理服务费")}>管理服务费明细</button>
        </div>
      ) : null}

      <div className="export-guidance">
        <strong>导出文件包含全部底层字段</strong>
        <span>页面展示核算主字段；导出同时包含订单、券、费率、账期、发票与结算底层字段。</span>
      </div>

      <WorkbenchToolbar onSearch={setSearch} searchLabel="搜索门店、SAP、发票号码、订单ID或SKU ID">
        <label className="filter-control"><span>筛选账期</span><select aria-label="筛选账期" value={period} onChange={(event) => setPeriod(event.target.value)}><option>全部账期</option><option>2026-07</option><option>2026-06</option></select></label>
        <label className="filter-control"><span>销售渠道</span><select aria-label="销售渠道" value={channel} onChange={(event) => setChannel(event.target.value)}><option>全部渠道</option><option>直播</option><option>短视频</option></select></label>
        <label className="filter-control"><span>发票审核状态</span><select aria-label="发票审核状态" value={invoiceStatus} onChange={(event) => setInvoiceStatus(event.target.value)}><option>全部状态</option>{[...new Set(sourceRows.map((row) => row.invoiceAuditStatus))].map((value) => <option key={value}>{value}</option>)}</select></label>
        <label className="filter-control"><span>结算状态</span><select aria-label="结算状态" value={settlementStatus} onChange={(event) => setSettlementStatus(event.target.value)}><option>全部状态</option><option>未结算</option><option>已结算</option></select></label>
        <fieldset className="date-range-filter" aria-label="发票提交日期范围">
          <legend>发票提交日期范围</legend>
          <div className="date-range-filter__inputs">
            <input aria-label="开始日期" type="date" value={submittedFrom} onChange={(event) => setSubmittedFrom(event.target.value)} />
            <span aria-hidden="true">至</span>
            <input aria-label="结束日期" type="date" value={submittedTo} onChange={(event) => setSubmittedTo(event.target.value)} />
          </div>
        </fieldset>
        <fieldset className="date-range-filter" aria-label="核销日期范围">
          <legend>核销日期范围</legend>
          <div className="date-range-filter__inputs">
            <input aria-label="开始日期" type="date" value={verifiedFrom} onChange={(event) => setVerifiedFrom(event.target.value)} />
            <span aria-hidden="true">至</span>
            <input aria-label="结束日期" type="date" value={verifiedTo} onChange={(event) => setVerifiedTo(event.target.value)} />
          </div>
        </fieldset>
      </WorkbenchToolbar>
      {activeField ? <div className="field-help-panel" role="status"><div><strong>{activeField}</strong><span>{fieldDefinitions[activeField]}</span></div><button type="button" className="text-button" onClick={() => setActiveField(null)}>关闭说明</button></div> : null}
      {exportNotice ? <div className="inline-notice" role="status">{exportNotice}</div> : null}

      <div className="data-table-wrap data-table-wrap--wide finance-order-table">
        <table>
          <thead><tr>{headers.map((header) => <FieldHeader key={header} label={header} onOpen={setActiveField} />)}</tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={row.receivedAmount < 0 ? "is-refund-row" : ""}>
                <td>{row.period}</td>
                <td><strong>{row.billingStoreName}</strong><small>{row.billingStoreId}</small></td>
                <td>{row.serviceStoreName}</td><td>{row.effectiveSap}</td>
                <td><strong>{row.orderId}</strong></td><td>{row.couponId}</td><td>{row.orderStatus} / {row.couponStatus}</td>
                <td><strong>{row.productName}</strong></td><td>{row.skuId}</td><td>{row.productType}</td><td>{row.saleChannel}</td>
                <td>{row.saleStoreName}</td><td>{row.verifyStoreName}</td><td>{row.saleTime}</td><td>{row.verifyTime}</td><td>{row.refundTime}</td>
                <td className="amount">{money(row.receivedAmount)}</td><td>{row.feeRate}</td><td className="amount">{money(row.originalFee)}</td><td>{row.invoiceNumber}</td><td>{row.submittedAt}</td>
                <td><StatusTag tone={statusTone(row.invoiceAuditStatus)}>{row.invoiceAuditStatus}</StatusTag></td><td>{row.settlementDate}</td><td>{row.rejectionReason}</td>
              </tr>
            ))}
            {!rows.length ? <tr><td colSpan={headers.length}>当前筛选下暂无订单明细</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function FinanceOrdersPage({ direction = "推广服务费", onDirectionChange, ...props }) {
  return <FinanceOrderDetailsPage {...props} direction={direction} onDirectionChange={onDirectionChange} />;
}
