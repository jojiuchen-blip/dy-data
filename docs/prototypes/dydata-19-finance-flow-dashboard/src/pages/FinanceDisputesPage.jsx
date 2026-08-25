import { useState } from "react";
import { MetricStrip } from "../components/DataWorkbench.jsx";
import { StatusTag } from "../components/StatusTag.jsx";
import { amountDisputes } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";

export function FinanceDisputesPage() {
  const [selectedAmount, setSelectedAmount] = useState(null);
  const [showExport, setShowExport] = useState(false);
  const selectedAmountRow = amountDisputes.find((row) => row.id === selectedAmount);

  return (
    <section className="business-page" aria-labelledby="finance-disputes-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">财务一级页面</span>
          <h1 id="finance-disputes-title">账单异议</h1>
          <p>仅处理账单金额、费率和订单遗漏异议；管理员和最高管理员均可处理。</p>
        </div>
        <button type="button" className="button button--secondary" onClick={() => setShowExport(true)}>导出账单异议</button>
      </header>

      {showExport ? (
        <section className="template-preview" aria-labelledby="amount-export-title">
          <div className="section-heading">
            <div><span className="eyebrow">导出字段预览</span><h2 id="amount-export-title">账单金额费率异议</h2></div>
            <button type="button" className="text-button" onClick={() => setShowExport(false)}>关闭</button>
          </div>
          <div className="data-table-wrap"><table><thead><tr><th>异议编号</th><th>门店编号</th><th>门店名称</th><th>账期</th><th>费用方向</th><th>异议类型</th><th>处理结果</th><th>原因</th></tr></thead><tbody><tr><td>DIS-260801</td><td>STORE-07102</td><td>南京江宁比亚迪王朝店</td><td>2026-07</td><td>推广服务费</td><td>费率设置错误</td><td>受理</td><td>费率配置需修正</td></tr></tbody></table></div>
        </section>
      ) : null}

      <MetricStrip items={[
        { label: "账单金额异议", value: "18 条" },
        { label: "系统检测中", value: "5 条" },
        { label: "待管理员处理", value: "9 条", tone: "warning" },
        { label: "今日已完成", value: "4 条", tone: "success" },
      ]} />
      <div className="data-table-wrap">
        <table>
          <thead><tr><th>异议编号</th><th>异议类型</th><th>门店</th><th>费用方向 / 账期</th><th>异议金额</th><th>系统检测结果</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>{amountDisputes.map((row) => <tr key={row.id}><td>{row.id}</td><td>{row.type}</td><td><strong>{row.store}</strong></td><td>{row.feeDirection} / {row.period}</td><td className="amount">{money(row.disputedAmount)}</td><td>{row.systemResult}</td><td><StatusTag tone={row.status === "已驳回" ? "neutral" : "warning"}>{row.status}</StatusTag></td><td><button type="button" className="text-button" onClick={() => setSelectedAmount(row.id)}>演示动作：{row.action}</button></td></tr>)}</tbody>
        </table>
      </div>

      {selectedAmountRow ? (
        <aside className="detail-drawer" aria-labelledby="amount-detail-title">
          <header><div><span className="eyebrow">金额异议详情</span><h2 id="amount-detail-title">{selectedAmountRow.type} · {selectedAmountRow.store}</h2></div><button type="button" className="text-button" onClick={() => setSelectedAmount(null)}>关闭</button></header>
          <dl><div><dt>系统检测结果</dt><dd>{selectedAmountRow.systemResult}</dd></div><div><dt>整期确认规则</dt><dd>处理完成前，该费用方向整期未确认，已确认金额为 0</dd></div><div><dt>处理权限</dt><dd>管理员或最高管理员均可处理</dd></div><div><dt>处理完成</dt><dd>账单自动确认，无需门店再次确认</dd></div></dl>
          <footer><button type="button" className="button button--secondary">演示动作：驳回并自动确认</button><button type="button" className="button button--primary">演示动作：受理并生成新版本</button></footer>
        </aside>
      ) : null}
    </section>
  );
}
