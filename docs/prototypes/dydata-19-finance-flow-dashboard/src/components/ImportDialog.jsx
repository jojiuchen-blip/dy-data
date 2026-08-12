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
        <span>共 {rows.length} 行 · 可写入 {result.accepted} 行 · 拒绝 {result.rejected} 行</span>
      </div>
      {!result.ok ? (
        <div className="validation-banner validation-banner--danger" role="alert">
          <strong>整批校验失败，未写入任何记录</strong>
          <span>请修正所有错误行后重新上传；本次不会产生部分成功数据。</span>
        </div>
      ) : (
        <div className="validation-banner validation-banner--success" role="status">
          <strong>数据齐全，可以一次性写入</strong>
          <span>如识别到同业务键的不同版本，系统将在确认前提示覆盖范围。</span>
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
        <span>系统仅保存校验、覆盖、操作人与导入时间日志，不保存原始上传文件。</span>
        <button type="button" className="button button--primary" disabled={!result.ok} onClick={onConfirm}>
          确认整批导入
        </button>
      </footer>
    </section>
  );
}
