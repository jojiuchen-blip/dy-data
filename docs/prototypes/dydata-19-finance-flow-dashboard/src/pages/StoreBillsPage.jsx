import { useMemo, useState } from "react";
import { billDirections } from "../data/financeData.js";
import { money } from "../domain/financeRules.js";
import { SolarIcon } from "../components/SolarIcon.jsx";
import { StatusTag } from "../components/StatusTag.jsx";

const orderRows = [
  { order: "DY20260719000842", product: "精诚养车空调深度养护", amount: 4280, rate: "8%" },
  { order: "DY20260722001935", product: "暑期轮胎焕新套餐", amount: 2860, rate: "6%" },
  { order: "DY20260728004318", product: "比亚迪原厂保养套餐", amount: 1980, rate: "6%" },
];

export function StoreBillsPage({ scenario }) {
  const [showDetail, setShowDetail] = useState(false);
  const [disputeOpen, setDisputeOpen] = useState(false);

  const directions = useMemo(() => {
    if (scenario.title === "单方向存在异议") {
      return billDirections.map((direction) =>
        direction.id === "promotion"
          ? {
              ...direction,
              confirmed: 0,
              pending: direction.total,
              status: "异议处理中",
              nextAction: "等待异议处理",
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
  }, [scenario.title]);

  return (
    <section className="business-page" aria-labelledby="store-bills-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">门店端 · 月度账单</span>
          <h1 id="store-bills-title">确认金额后，即可进入开票</h1>
          <p>推广服务费与管理服务费按费用方向和账单版本分别确认，互不阻断。</p>
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
                  <span>{direction.period} · 账单{direction.version}</span>
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
              <div>
                <dt>已确认金额</dt>
                <dd>{money(direction.confirmed)}</dd>
              </div>
              <div>
                <dt>待确认金额</dt>
                <dd>{money(direction.pending)}</dd>
              </div>
            </dl>
            <div className="bill-direction__footer">
              <span>{direction.nextAction}</span>
              {direction.id === "promotion" && direction.status === "已确认" ? (
                <button type="button" className="button button--primary">
                  进入推广费开票
                  <SolarIcon name="arrowRight" />
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
          <span className="eyebrow">核对后再决定</span>
          <h2 id="bill-detail-entry-title">先查看订单明细，再处理账单</h2>
          <p>异议入口放在详情内部，避免未核对订单就直接发起。</p>
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
              <span className="eyebrow">推广服务费 · V1</span>
              <h2 id="bill-detail-title">订单与费率明细</h2>
            </div>
            <span>共 1,284 笔订单 · 当前展示重点订单</span>
          </div>
          <div className="data-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>订单号</th>
                  <th>商品</th>
                  <th>订单金额</th>
                  <th>有效费率</th>
                </tr>
              </thead>
              <tbody>
                {orderRows.map((row) => (
                  <tr key={row.order}>
                    <td>{row.order}</td>
                    <td>{row.product}</td>
                    <td className="amount">{money(row.amount)}</td>
                    <td>{row.rate}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="detail-workbench__actions">
            <span>仍有金额或费率问题？请准备争议订单、说明和证明材料。</span>
            <button type="button" className="text-button" onClick={() => setDisputeOpen(true)}>
              发起账单异议
            </button>
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
