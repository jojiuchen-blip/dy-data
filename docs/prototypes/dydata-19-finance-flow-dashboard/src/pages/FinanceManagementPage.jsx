import { MetricStrip, WorkbenchToolbar } from "../components/DataWorkbench.jsx";
import { StatusTag } from "../components/StatusTag.jsx";
import { managementInvoices } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";

export function FinanceManagementPage() {
  const total = managementInvoices.reduce((sum, row) => sum + row.totalFee, 0);
  const issued = managementInvoices.reduce((sum, row) => sum + row.invoiceAmount, 0);
  return (
    <section className="business-page" aria-labelledby="finance-management-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">财务二级页面</span>
          <h1 id="finance-management-title">管理服务费</h1>
          <p>显示全量已确认账单，由财务批量导入厂端提供的发票号码、金额和开票时间。</p>
        </div>
        <button type="button" className="button button--primary">批量导入发票信息</button>
      </header>
      <MetricStrip items={[
        { label: "管理费总额", value: money(total) },
        { label: "已确认金额", value: money(total) },
        { label: "待开票金额", value: money(total - issued), tone: "warning" },
        { label: "已开票金额", value: money(issued), tone: "success" },
      ]} />
      <WorkbenchToolbar actions={<button type="button" className="button button--secondary">导出当前列表</button>}>
        <label><span className="sr-only">开票状态</span><select defaultValue="全部状态"><option>全部状态</option><option>待开票</option><option>已开票</option></select></label>
      </WorkbenchToolbar>
      <div className="data-table-wrap">
        <table>
          <thead><tr><th>门店</th><th>有效 SAP</th><th>账期 / 版本</th><th>管理费总额</th><th>已确认金额</th><th>发票号码</th><th>发票金额</th><th>开票时间</th><th>状态</th></tr></thead>
          <tbody>{managementInvoices.map((row) => <tr key={row.id}>
            <td><strong>{row.store}</strong></td><td>{row.effectiveSap}</td><td>{row.period} / {row.version}</td><td className="amount">{money(row.totalFee)}</td><td className="amount">{money(row.confirmedAmount)}</td><td>{row.invoiceNumber}</td><td className="amount">{money(row.invoiceAmount)}</td><td>{row.issuedAt}</td><td><StatusTag tone={row.status === "已开票" ? "success" : "warning"}>{row.status}</StatusTag></td>
          </tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}
