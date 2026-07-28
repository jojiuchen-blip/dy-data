const processSteps = [
  "月度账单待确认",
  "门店确认账单",
  "门店开具推广服务费发票",
  "发票提交财务审核",
  "审核完成并进入结算",
];

export function InvoiceGuidePage() {
  return (
    <div className="page-stack invoice-guide">
      <section className="page-heading">
        <div>
          <p className="eyebrow">门店结算</p>
          <h1>开票确认</h1>
          <p>当前不提供在线开票或财务操作，本页仅说明未来流程和准备口径。</p>
        </div>
        <span className="source-pill">当前功能暂未开放</span>
      </section>

      <section className="content-section">
        <div className="section-title"><div><h2>账单确认与开票</h2><p>以下仅说明顺序，不代表任何门店的实时进度。</p></div></div>
        <ol className="invoice-process" aria-label="开票流程说明">
          {processSteps.map((step, index) => (
            <li key={step}><span>{String(index + 1).padStart(2, "0")}</span><strong>{step}</strong><small>流程节点</small></li>
          ))}
        </ol>
      </section>

      <section className="invoice-guide-grid" aria-label="开票准备">
        <article className="content-section">
          <p className="eyebrow">前置条件</p><h2>先完成费用核对</h2>
          <ul><li>正式账期从 2026-08 开始</li><li>2026-07 为测试账期，不进入正式开票准备</li><li>先在单店分账核对汇总，再到订单费用明细追溯依据</li></ul>
        </article>
        <article className="content-section">
          <p className="eyebrow">需准备材料</p><h2>具体字段待财务确认</h2>
          <ul><li>门店开票主体与纳税人识别信息</li><li>已确认月度账单与推广服务费订单明细</li><li>其他资质或证明材料以上线通知为准</li></ul>
        </article>
        <article className="content-section">
          <p className="eyebrow">预计开票范围</p><h2>只包含推广服务费</h2>
          <ul><li>仅限正式账期已确认账单中的推广服务费</li><li>管理服务费属于应扣费用，不计入开票金额</li><li>未确认账单和测试数据不纳入</li></ul>
        </article>
      </section>

      <section className="content-section invoice-support">
        <div><p className="eyebrow">支持渠道</p><h2>正式入口待上线通知</h2><p>当前页面不提供在线提交。需要协助时，请联系既有区域运营或财务对接人。</p></div>
        <div className="invoice-faq">
          <details open><summary>现在能在系统里开票吗？</summary><p>不能。当前仅提供流程和准备指引。</p></details>
          <details><summary>2026-07 测试账单需要开票吗？</summary><p>不需要进入正式开票准备。</p></details>
          <details><summary>账单金额或订单归属有疑问怎么办？</summary><p>先核对单店分账汇总，再下钻订单费用明细检查业务 ID、费用方向、费率、调整和规则版本，最后联系既有对接人。</p></details>
        </div>
      </section>
    </div>
  );
}
