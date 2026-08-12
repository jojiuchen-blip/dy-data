import { StatusTag } from "../components/StatusTag.jsx";
import { importRecords } from "../data/financeData.js";

export function FinanceImportsPage() {
  return (
    <section className="business-page" aria-labelledby="finance-imports-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">财务二级页面</span>
          <h1 id="finance-imports-title">导入记录</h1>
          <p>四类数据均从对应业务页面发起导入；本页只用于查询批次结果和覆盖日志。</p>
        </div>
        <span className="scope-note">整批成功或整批失败</span>
      </header>

      <div className="validation-banner" role="note">
        <strong>仅保存导入日志，不保存原始上传文件。</strong>
        <span>日志记录导入类型、源文件名称、数据行数、校验结果、操作人、导入时间和覆盖摘要。</span>
      </div>

      <section className="records-section" aria-labelledby="import-records-title">
        <div className="section-heading">
          <div><span className="eyebrow">操作追溯</span><h2 id="import-records-title">历史导入日志</h2></div>
          <span>最新导入生效，覆盖前必须确认</span>
        </div>
        <div className="data-table-wrap">
          <table>
            <thead><tr><th>导入编号</th><th>导入类型</th><th>源文件名称（仅日志）</th><th>记录数</th><th>状态</th><th>操作人</th><th>导入时间</th><th>结果摘要</th></tr></thead>
            <tbody>{importRecords.map((row) => <tr key={row.id}>
              <td>{row.id}</td><td>{row.type}</td><td>{row.fileName}</td><td>{row.count}</td><td><StatusTag tone={row.status.includes("失败") ? "danger" : row.status.includes("成功") ? "success" : "warning"}>{row.status}</StatusTag></td><td>{row.operator}</td><td>{row.importedAt}</td><td>{row.summary}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
