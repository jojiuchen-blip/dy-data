import { useMemo, useState } from "react";
import { MetricStrip, WorkbenchToolbar } from "../components/DataWorkbench.jsx";
import { StatusTag } from "../components/StatusTag.jsx";
import { managementInvoices } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";
import { exportAllFields } from "../domain/csvExport.js";
import { ImportTemplatePanel } from "../components/ImportTemplatePanel.jsx";
import { MetricScopeToggle } from "../components/MetricScopeToggle.jsx";

const managementImportFields = ["门店ID（所属账户关联poi-id）", "账期", "服务店名称", "发票号码", "发票开具日期", "厂家扣款日期", "厂家扣款金额"];

export function FinanceManagementPage({ onNavigate }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("全部状态");
  const [period, setPeriod] = useState("全部账期");
  const [exportNotice, setExportNotice] = useState("");
  const [importPanel, setImportPanel] = useState(null);
  const [importNotice, setImportNotice] = useState("");
  const [metricScope, setMetricScope] = useState("month");
  const rows = useMemo(() => managementInvoices.filter((row) => {
    const matchesSearch = `${row.store}${row.effectiveSap}${row.invoiceNumber}`.toLowerCase().includes(search.toLowerCase());
    return matchesSearch
      && (status === "全部状态" || row.status === status)
      && (period === "全部账期" || row.period === period);
  }), [search, status, period]);
  const total = rows.reduce((sum, row) => sum + row.totalFee, 0);
  const issued = rows.reduce((sum, row) => sum + row.invoiceAmount, 0);
  const scopeMultiplier = metricScope === "cumulative" ? 2.1 : 1;

  function exportCurrentRows() {
    const count = exportAllFields(rows, `管理服务费-${period === "全部账期" ? "全部账期" : period}.csv`);
    setExportNotice(`已按当前筛选导出 ${count} 条记录`);
  }
  return (
    <section className="business-page" aria-labelledby="finance-management-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">财务二级页面</span>
          <h1 id="finance-management-title">管理服务费</h1>
          <p>显示全量已确认账单，由财务批量导入厂端提供的发票号码、金额和开票时间。</p>
        </div>
        <div className="page-heading__actions page-heading__actions--wrap">
          <button type="button" className="button button--secondary" onClick={() => setImportPanel("template")}>下载管理服务费厂家导入模板</button>
          <button type="button" className="button button--primary" onClick={() => setImportPanel("import")}>导入管理服务费厂家信息</button>
        </div>
      </header>
      {importPanel ? <ImportTemplatePanel
        title="管理服务费厂家导入信息"
        fields={managementImportFields}
        sample={["7123456789012345678", "2026-07", "深圳龙岗比亚迪王朝店", "25322000000863002155", "2026-08-08", "2026-08-12", "18640.00"]}
        rules={["全部字段必填。", "一个门店的一个账期对应一张管理服务费发票。", "以门店ID（所属账户关联poi-id）＋账期作为唯一匹配键。"]}
        mode={importPanel}
        onClose={() => setImportPanel(null)}
        onConfirm={() => { setImportPanel(null); setImportNotice("管理服务费厂家信息已更新"); }}
      /> : null}
      {importNotice ? <div className="inline-notice" role="status">{importNotice}</div> : null}
      <MetricScopeToggle value={metricScope} onChange={setMetricScope} />
      <MetricStrip items={[
        { label: "管理费总额", value: money(total * scopeMultiplier) },
        { label: "已确认金额（仅单月）", value: money(total) },
        { label: "待开票金额", value: money((total - issued) * scopeMultiplier), tone: "warning" },
        { label: "已开票金额", value: money(issued * scopeMultiplier), tone: "success" },
      ]} />
      <div className="export-guidance">账期、状态与搜索条件同时作用于列表、金额汇总和导出结果。</div>
      <WorkbenchToolbar onSearch={setSearch} actions={<><button type="button" className="button button--secondary" onClick={() => onNavigate?.("finance-orders", { direction: "管理服务费" })}>查看管理服务费订单明细</button><button type="button" className="button button--secondary" onClick={exportCurrentRows}>导出当前筛选结果</button></>}>
        <label className="filter-control"><span>开票状态</span><select aria-label="开票状态" value={status} onChange={(event) => setStatus(event.target.value)}><option>全部状态</option><option>待开票</option><option>已开票</option></select></label>
        <label className="filter-control"><span>筛选账期</span><select aria-label="筛选账期" value={period} onChange={(event) => setPeriod(event.target.value)}><option>全部账期</option><option>2026-07</option><option>2026-06</option></select></label>
      </WorkbenchToolbar>
      {exportNotice ? <div className="inline-notice" role="status">{exportNotice}</div> : null}
      <div className="data-table-wrap">
        <table>
          <thead><tr><th>门店</th><th>有效 SAP</th><th>账期</th><th>管理费总额</th><th>已确认金额</th><th>发票号码</th><th>发票金额</th><th>开票时间</th><th>状态</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.id}>
            <td><strong>{row.store}</strong></td><td>{row.effectiveSap}</td><td>{row.period}</td><td className="amount">{money(row.totalFee)}</td><td className="amount">{money(row.confirmedAmount)}</td><td>{row.invoiceNumber}</td><td className="amount">{money(row.invoiceAmount)}</td><td>{row.issuedAt}</td><td><StatusTag tone={row.status === "已开票" ? "success" : "warning"}>{row.status}</StatusTag></td>
          </tr>)}{!rows.length ? <tr><td colSpan="9">当前筛选下暂无记录</td></tr> : null}</tbody>
        </table>
      </div>
    </section>
  );
}
