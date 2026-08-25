import { managementInvoices, promotionInvoices } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";
import { StatusTag } from "../components/StatusTag.jsx";

const activeStore = "深圳龙岗比亚迪王朝店";

export function StoreHistoryPage({ scenario }) {
  const promotionRecords = promotionInvoices.filter((invoice) => invoice.store === activeStore);
  const managementRecords = managementInvoices.filter((invoice) => invoice.store === activeStore);
  const promotionRows = promotionRecords.flatMap((invoice) => {
    const periods = invoice.coveredPeriods ?? [invoice.period];
    return periods.map((period) => ({
      ...invoice,
      period,
      isMultiPeriod: periods.length > 1,
    }));
  });
  const promotionStatus = scenario.title === "发票校验或审核失败" ? "已重新开具" : promotionRecords[0].auditStatus;
  const sumPromotionAmount = (predicate, field = "total") => promotionRecords
    .filter(predicate)
    .reduce((total, invoice) => total + Number(invoice[field] ?? 0), 0);
  const promotionTotal = sumPromotionAmount(() => true, "totalFee");
  const confirmedAmount = sumPromotionAmount(() => true, "confirmedAmount");
  const invoicedAmount = sumPromotionAmount((invoice) => /^\d{20}$/.test(invoice.invoiceNumber));
  const settledAmount = sumPromotionAmount((invoice) => invoice.auditStatus.includes("审核通过") || invoice.auditStatus.includes("已结算"));
  const failedAuditAmount = promotionStatus === "已重新开具"
    ? 0
    : sumPromotionAmount((invoice) => invoice.auditStatus.includes("不通过"));
  const promotionStatusTone = promotionStatus.includes("不通过")
    ? "danger"
    : promotionStatus.includes("通过") || promotionStatus.includes("重新开具")
      ? "success"
      : "info";
  return (
    <section className="business-page" aria-labelledby="store-history-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">门店端 · 发票状态查看</span>
          <h1 id="store-history-title">查看发票审核状态与历史调整</h1>
          <p>只展示门店需要处理或核对的信息，不提供厂端发票附件下载。</p>
        </div>
      </header>

      <dl className="metric-strip" aria-label="推广服务费金额汇总">
        <div>
          <dt>推广服务费总额</dt>
          <dd>{money(promotionTotal)}</dd>
        </div>
        <div>
          <dt>已确认金额</dt>
          <dd>{money(confirmedAmount)}</dd>
        </div>
        <div>
          <dt>已开票金额</dt>
          <dd>{money(invoicedAmount)}</dd>
        </div>
        <div>
          <dt>发票审核通过已结算金额</dt>
          <dd>{money(settledAmount)}</dd>
        </div>
        <div>
          <dt>发票审核未通过金额</dt>
          <dd>{money(failedAuditAmount)}</dd>
        </div>
      </dl>

      <section className="history-section" aria-labelledby="promotion-history-title">
        <div className="section-heading">
          <div>
            <span className="eyebrow">门店开具</span>
            <h2 id="promotion-history-title">推广服务费发票记录</h2>
          </div>
        </div>
        <div className="data-table-wrap history-table">
          <table aria-label="推广服务费发票记录">
            <thead>
              <tr>
                <th>账期</th>
                <th>是否多账期开票</th>
                <th>金额</th>
                <th>发票号</th>
                <th>开票日期</th>
                <th>提交时间</th>
                <th>审核状态</th>
              </tr>
            </thead>
            <tbody>
              {promotionRows.map((invoice) => (
                <tr key={`${invoice.id}-${invoice.period}`}>
                  <td>{invoice.period}</td>
                  <td>{invoice.isMultiPeriod ? "是" : "否"}</td>
                  <td className="amount">{money(invoice.total)}</td>
                  <td>{invoice.invoiceNumber}</td>
                  <td>{invoice.invoiceDate}</td>
                  <td>{invoice.submittedAt}</td>
                  <td><StatusTag tone={promotionStatusTone}>{promotionStatus}</StatusTag></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="history-section" aria-labelledby="management-history-title">
        <div className="section-heading">
          <div>
            <span className="eyebrow">厂端开具</span>
            <h2 id="management-history-title">管理服务费发票信息</h2>
          </div>
          <span>财务上传后同步发票号码、金额、开票日期、提交时间和最新状态</span>
        </div>
        <div className="data-table-wrap history-table history-table--management">
          <table aria-label="管理服务费发票信息">
            <thead>
              <tr>
                <th>账期</th>
                <th>金额</th>
                <th>发票号</th>
                <th>开票日期</th>
                <th>提交时间</th>
                <th>审核状态</th>
              </tr>
            </thead>
            <tbody>
              {managementRecords.map((invoice) => (
                <tr key={invoice.id}>
                  <td>{invoice.period}</td>
                  <td className="amount">{money(invoice.invoiceAmount)}</td>
                  <td>{invoice.invoiceNumber}</td>
                  <td>{invoice.invoiceDate}</td>
                  <td>{invoice.submittedAt}</td>
                  <td><StatusTag tone={invoice.status === "已开票" ? "success" : "warning"}>{invoice.status}</StatusTag></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="adjustment-ledger" aria-labelledby="adjustment-title">
        <div>
          <span className="eyebrow">差异金额将在下个账期调整</span>
          <h2 id="adjustment-title">2026年8月 · 系统重算差额</h2>
          <p>7月账单已打款，不修改原发票与结算结果；差额在下账期继续抵扣。</p>
        </div>
        <strong>-{money(8420)}</strong>
      </section>
    </section>
  );
}
