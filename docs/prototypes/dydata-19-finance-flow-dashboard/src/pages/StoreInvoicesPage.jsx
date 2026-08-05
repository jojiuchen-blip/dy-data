import { useState } from "react";
import { promotionInvoices } from "../data/financeData.js";
import { money, REQUIRED_BUYER, validateInvoice } from "../domain/financeRules.js";
import { SolarIcon } from "../components/SolarIcon.jsx";
import { StatusTag } from "../components/StatusTag.jsx";

const expectedTotal = 128640.5;

export function StoreInvoicesPage({ scenario }) {
  const [form, setForm] = useState({
    buyer: REQUIRED_BUYER,
    taxRate: "6",
    invoiceNumber: "",
    invoiceDate: "2026-08-08",
    netAmount: "121358.96",
    taxAmount: "7281.54",
    total: "128640.50",
  });
  const [errors, setErrors] = useState([]);
  const [copied, setCopied] = useState("");

  function updateField(event) {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }));
  }

  function copyText(label, value) {
    setCopied(label);
    navigator.clipboard?.writeText(value).catch(() => undefined);
  }

  function submitInvoice(event) {
    event.preventDefault();
    setErrors(
      validateInvoice({
        ...form,
        taxRate: Number(form.taxRate),
        total: Number(form.total),
        expectedTotal,
      }),
    );
  }

  const failedInvoice = promotionInvoices.find((invoice) => invoice.auditStatus.includes("不通过"));

  return (
    <section className="business-page" aria-labelledby="store-invoices-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">门店端 · 推广服务费开票</span>
          <h1 id="store-invoices-title">开票信息可复制，提交后先由系统校验</h1>
          <p>门店前往开票系统开具数电专票，再将五项发票信息填回本页。</p>
        </div>
        <div className="deadline-block deadline-block--urgent">
          <span>当月结算截止</span>
          <strong>8月10日 24:00</strong>
          <small>仅看系统提交成功时间</small>
        </div>
      </header>

      {scenario.title === "发票校验或审核失败" ? (
        <section className="audit-failure" role="status">
          <SolarIcon name="danger" />
          <div>
            <StatusTag tone="danger">审核不通过，请红冲重开</StatusTag>
            <h2>{failedInvoice.invoiceNumber}</h2>
            <p>{failedInvoice.auditReason}。原发票已退出已开票金额，2026年7月账期已重新转为待开票。</p>
          </div>
        </section>
      ) : null}

      <div className="invoice-layout">
        <section className="invoice-brief" aria-labelledby="invoice-brief-title">
          <div className="section-heading">
            <div>
              <span className="eyebrow">开票抬头</span>
              <h2 id="invoice-brief-title">复制到开票系统</h2>
            </div>
            {copied ? <StatusTag tone="success">已复制{copied}</StatusTag> : null}
          </div>
          <dl className="copy-list">
            <div>
              <dt>购买方</dt>
              <dd>{REQUIRED_BUYER}</dd>
              <button type="button" aria-label="复制购买方" onClick={() => copyText("购买方", REQUIRED_BUYER)}>
                <SolarIcon name="copy" />
              </button>
            </div>
            <div>
              <dt>发票项目</dt>
              <dd>推广服务费</dd>
              <button type="button" aria-label="复制发票项目" onClick={() => copyText("发票项目", "推广服务费")}>
                <SolarIcon name="copy" />
              </button>
            </div>
            <div>
              <dt>税率</dt>
              <dd>6%</dd>
              <button type="button" aria-label="复制税率" onClick={() => copyText("税率", "6%")}>
                <SolarIcon name="copy" />
              </button>
            </div>
            <div>
              <dt>价税合计</dt>
              <dd>{money(expectedTotal)}</dd>
              <button type="button" aria-label="复制价税合计" onClick={() => copyText("价税合计", String(expectedTotal))}>
                <SolarIcon name="copy" />
              </button>
            </div>
          </dl>
          <div className="period-coverage">
            <span>本张发票覆盖</span>
            <strong>2026年7月 · 完整账期</strong>
            <small>一张可覆盖多个连续完整账期，但一个账期不能拆成多张。</small>
          </div>
        </section>

        <form className="invoice-form" onSubmit={submitInvoice} noValidate>
          <div className="section-heading">
            <div>
              <span className="eyebrow">发票提交</span>
              <h2>填写数电专票信息</h2>
            </div>
            <StatusTag tone="warning">待开票</StatusTag>
          </div>
          <div className="form-grid">
            <label className="form-grid__wide">
              <span>购买方</span>
              <input name="buyer" value={form.buyer} onChange={updateField} />
            </label>
            <label>
              <span>税率</span>
              <select name="taxRate" value={form.taxRate} onChange={updateField}>
                <option value="6">6%</option>
                <option value="3">3%</option>
              </select>
            </label>
            <label>
              <span>开票日期</span>
              <input type="date" name="invoiceDate" value={form.invoiceDate} onChange={updateField} />
            </label>
            <label className="form-grid__wide">
              <span>数电专票号码</span>
              <input
                name="invoiceNumber"
                inputMode="numeric"
                maxLength={20}
                value={form.invoiceNumber}
                onChange={updateField}
                placeholder="请输入20位纯数字"
              />
            </label>
            <label>
              <span>不含税金额</span>
              <input name="netAmount" inputMode="decimal" value={form.netAmount} onChange={updateField} />
            </label>
            <label>
              <span>税额</span>
              <input name="taxAmount" inputMode="decimal" value={form.taxAmount} onChange={updateField} />
            </label>
            <label className="form-grid__wide">
              <span>价税合计</span>
              <input name="total" inputMode="decimal" value={form.total} onChange={updateField} />
              <small>必须等于所选全部账期的已确认推广服务费。</small>
            </label>
          </div>
          <div className="form-feedback" aria-live="polite">
            {errors.length ? (
              <ul>
                {errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            ) : (
              <p>系统仅进行格式、重复性和金额校验，不调用外部验真服务。</p>
            )}
          </div>
          <button type="submit" className="button button--primary button--full">
            校验并提交发票
          </button>
        </form>
      </div>
    </section>
  );
}
