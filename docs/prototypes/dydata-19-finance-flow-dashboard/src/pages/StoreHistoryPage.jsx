import { managementInvoices, promotionInvoices } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";
import { StatusTag } from "../components/StatusTag.jsx";

export function StoreHistoryPage() {
  return (
    <section className="business-page" aria-labelledby="store-history-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">门店端 · 发票与调整记录</span>
          <h1 id="store-history-title">审核结果、管理服务费发票和调整都可追溯</h1>
          <p>只展示门店需要处理或核对的信息，不提供厂端发票附件下载。</p>
        </div>
      </header>

      <dl className="metric-strip" aria-label="推广服务费金额汇总">
        <div>
          <dt>推广服务费总额</dt>
          <dd>{money(301880.5)}</dd>
        </div>
        <div>
          <dt>已确认金额</dt>
          <dd>{money(301880.5)}</dd>
        </div>
        <div>
          <dt>已开票金额</dt>
          <dd>{money(225460.5)}</dd>
        </div>
        <div>
          <dt>发票审核通过金额</dt>
          <dd>{money(96820)}</dd>
        </div>
        <div>
          <dt>发票审核未通过金额</dt>
          <dd>{money(76420)}</dd>
        </div>
      </dl>

      <section className="history-section" aria-labelledby="promotion-history-title">
        <div className="section-heading">
          <div>
            <span className="eyebrow">门店开具</span>
            <h2 id="promotion-history-title">推广服务费发票记录</h2>
          </div>
        </div>
        <div className="record-list">
          {promotionInvoices.map((invoice) => (
            <article key={invoice.id}>
              <div>
                <span>{invoice.period} · {invoice.invoiceNumber}</span>
                <strong>{money(invoice.total)}</strong>
              </div>
              <StatusTag tone={invoice.auditStatus.includes("通过") ? "success" : invoice.auditStatus.includes("不通过") ? "danger" : "info"}>
                {invoice.auditStatus}
              </StatusTag>
              <p>{invoice.auditReason === "—" ? `提交成功时间：${invoice.submittedAt}` : `原因：${invoice.auditReason}`}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="history-section" aria-labelledby="management-history-title">
        <div className="section-heading">
          <div>
            <span className="eyebrow">厂端开具</span>
            <h2 id="management-history-title">管理服务费发票信息</h2>
          </div>
          <span>仅提供发票号码、金额和开票时间</span>
        </div>
        <div className="record-list record-list--compact">
          {managementInvoices.map((invoice) => (
            <article key={invoice.id}>
              <div>
                <span>{invoice.period} · {invoice.invoiceNumber}</span>
                <strong>{money(invoice.invoiceAmount)}</strong>
              </div>
              <StatusTag tone={invoice.status === "已开票" ? "success" : "warning"}>{invoice.status}</StatusTag>
              <p>开票时间：{invoice.issuedAt}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="adjustment-ledger" aria-labelledby="adjustment-title">
        <div>
          <span className="eyebrow">下账期调整</span>
          <h2 id="adjustment-title">2026年8月 · 系统重算差额</h2>
          <p>7月账单已打款，不修改原发票与结算结果；差额在下账期继续抵扣。</p>
        </div>
        <strong>-{money(8420)}</strong>
      </section>
    </section>
  );
}
