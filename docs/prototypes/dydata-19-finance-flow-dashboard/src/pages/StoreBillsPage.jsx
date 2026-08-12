import { useMemo, useState } from "react";
import { billDirections, financeOrderDetails } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";
import { SolarIcon } from "../components/SolarIcon.jsx";
import { StatusTag } from "../components/StatusTag.jsx";

export function StoreBillsPage({ scenario, onNavigate }) {
  const [showDetail, setShowDetail] = useState(true);
  const [disputeConfirmOpen, setDisputeConfirmOpen] = useState(false);
  const [disputeOpen, setDisputeOpen] = useState(false);
  const [confirmedDirections, setConfirmedDirections] = useState([]);
  const promotionDetailRows = financeOrderDetails.filter(
    (row) => row.feeDirection === "推广服务费" && row.billingStoreId === "STORE-02846",
  );

  const directions = useMemo(() => {
    if (scenario.title === "门店主动确认") {
      return billDirections.map((direction) =>
        confirmedDirections.includes(direction.id)
          ? direction
          : {
              ...direction,
              confirmed: 0,
              pending: direction.total,
              status: "待确认",
              nextAction: "请核对账单总额",
            },
      );
    }
    if (scenario.title === "单方向存在异议") {
      return billDirections.map((direction) =>
        direction.id === "promotion"
          ? {
              ...direction,
              confirmed: 0,
              pending: direction.total,
              status: "异议处理中",
              nextAction: "待厂端确认异议是否成立",
            }
          : direction,
      );
    }
    if (scenario.title === "系统数据不齐全") {
      return billDirections.map((direction) => ({
        ...direction,
        confirmed: 0,
        pending: direction.total,
        status: "系统异常，待修复",
        nextAction: "修复后自动排查",
      }));
    }
    return billDirections;
  }, [confirmedDirections, scenario.title]);

  function confirmDirection(directionId) {
    setConfirmedDirections((current) =>
      current.includes(directionId) ? current : [...current, directionId],
    );
  }

  return (
    <section className="business-page" aria-labelledby="store-bills-title">
      <div className="validation-banner" role="status">
        <strong>月度账单确认提醒</strong>
        <span>月度结束后，请先确认账单金额，再前往推广服务费开票页面完成操作。</span>
      </div>
      <header className="page-heading">
        <div>
          <span className="eyebrow">门店端 · 单店分账</span>
          <h1 id="store-bills-title">确认金额后，即可进入开票</h1>
          <p>推广服务费与管理服务费按费用方向分别确认，互不阻断。</p>
        </div>
        <div className="deadline-block">
          <span>主动确认截止</span>
          <strong>8月6日 24:00</strong>
          <small>未操作且无异常时自动确认</small>
        </div>
      </header>

      <div className="bill-direction-grid">
        {directions.map((direction) => (
          <article className="bill-direction" key={direction.id}>
            <div className="bill-direction__topline">
              <div className="bill-direction__identity">
                <SolarIcon name={direction.id === "promotion" ? "wallet" : "bill"} />
                <div>
                  <span>{direction.period}</span>
                  <h2>{direction.name}</h2>
                </div>
              </div>
              <StatusTag
                tone={
                  direction.status === "已确认"
                    ? "success"
                    : direction.status.includes("异常")
                      ? "danger"
                      : "warning"
                }
              >
                {direction.status}
              </StatusTag>
            </div>
            <dl className="amount-ledger">
              <div>
                <dt>账单总额</dt>
                <dd>{money(direction.total)}</dd>
              </div>
            </dl>
            <div className="bill-direction__footer">
              <span>{direction.nextAction}</span>
              {direction.status === "待确认" ? (
                <button
                  type="button"
                  className="button button--primary"
                  aria-label={`确认${direction.name}金额`}
                  onClick={() => confirmDirection(direction.id)}
                >
                  确认金额
                </button>
              ) : direction.id === "promotion" && direction.status === "已确认" ? (
                <button
                  type="button"
                  className="button button--primary"
                  onClick={() => onNavigate?.("store-invoices")}
                >
                  进入推广费开票
                  <SolarIcon name="arrowRight" />
                </button>
              ) : direction.id === "management" && direction.status === "已确认" ? (
                <button type="button" className="button button--secondary" disabled>
                  已确认，待厂端开票
                </button>
              ) : (
                <span className="passive-action">系统将同步下一步状态</span>
              )}
            </div>
          </article>
        ))}
      </div>

      <section className="bill-detail-entry" aria-labelledby="bill-detail-entry-title">
        <div>
          <span className="eyebrow">核对后再确认</span>
          <h2 id="bill-detail-entry-title">先查看订单明细，再处理账单</h2>
        </div>
        <button
          type="button"
          className="button button--secondary"
          onClick={() => setShowDetail((current) => !current)}
        >
          {showDetail ? "收起账单详情" : "查看账单详情"}
        </button>
      </section>

      {showDetail ? (
        <section className="detail-workbench" aria-labelledby="bill-detail-title">
          <div className="section-heading">
            <div>
              <span className="eyebrow">推广服务费</span>
              <h2 id="bill-detail-title">推广服务费明细</h2>
            </div>
            <div className="section-heading__actions">
              <span>共 1,284 笔订单</span>
            </div>
          </div>
          <div className="data-table-wrap store-order-detail-table">
            <table aria-label="门店推广服务费明细">
              <thead>
                <tr><th>订单号</th><th>商品</th><th>销售渠道</th><th>核销时间</th><th>实收金额</th><th>有效费率</th><th>推广服务费</th></tr>
              </thead>
              <tbody>
                {promotionDetailRows.map((row) => (
                  <tr key={row.id}>
                    <td><strong>{row.orderId}</strong></td>
                    <td>{row.productName}</td>
                    <td>{row.saleChannel}</td>
                    <td>{row.verifyTime}</td>
                    <td className="amount">{money(row.receivedAmount)}</td>
                    <td>{row.feeRate}</td>
                    <td className="amount">{money(row.receivedAmount * Number.parseFloat(row.feeRate) / 100)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="detail-workbench__actions">
            <span>如对账单金额、费率有异议，请准备争议订单、说明、证明材料后发起；待厂端审核确认。</span>
            <button type="button" className="text-button text-button--compact text-button--quiet" onClick={() => setDisputeConfirmOpen(true)}>
              发起账单异议
            </button>
          </div>
        </section>
      ) : null}

      {disputeConfirmOpen ? (
        <section className="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby="dispute-confirm-title">
          <span className="eyebrow">提交前确认</span>
          <h2 id="dispute-confirm-title">确认发起账单异议</h2>
          <p>发起异议前请准备充分资料，是否发起？</p>
          <div className="form-actions">
            <button type="button" className="button button--secondary" onClick={() => setDisputeConfirmOpen(false)}>取消</button>
            <button type="button" className="button button--primary" onClick={() => { setDisputeConfirmOpen(false); setDisputeOpen(true); }}>确认发起</button>
          </div>
        </section>
      ) : null}

      {disputeOpen ? (
        <section className="inline-form" aria-labelledby="dispute-form-title">
          <div className="section-heading">
            <div>
              <span className="eyebrow">异常分支</span>
              <h2 id="dispute-form-title">发起推广服务费账单异议</h2>
            </div>
            <button type="button" className="text-button" onClick={() => setDisputeOpen(false)}>
              返回账单详情
            </button>
          </div>
          <div className="form-grid">
            <label>
              <span>异议类型</span>
              <select defaultValue="费率设置错误">
                <option>费率设置错误</option>
                <option>订单遗漏</option>
                <option>其他</option>
              </select>
            </label>
            <label>
              <span>争议金额</span>
              <input inputMode="decimal" defaultValue="12480.00" />
            </label>
            <label className="form-grid__wide">
              <span>争议订单</span>
              <input defaultValue="DY20260719000842、DY20260722001935" />
            </label>
            <label className="form-grid__wide">
              <span>问题说明</span>
              <textarea defaultValue="7月15日后费率与双方确认记录不一致，请核对费率配置日志。" />
            </label>
            <label className="form-grid__wide">
              <span>证明材料</span>
              <input type="file" />
            </label>
          </div>
          <div className="form-actions">
            <span>提交后系统先检测数据，该费用方向整期保持未确认。</span>
            <button type="button" className="button button--primary">
              提交异议并开始检测
            </button>
          </div>
        </section>
      ) : null}
    </section>
  );
}
