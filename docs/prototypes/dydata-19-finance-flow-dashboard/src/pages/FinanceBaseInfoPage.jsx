import { useEffect, useMemo, useState } from "react";
import { ImportTemplatePanel } from "../components/ImportTemplatePanel.jsx";
import { SapDisputesPanel } from "../components/SapDisputesPanel.jsx";
import { StatusTag } from "../components/StatusTag.jsx";
import { WorkbenchToolbar } from "../components/DataWorkbench.jsx";
import { storeBaseInformation } from "../data/financeData.js";
import { exportAllFields } from "../domain/csvExport.js";

const templateFields = [
  "门店ID（所属账户关联poi-id）",
  "服务店名称",
  "SAP编码",
  "导入时间",
];

export function FinanceBaseInfoPage({ scenario }) {
  const [tab, setTab] = useState(scenario?.title === "SAP 编码不一致" ? "sap" : "base");
  const [search, setSearch] = useState("");
  const [panel, setPanel] = useState(null);
  const [notice, setNotice] = useState("");
  const rows = useMemo(() => storeBaseInformation.filter((row) => (
    `${row.poiId}${row.serviceStoreName}${row.effectiveSap}`.toLowerCase().includes(search.toLowerCase())
  )), [search]);

  useEffect(() => {
    if (scenario?.title === "SAP 编码不一致") setTab("sap");
  }, [scenario?.title]);

  function exportBaseInformation() {
    const count = exportAllFields(rows, "门店基础信息.csv");
    setNotice(`已导出 ${count} 条门店基础信息`);
  }

  return (
    <section className="business-page" aria-labelledby="finance-base-info-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">财务一级页面</span>
          <h1 id="finance-base-info-title">门店基础信息</h1>
          <p>以门店ID（所属账户关联poi-id）为主键，维护服务店名称和后续账期使用的有效SAP编码。</p>
        </div>
        {tab === "base" ? (
          <div className="page-heading__actions page-heading__actions--wrap">
            <button type="button" className="button button--secondary" onClick={() => setPanel("template")}>下载基础信息导入模板</button>
            <button type="button" className="button button--secondary" onClick={exportBaseInformation}>导出门店基础信息</button>
            <button type="button" className="button button--primary" onClick={() => setPanel("import")}>导入门店基础信息</button>
          </div>
        ) : null}
      </header>

      <div className="segmented-tabs page-tabs" role="tablist" aria-label="门店基础信息页面">
        <button type="button" role="tab" aria-selected={tab === "base"} onClick={() => setTab("base")}>基础信息</button>
        <button type="button" role="tab" aria-selected={tab === "sap"} onClick={() => setTab("sap")}>SAP异议处理</button>
      </div>

      {tab === "sap" ? <SapDisputesPanel /> : (
        <>
          <div className="validation-banner" role="note">
            <strong>历史账期保留当时快照</strong>
            <span>重新导入的服务店名称和SAP编码仅影响后续新账期，不刷新历史账单与订单明细。</span>
          </div>

          {panel ? <ImportTemplatePanel
            title="基础信息导入模板"
            fields={templateFields}
            sample={["7123456789012345678", "深圳龙岗比亚迪王朝店", "0010028460", "2026-08-12 10:20"]}
            rules={["全部字段必填。", "SAP编码为纯数字时必须为10位，不足前补0；非纯数字保持原值。", "原文件留存政策待 DYDATA-19 财务与审计决策。"]}
            mode={panel}
            onClose={() => setPanel(null)}
            onConfirm={() => { setPanel(null); setNotice("基础信息已按门店ID更新"); }}
          /> : null}

          {notice ? <div className="inline-notice" role="status">{notice}</div> : null}
          <WorkbenchToolbar onSearch={setSearch} searchLabel="搜索门店ID、服务店名称或SAP编码" />
          <div className="data-table-wrap">
            <table>
              <thead><tr><th>门店ID（所属账户关联poi-id）</th><th>服务店名称</th><th>有效SAP编码</th><th>最近导入时间</th><th>SAP确认状态</th></tr></thead>
              <tbody>{rows.map((row) => <tr key={row.poiId}>
                <td>{row.poiId}</td><td><strong>{row.serviceStoreName}</strong></td><td>{row.effectiveSap}</td><td>{row.importedAt}</td><td><StatusTag tone={row.sapStatus === "已确认" ? "success" : "warning"}>{row.sapStatus}</StatusTag></td>
              </tr>)}</tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
