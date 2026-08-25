import { StatusTag } from "./StatusTag.jsx";

export function ImportDialog({ importType, rows, result, onClose, onConfirm }) {
  return (
    <section className="import-preview" role="dialog" aria-modal="true" aria-labelledby="import-preview-title">
      <header className="section-heading">
        <div>
          <span className="eyebrow">导入前整批校验</span>
          <h2 id="import-preview-title">{importType}</h2>
        </div>
        <button type="button" className="text-button" onClick={onClose}>关闭预览</button>
      </header>
      <div className="import-preview__summary">
        <StatusTag tone={result.ok ? "success" : "danger"}>
          {result.ok ? "整批校验通过" : "整批校验失败"}
        </StatusTag>
        <span>共 {rows.length} 行 · 演示可写入 {result.accepted} 行 · 拒绝 {result.rejected} 行</span>
      </div>
      {!result.ok ? (
        <div className="validation-banner validation-banner--danger" role="alert">
          <strong>整批演示校验失败，未修改任何业务记录</strong>
          <span>请修正所有错误行后重新选择；本原型不会上传文件或产生部分成功数据。</span>
        </div>
      ) : (
        <div className="validation-banner validation-banner--success" role="status">
          <strong>数据齐全，可以演示一次性写入</strong>
          <span>确认仅修改当前页面内存状态，不会覆盖真实业务数据。</span>
        </div>
      )}
      <div className="data-table-wrap">
        <table>
          <thead>
            <tr><th>行号</th><th>业务键</th><th>校验结果</th><th>说明</th></tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.invoiceNumber}-${index}`}>
                <td>{index + 1}</td>
                <td>{row.invoiceNumber}</td>
                <td><StatusTag tone={row.valid ? "success" : "danger"}>{row.valid ? "通过" : "失败"}</StatusTag></td>
                <td>{row.valid ? "字段、金额与唯一键校验通过" : "金额与已确认金额不一致"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <footer className="form-actions">
        <span>原文件留存政策待 DYDATA-19 财务与审计决策；本原型不执行真实上传或保存。</span>
        <button type="button" className="button button--primary" disabled={!result.ok} onClick={onConfirm}>
          演示动作：确认整批导入
        </button>
      </footer>
    </section>
  );
}
