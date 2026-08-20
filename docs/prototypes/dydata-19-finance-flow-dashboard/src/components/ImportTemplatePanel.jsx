import { useState } from "react";

const importScenarios = {
  first: {
    label: "首次成功",
    tone: "success",
    title: "校验通过，可整批写入",
    detail: "业务唯一键、标准化内容和文件哈希均通过校验，将生成首个有效版本。",
  },
  unchanged: {
    label: "无变化",
    tone: "success",
    title: "内容无变化，不生成新版本",
    detail: "返回第一次成功结果并记录幂等命中，不重复写入。",
  },
  difference: {
    label: "差异待确认",
    tone: "warning",
    title: "检测到 3 项差异",
    detail: "确认后生成新版本并保留旧版本；取消则不写入。",
  },
  failed: {
    label: "整批失败",
    tone: "danger",
    title: "整批未写入",
    detail: "共 128 行，发现 6 个错误行；页面分页展示，下载包含全部错误。",
  },
  conflict: {
    label: "版本冲突",
    tone: "danger",
    title: "数据已被其他管理员更新",
    detail: "读取版本 V3，当前版本 V4；最近操作人王宁，操作时间 2026-08-20 16:41。请刷新后重试。",
  },
};

export function ImportTemplatePanel({ title, fields, sample, rules = [], mode = "template", onClose, onConfirm }) {
  const [scenarioId, setScenarioId] = useState("first");
  const result = importScenarios[scenarioId];
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
        <>
          <label className="import-scenario-control">
            <span>导入结果场景</span>
            <select aria-label="导入结果场景" value={scenarioId} onChange={(event) => setScenarioId(event.target.value)}>
              {Object.entries(importScenarios).map(([id, item]) => <option key={id} value={id}>{item.label}</option>)}
            </select>
          </label>
          <div className={`import-result import-result--${result.tone}`} role="status">
            <strong>{result.title}</strong>
            <span>{result.detail}</span>
            {scenarioId === "failed" ? (
              <div className="import-error-actions">
                <span>错误行 2、17、38、64、91、117 · 第 1 / 2 页</span>
                <button type="button" className="button button--secondary">下载全部错误</button>
              </div>
            ) : null}
            {scenarioId === "conflict" ? <button type="button" className="button button--secondary">刷新查看最新数据</button> : null}
          </div>
          <div className="form-actions">
            <span>实际导入时整批校验；任一行错误则整批不写入。</span>
            <button type="button" className="button button--primary" onClick={onConfirm}>演示动作：模拟校验并导入</button>
          </div>
        </>
      ) : null}
    </section>
  );
}
