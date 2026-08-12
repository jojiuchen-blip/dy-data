import { useState } from "react";
import { MetricStrip } from "./DataWorkbench.jsx";
import { StatusTag } from "./StatusTag.jsx";
import { sapDisputes } from "../data/financeData.js";

export function SapDisputesPanel() {
  const [selectedSap, setSelectedSap] = useState(null);
  const [template, setTemplate] = useState(null);
  const [sapImportApplied, setSapImportApplied] = useState(false);
  const [effectiveSap, setEffectiveSap] = useState(sapDisputes[0].effectiveSap);
  const selectedSapRow = sapDisputes.find((row) => row.id === selectedSap);

  return (
    <section aria-label="SAP异议处理">
      <div className="dispute-action-bar" role="group" aria-label="SAP异议操作">
        <button type="button" className="button button--secondary" onClick={() => setTemplate("sap-export")}>导出 SAP 编码差异清单</button>
        <button type="button" className="button button--secondary" onClick={() => setTemplate("sap-download")}>下载 SAP 编码确认模板</button>
        <button type="button" className="button button--primary" onClick={() => setTemplate("sap-import")}>导入最终确认 SAP 编码</button>
      </div>

      {template ? (
        <section className="template-preview" aria-labelledby="sap-template-preview-title">
          <div className="section-heading">
            <div>
              <span className="eyebrow">模板首行提供填写示例</span>
              <h2 id="sap-template-preview-title">SAP 编码确认{template === "sap-import" ? "导入预览" : "模板字段"}</h2>
            </div>
            <button type="button" className="text-button" onClick={() => setTemplate(null)}>关闭</button>
          </div>
          <div className="data-table-wrap data-table-wrap--wide">
            <table>
              <thead><tr><th>门店ID（所属账户关联poi-id）</th><th>服务店名称</th><th>财务初始导入SAP编码（若纯数字格式需为10位，不足前面需加0补、非纯数字无需修改）</th><th>服务店编码</th><th>厂家确认结果</th><th>确认时间</th></tr></thead>
              <tbody><tr><td>7123456789012345701</td><td>广州番禺方程豹中心</td><td>0010052200</td><td>0010052280</td><td>{template === "sap-import" ? "0010052209" : "（待厂家填写）"}</td><td>{template === "sap-import" ? "2026-08-12 14:30" : "（待厂家填写）"}</td></tr></tbody>
            </table>
          </div>
          <p>{template === "sap-import" ? "厂家确认结果填写最终有效SAP编码；纯数字编码按10位文本格式校验，不足前补0。" : "模板第一行固定提供示例数据，正式处理时从第二行开始填写。"}</p>
          {template === "sap-import" ? (
            <div className="form-actions">
              <span>导入后以门店ID匹配差异记录，并把厂家确认结果写入有效SAP编码。</span>
              <button type="button" className="button button--primary" onClick={() => { setEffectiveSap(sapDisputes[0].finalSap); setSapImportApplied(true); setTemplate(null); }}>确认导入并更新有效SAP编码</button>
            </div>
          ) : null}
        </section>
      ) : null}

      <MetricStrip items={[
        { label: "SAP 差异", value: "24 家" },
        { label: "待门店确认", value: "11 家", tone: "warning" },
        { label: "财务可代确认", value: "11 家" },
        { label: "今日已确认", value: "13 家", tone: "success" },
      ]} />
      <div className="data-table-wrap">
        <table>
          <thead><tr><th>异议编号</th><th>门店</th><th>有效 SAP</th><th>当前状态</th><th>检测时间</th><th>操作</th></tr></thead>
          <tbody>{sapDisputes.map((row, index) => {
            const currentStatus = index === 0 && sapImportApplied ? "已确认" : row.status;
            return <tr key={row.id}><td>{row.id}</td><td><strong>{row.store}</strong></td><td>{index === 0 ? effectiveSap : row.effectiveSap}</td><td><StatusTag tone={currentStatus === "已确认" ? "success" : "warning"}>{currentStatus}</StatusTag></td><td>{row.detectedAt}</td><td><button type="button" className="text-button" onClick={() => setSelectedSap(row.id)}>查看详情</button></td></tr>;
          })}</tbody>
        </table>
      </div>

      {selectedSapRow ? (
        <aside className="detail-drawer" aria-labelledby="sap-detail-title">
          <header><div><span className="eyebrow">SAP 差异详情</span><h2 id="sap-detail-title">{selectedSapRow.store}</h2></div><button type="button" className="text-button" onClick={() => setSelectedSap(null)}>关闭</button></header>
          <dl><div><dt>门店维护值</dt><dd>{selectedSapRow.storeSap}</dd></div><div><dt>财务导入值</dt><dd>{selectedSapRow.financeSap}</dd></div><div><dt>当前有效 SAP</dt><dd>{effectiveSap}</dd></div><div><dt>影响</dt><dd>请检查SAP编码是否正确，将影响厂端开票</dd></div></dl>
          <footer><span>不一致记录需导出给厂家确认，再通过SAP编码确认模板导入最终有效编码。</span><button type="button" className="button button--primary" onClick={() => { setSelectedSap(null); setTemplate("sap-export"); }}>导出该条差异</button></footer>
        </aside>
      ) : null}
    </section>
  );
}
