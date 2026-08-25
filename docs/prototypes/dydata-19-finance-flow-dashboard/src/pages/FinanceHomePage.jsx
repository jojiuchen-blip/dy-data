import { SolarIcon } from "../components/SolarIcon.jsx";

const entries = [
  { page: "finance-base-info", icon: "shop", title: "门店基础信息", detail: "按门店ID维护服务店名称、SAP编码与有效SAP结果。" },
  { page: "finance-promotion", icon: "wallet", title: "推广服务费", detail: "查看全量门店确认、发票提交、厂端审核与结算结果。" },
  { page: "finance-management", icon: "bill", title: "管理服务费", detail: "批量登记厂端开票号码、金额和开票时间。" },
  { page: "finance-disputes", icon: "danger", title: "账单异议", detail: "统一处理 SAP 编码差异和账单金额费率异议。" },
  { page: "finance-imports", icon: "document", title: "导入记录", detail: "统一查看四类批量导入日志；留存政策待 DYDATA-19 财务与审计决策。" },
];

export function FinanceHomePage({ onNavigate }) {
  return (
    <section className="business-page finance-home" aria-labelledby="finance-home-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">财务（系统权限：管理员角色）</span>
          <h1 id="finance-home-title">选择要处理的财务业务</h1>
          <p>一级页面只负责分流；任务数量、金额和操作均放在对应二级页面顶部。</p>
        </div>
        <span className="scope-note">全量门店 · 2026年7月账期</span>
      </header>
      <div className="finance-entry-grid">
        {entries.map((entry) => (
          <button type="button" className="finance-entry" aria-label={`进入${entry.title}`} key={entry.page} onClick={() => onNavigate(entry.page)}>
            <span className="finance-entry__icon"><SolarIcon name={entry.icon} size={24} /></span>
            <span>
              <strong>{entry.title}</strong>
              <small>{entry.detail}</small>
            </span>
            <SolarIcon name="arrowRight" />
          </button>
        ))}
      </div>
    </section>
  );
}
