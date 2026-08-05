import { useState } from "react";
import { MetricStrip } from "../components/DataWorkbench.jsx";
import { StatusTag } from "../components/StatusTag.jsx";
import { amountDisputes, sapDisputes } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";

export function FinanceDisputesPage() {
  const [tab, setTab] = useState("sap");
  const [selectedSap, setSelectedSap] = useState(null);
  const [selectedAmount, setSelectedAmount] = useState(null);
  const [effectiveSap, setEffectiveSap] = useState(sapDisputes[0].effectiveSap);
  const selectedSapRow = sapDisputes.find((row) => row.id === selectedSap);
  const selectedAmountRow = amountDisputes.find((row) => row.id === selectedAmount);

  function resolveSap(value) {
    setEffectiveSap(value);
    setSelectedSap(null);
  }

  return (
    <section className="business-page" aria-labelledby="finance-disputes-title">
      <header className="page-heading">
        <div><span className="eyebrow">财务二级页面</span><h1 id="finance-disputes-title">账单异议</h1><p>统一列表，按异议类型展示处理动作；管理员和最高管理员均可处理。</p></div>
        <div className="page-heading__actions"><button type="button" className="button button--secondary">导出待确认清单</button><button type="button" className="button button--primary">导入确认清单</button></div>
      </header>
      <MetricStrip items={tab === "sap" ? [
        { label: "SAP 差异", value: "24 家" }, { label: "待门店确认", value: "11 家", tone: "warning" }, { label: "财务可代确认", value: "11 家" }, { label: "今日已确认", value: "13 家", tone: "success" },
      ] : [
        { label: "账单金额异议", value: "18 条" }, { label: "系统检测中", value: "5 条" }, { label: "待管理员处理", value: "9 条", tone: "warning" }, { label: "今日已完成", value: "4 条", tone: "success" },
      ]} />
      <div className="segmented-tabs" role="tablist" aria-label="异议类型">
        <button type="button" role="tab" aria-selected={tab === "sap"} onClick={() => setTab("sap")}>SAP 编码异议</button>
        <button type="button" role="tab" aria-selected={tab === "amount"} onClick={() => setTab("amount")}>账单金额费率异议</button>
      </div>
      {tab === "sap" ? (
        <div className="data-table-wrap">
          <table>
            <thead><tr><th>异议编号</th><th>门店</th><th>有效 SAP</th><th>当前状态</th><th>检测时间</th><th>操作</th></tr></thead>
            <tbody>{sapDisputes.map((row, index) => <tr key={row.id}><td>{row.id}</td><td><strong>{row.store}</strong></td><td>{index === 0 ? effectiveSap : row.effectiveSap}</td><td><StatusTag tone={row.status === "已确认" ? "success" : "warning"}>{row.status}</StatusTag></td><td>{row.detectedAt}</td><td><button type="button" className="text-button" onClick={() => setSelectedSap(row.id)}>查看详情</button></td></tr>)}</tbody>
          </table>
        </div>
      ) : (
        <div className="data-table-wrap">
          <table>
            <thead><tr><th>异议编号</th><th>异议类型</th><th>门店</th><th>费用方向 / 账期</th><th>异议金额</th><th>系统检测结果</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>{amountDisputes.map((row) => <tr key={row.id}><td>{row.id}</td><td>{row.type}</td><td><strong>{row.store}</strong></td><td>{row.feeDirection} / {row.period}</td><td className="amount">{money(row.disputedAmount)}</td><td>{row.systemResult}</td><td><StatusTag tone={row.status === "已驳回" ? "neutral" : "warning"}>{row.status}</StatusTag></td><td><button type="button" className="text-button" onClick={() => setSelectedAmount(row.id)}>{row.action}</button></td></tr>)}</tbody>
          </table>
        </div>
      )}
      {selectedSapRow ? <aside className="detail-drawer" aria-labelledby="sap-detail-title">
        <header><div><span className="eyebrow">SAP 差异详情</span><h2 id="sap-detail-title">{selectedSapRow.store}</h2></div><button type="button" className="text-button" onClick={() => setSelectedSap(null)}>关闭</button></header>
        <dl><div><dt>门店维护值</dt><dd>{selectedSapRow.storeSap}</dd></div><div><dt>财务导入值</dt><dd>{selectedSapRow.financeSap}</dd></div><div><dt>当前有效 SAP</dt><dd>{effectiveSap}</dd></div><div><dt>影响</dt><dd>提示确认，但不阻断推广服务费发票提交</dd></div></dl>
        <footer><button type="button" className="button button--secondary" onClick={() => resolveSap(selectedSapRow.storeSap)}>采用门店值</button><button type="button" className="button button--primary" onClick={() => resolveSap(selectedSapRow.financeSap)}>采用财务值</button></footer>
      </aside> : null}
      {selectedAmountRow ? <aside className="detail-drawer" aria-labelledby="amount-detail-title">
        <header><div><span className="eyebrow">金额异议详情</span><h2 id="amount-detail-title">{selectedAmountRow.type} · {selectedAmountRow.store}</h2></div><button type="button" className="text-button" onClick={() => setSelectedAmount(null)}>关闭</button></header>
        <dl><div><dt>系统检测结果</dt><dd>{selectedAmountRow.systemResult}</dd></div><div><dt>整期确认规则</dt><dd>处理完成前，该费用方向整期未确认，已确认金额为 0</dd></div><div><dt>处理权限</dt><dd>管理员或最高管理员均可处理</dd></div><div><dt>处理完成</dt><dd>账单自动确认，无需门店再次确认</dd></div></dl>
        <footer><button type="button" className="button button--secondary">驳回并自动确认</button><button type="button" className="button button--primary">受理并生成新版本</button></footer>
      </aside> : null}
    </section>
  );
}
