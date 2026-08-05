import { useState } from "react";
import { ImportDialog } from "../components/ImportDialog.jsx";
import { SolarIcon } from "../components/SolarIcon.jsx";
import { StatusTag } from "../components/StatusTag.jsx";
import { importDemoRows, importRecords } from "../data/financeData.js";
import { validateImportBatch } from "../domain/financeRules.js";

const importTypes = [
  { title: "待确认 SAP 编码门店列表", detail: "门店或财务维护的新值可以覆盖原值；无原始数据时直接生效。", action: "导入待确认列表" },
  { title: "SAP 编码确认结果", detail: "使用门店与有效 SAP 唯一匹配，支持导出清单后整批回导。", action: "导入确认结果" },
  { title: "管理服务费发票信息", detail: "批量登记发票号码、发票金额和开票时间。", action: "导入发票信息" },
  { title: "推广服务费审核结果", detail: "按数电专票号码更新审核状态；不通过时必须填写原因。", action: "导入审核结果" },
];

export function FinanceImportsPage() {
  const [preview, setPreview] = useState(null);
  const [notice, setNotice] = useState("");

  function showPreview(kind) {
    const rows = importDemoRows[kind];
    setPreview({ type: kind === "invalid" ? "推广服务费审核结果 · 含错误演示" : "推广服务费审核结果 · 有效演示", rows, result: validateImportBatch(rows) });
    setNotice("");
  }

  return (
    <section className="business-page" aria-labelledby="finance-imports-title">
      <header className="page-heading"><div><span className="eyebrow">财务二级页面</span><h1 id="finance-imports-title">导入记录</h1><p>业务页面发起导入，统一在此查看校验、覆盖、版本与永久审计记录。</p></div><span className="scope-note">整批成功或整批失败</span></header>
      <div className="import-type-grid">
        {importTypes.map((item) => <article key={item.title}><span className="finance-entry__icon"><SolarIcon name="document" /></span><div><h2>{item.title}</h2><p>{item.detail}</p></div><button type="button" className="button button--secondary">{item.action}</button></article>)}
      </div>
      <div className="demo-actions" aria-label="导入校验演示">
        <div><strong>原子导入演示</strong><span>用两组样例确认“任一行失败，整批零写入”。</span></div>
        <button type="button" className="button button--secondary" onClick={() => showPreview("valid")}>演示有效批次</button>
        <button type="button" className="button button--danger" onClick={() => showPreview("invalid")}>演示含错误批次</button>
      </div>
      {notice ? <div className="validation-banner validation-banner--success" role="status"><strong>{notice}</strong><span>如业务键已存在且内容不同，已生成新版本并保留原记录。</span></div> : null}
      {preview ? <ImportDialog importType={preview.type} rows={preview.rows} result={preview.result} onClose={() => setPreview(null)} onConfirm={() => { setPreview(null); setNotice("整批导入成功，已写入全部记录"); }} /> : null}
      <section className="records-section" aria-labelledby="import-records-title">
        <div className="section-heading"><div><span className="eyebrow">永久审计</span><h2 id="import-records-title">历史导入记录</h2></div><span>按最新版本生效，覆盖前必须确认</span></div>
        <div className="data-table-wrap"><table><thead><tr><th>导入编号</th><th>导入类型</th><th>文件名</th><th>记录数</th><th>状态</th><th>版本</th><th>操作人</th><th>导入时间</th><th>结果摘要</th></tr></thead><tbody>{importRecords.map((row) => <tr key={row.id}><td>{row.id}</td><td>{row.type}</td><td>{row.fileName}</td><td>{row.count}</td><td><StatusTag tone={row.status.includes("失败") ? "danger" : row.status.includes("成功") ? "success" : "warning"}>{row.status}</StatusTag></td><td>{row.version}</td><td>{row.operator}</td><td>{row.importedAt}</td><td>{row.summary}</td></tr>)}</tbody></table></div>
      </section>
    </section>
  );
}
