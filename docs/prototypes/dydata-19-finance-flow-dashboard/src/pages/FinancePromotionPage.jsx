import { useMemo, useState } from "react";
import { MetricStrip, WorkbenchToolbar } from "../components/DataWorkbench.jsx";
import { StatusTag } from "../components/StatusTag.jsx";
import { promotionInvoices } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";

function statusTone(status) {
  if (status.includes("通过")) return "success";
  if (status.includes("不通过")) return "danger";
  return "warning";
}

export function FinancePromotionPage({ scenario }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("全部状态");
  const rows = useMemo(() => promotionInvoices.filter((row) => {
    const matchesSearch = `${row.store}${row.effectiveSap}${row.invoiceNumber}`.toLowerCase().includes(search.toLowerCase());
    return matchesSearch && (status === "全部状态" || row.auditStatus === status);
  }), [search, status]);

  const total = promotionInvoices.reduce((sum, row) => sum + row.totalFee, 0);
  const passed = promotionInvoices.filter((row) => row.auditStatus.includes("通过，已结算")).reduce((sum, row) => sum + row.total, 0);
  const failed = promotionInvoices.filter((row) => row.auditStatus.includes("不通过")).reduce((sum, row) => sum + row.total, 0);
  const invoiced = promotionInvoices.filter((row) => !row.auditStatus.includes("不通过")).reduce((sum, row) => sum + row.total, 0);

  return (
    <section className="business-page" aria-labelledby="finance-promotion-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">财务二级页面</span>
          <h1 id="finance-promotion-title">推广服务费</h1>
          <p>门店提交成功后全量进入此列表；财务导入审核状态、原因并同步门店。</p>
        </div>
        <button type="button" className="button button--primary">导入厂端审核结果</button>
      </header>
      <MetricStrip items={[
        { label: "推广费总额", value: money(total) },
        { label: "已确认金额", value: money(total) },
        { label: "已开票金额", value: money(invoiced), helper: "审核不通过金额已退出" },
        { label: "发票审核通过金额", value: money(passed), tone: "success" },
        { label: "审核未通过金额", value: money(failed), tone: "danger" },
      ]} />
      {scenario.title === "已开票或已打款后重算" ? (
        <div className="validation-banner" role="status">
          <strong>重算差额进入下一账期</strong>
          <span>原发票及打款结果不回滚；本次 -¥8,420.00 计入下一账期并提示确认。</span>
        </div>
      ) : null}
      <WorkbenchToolbar onSearch={setSearch} actions={<button type="button" className="button button--secondary">导出当前列表</button>}>
        <label><span className="sr-only">审核状态</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option>全部状态</option><option>提交成功，待厂端审核</option><option>审核通过，已结算</option><option>审核不通过，请红冲重开</option></select></label>
        <label><span className="sr-only">账期</span><select defaultValue="2026-07"><option>2026-07</option><option>2026-06</option></select></label>
      </WorkbenchToolbar>
      <div className="data-table-wrap data-table-wrap--wide">
        <table>
          <thead><tr><th>门店</th><th>有效 SAP</th><th>账期 / 版本</th><th>推广费总额</th><th>已确认金额</th><th>数电专票号码</th><th>提交成功时间</th><th>结算归属月</th><th>审核状态</th><th>审核原因</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id}>
            <td><strong>{row.store}</strong></td><td>{row.effectiveSap}</td><td>{row.period} / {row.version}</td><td className="amount">{money(row.totalFee)}</td><td className="amount">{money(row.confirmedAmount)}</td><td>{row.invoiceNumber}</td><td>{row.submittedAt}</td><td>{row.settlementMonth}</td><td><StatusTag tone={statusTone(row.auditStatus)}>{row.auditStatus}</StatusTag></td><td>{row.auditReason}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}
