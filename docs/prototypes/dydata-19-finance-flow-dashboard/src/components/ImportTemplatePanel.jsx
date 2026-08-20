export function ImportTemplatePanel({ title, fields, sample, rules = [], mode = "template", onClose, onConfirm }) {
  return (
    <section className="template-preview import-template-panel" aria-labelledby="import-template-title">
      <div className="section-heading">
        <div>
          <span className="eyebrow">{mode === "import" ? "导入前模板核对" : "模板字段预览"}</span>
          <h2 id="import-template-title">{title}</h2>
        </div>
        <button type="button" className="text-button" onClick={onClose}>关闭</button>
      </div>
      <div className="data-table-wrap data-table-wrap--wide">
        <table aria-label={`${title}字段`}>
          <thead><tr>{fields.map((field) => <th key={field}>{field}</th>)}</tr></thead>
          <tbody><tr>{sample.map((value, index) => <td key={`${fields[index]}-${value}`}>{value}</td>)}</tr></tbody>
        </table>
      </div>
      <div className="template-rules">
        <strong>模板填写规则</strong>
        <ul>{rules.map((rule) => <li key={rule}>{rule}</li>)}</ul>
      </div>
      {mode === "import" ? (
        <div className="form-actions">
          <span>实际导入时整批校验；任一行错误则整批不写入。</span>
          <button type="button" className="button button--primary" onClick={onConfirm}>演示动作：模拟校验并导入</button>
        </div>
      ) : null}
    </section>
  );
}
