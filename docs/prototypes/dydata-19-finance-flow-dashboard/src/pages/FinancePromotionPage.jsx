import { useMemo, useState } from "react";
import { MetricStrip, WorkbenchToolbar } from "../components/DataWorkbench.jsx";
import { StatusTag } from "../components/StatusTag.jsx";
import { promotionInvoices } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";
import { exportAllFields } from "../domain/csvExport.js";
import { ImportTemplatePanel } from "../components/ImportTemplatePanel.jsx";

const promotionImportFields = ["发票号码", "发票审核结果", "发票审核不通过原因", "结算日期", "结算金额"];

function statusTone(status) {
  if (status.includes("不通过")) return "danger";
  if (status.includes("通过")) return "success";
  return "warning";
}

export function FinancePromotionPage({ scenario, onNavigate }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("全部状态");
  const [period, setPeriod] = useState("全部账期");
  const [exportNotice, setExportNotice] = useState("");
  const [importPanel, setImportPanel] = useState(null);
  const [importNotice, setImportNotice] = useState("");
  const rows = useMemo(() => promotionInvoices.filter((row) => {
    const matchesSearch = `${row.store}${row.effectiveSap}${row.invoiceNumber}`.toLowerCase().includes(search.toLowerCase());
    return matchesSearch
      && (status === "全部状态" || row.auditStatus === status)
      && (period === "全部账期" || row.period === period);
  }), [search, status, period]);

  const total = rows.reduce((sum, row) => sum + row.totalFee, 0);
  const passed = rows.filter((row) => row.auditStatus.includes("通过，已结算")).reduce((sum, row) => sum + row.total, 0);
  const failed = rows.filter((row) => row.auditStatus.includes("不通过")).reduce((sum, row) => sum + row.total, 0);
  const invoiced = rows.filter((row) => !row.auditStatus.includes("不通过")).reduce((sum, row) => sum + row.total, 0);

  function exportCurrentRows() {
    const count = exportAllFields(rows, `推广服务费-${period === "全部账期" ? "全部账期" : period}.csv`);
    setExportNotice(`已按当前筛选导出 ${count} 条记录`);
  }

  return (
    <section className="business-page" aria-labelledby="finance-promotion-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">财务二级页面</span>
          <h1 id="finance-promotion-title">推广服务费</h1>
          <p>门店提交成功后全量进入此列表；财务导入审核状态、原因并同步门店。</p>
        </div>
        <div className="page-heading__actions page-heading__actions--wrap">
          <button type="button" className="button button--secondary" onClick={() => setImportPanel("template")}>下载推广费厂家导入模板</button>
          <button type="button" className="button button--primary" onClick={() => setImportPanel("import")}>演示动作：导入推广费厂家信息</button>
        </div>
      </header>
      {importPanel ? <ImportTemplatePanel
        title="推广费厂家导入信息"
        fields={promotionImportFields}
        sample={["25322000000178435217", "审核通过", "", "2026-08-13", "96820.00"]}
        rules={["发票号码、发票审核结果必填，并以发票号码匹配门店已提交记录。", "审核通过时结算日期、结算金额必填。", "审核不通过时原因必填，结算日期和结算金额允许为空。"]}
        mode={importPanel}
        onClose={() => setImportPanel(null)}
        onConfirm={() => { setImportPanel(null); setImportNotice("模拟导入成功：推广费厂家结果已更新"); }}
      /> : null}
      {importNotice ? <div className="inline-notice" role="status">{importNotice}</div> : null}
      <MetricStrip items={[
        { label: "推广费总额", value: money(total) },
        { label: "已确认金额", value: money(total) },
        { label: "已开票金额", value: money(invoiced), helper: "审核不通过金额已退出" },
        { label: "发票审核通过已结算金额", value: money(passed), tone: "success" },
        { label: "审核未通过金额", value: money(failed), tone: "danger" },
      ]} />
      {scenario.title === "已开票或已打款后重算" ? (
        <div className="validation-banner" role="status">
          <strong>重算差额进入下一账期</strong>
          <span>已开票、已打款不修改原结果；历史账期补充金额在下一账期合算。</span>
        </div>
      ) : null}
      <div className="export-guidance">可先按发票审核状态、账期或门店筛选，再导出当前结果。</div>
      <WorkbenchToolbar onSearch={setSearch} actions={<><button type="button" className="button button--secondary" onClick={() => onNavigate?.("finance-orders", { direction: "推广服务费" })}>查看推广服务费订单明细</button><button type="button" className="button button--secondary" onClick={exportCurrentRows}>导出当前筛选结果</button></>}>
        <label className="filter-control"><span>发票审核状态</span><select aria-label="发票审核状态" value={status} onChange={(event) => setStatus(event.target.value)}><option>全部状态</option><option>提交成功，待厂端审核</option><option>审核通过，已结算</option><option>审核不通过</option></select></label>
        <label className="filter-control"><span>筛选账期</span><select aria-label="筛选账期" value={period} onChange={(event) => setPeriod(event.target.value)}><option>全部账期</option><option>2026-07</option><option>2026-06</option></select></label>
      </WorkbenchToolbar>
      {exportNotice ? <div className="inline-notice" role="status">{exportNotice}</div> : null}
      <div className="data-table-wrap data-table-wrap--wide">
        <table>
          <thead><tr><th>门店</th><th>有效 SAP</th><th>账期</th><th>推广费总额</th><th>已确认金额</th><th>数电专票号码</th><th>提交成功时间</th><th>结算归属月</th><th>发票审核状态</th><th>审核原因</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id}>
            <td><strong>{row.store}</strong></td><td>{row.effectiveSap}</td><td>{row.period}</td><td className="amount">{money(row.totalFee)}</td><td className="amount">{money(row.confirmedAmount)}</td><td>{row.invoiceNumber}</td><td>{row.submittedAt}</td><td>{row.settlementMonth}</td><td><StatusTag tone={statusTone(row.auditStatus)}>{row.auditStatus}</StatusTag></td><td>{row.auditReason}</td>
          </tr>)}{!rows.length ? <tr><td colSpan="10">当前筛选下暂无记录</td></tr> : null}</tbody>
        </table>
      </div>
    </section>
  );
}
