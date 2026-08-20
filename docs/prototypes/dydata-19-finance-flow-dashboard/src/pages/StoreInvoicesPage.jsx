import { useRef, useState } from "react";
import { promotionInvoices } from "../data/financeData.js";
import { money, REQUIRED_BUYER, validateInvoice } from "../domain/financeRules.js";
import { SolarIcon } from "../components/SolarIcon.jsx";
import { StatusTag } from "../components/StatusTag.jsx";

const expectedTotal = 128640.5;
const invoiceRecipient = [
  { label: "名称", value: REQUIRED_BUYER },
  { label: "纳税人识别号", value: "914403007604674476" },
  { label: "地址", value: "深圳市坪山新区坪山街道比亚迪路3005号" },
  { label: "电话", value: "0755-89888888" },
  { label: "开户行及账号", value: "农行龙岗支行 41022900040008463" },
  { label: "项目名称", value: "推广服务费" },
  { label: "税收分类编码", value: "3079900000000000000" },
  { label: "税率", value: "6%" },
  { label: "价税合计", value: money(expectedTotal) },
];

const allInvoiceInformation = invoiceRecipient
  .map(({ label, value }) => `${label}：${value}`)
  .join("\n");

export function StoreInvoicesPage({ scenario }) {
  const [form, setForm] = useState({
    buyer: "",
    taxRate: "",
    invoiceNumber: "",
    invoiceDate: "2026-08-08",
    netAmount: "121358.96",
    taxAmount: "7281.54",
    total: "128640.50",
  });
  const [errors, setErrors] = useState([]);
  const [copied, setCopied] = useState("");
  const invoiceFormRef = useRef(null);

  function updateField(event) {
    const value = event.target.name === "taxRate"
      ? event.target.value.replace(/\D/g, "")
      : event.target.value;
    setForm((current) => ({ ...current, [event.target.name]: value }));
  }

  function copyText(label, value) {
    setCopied(label);
    navigator.clipboard?.writeText(value).catch(() => undefined);
  }

  function copyAllInvoiceInformation() {
    copyText("全部开票信息", allInvoiceInformation);
    invoiceFormRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    invoiceFormRef.current?.focus();
  }

  function submitInvoice(event) {
    event.preventDefault();
    setErrors(
      validateInvoice({
        ...form,
        expectedTotal,
        duplicateInvoiceNumbers: promotionInvoices
          .map((invoice) => invoice.invoiceNumber)
          .filter((invoiceNumber) => /^\d{20}$/.test(invoiceNumber)),
      }),
    );
  }

  const failedInvoice = promotionInvoices.find((invoice) => invoice.auditStatus.includes("不通过"));

  return (
    <section className="business-page" aria-labelledby="store-invoices-title">
      <header className="page-heading">
        <div>
          <span className="eyebrow">门店端 · 推广服务费开票</span>
          <h1 id="store-invoices-title">门店前往开票系统开具数电专票，再将发票信息上传系统，否则将无法收款。</h1>
          <p className="page-heading__lead page-heading__lead--urgent">当月10号前开票提交，当月结算；10号后开票提交将在下月结算。</p>
        </div>
      </header>

      {scenario.title === "发票校验或审核失败" ? (
        <section className="audit-failure" role="status">
          <SolarIcon name="danger" />
          <div>
            <StatusTag tone="danger">发票审核不通过，请查看原因，红冲后重新开票上传</StatusTag>
            <h2>{failedInvoice.invoiceNumber}</h2>
            <p>{failedInvoice.auditReason}。原发票已退出已开票金额，2026年7月账期已重新转为待开票。</p>
          </div>
        </section>
      ) : null}

      <div className="invoice-layout">
        <section className="invoice-brief" aria-label="收票方与开票信息">
          <div className="section-heading">
            <div>
              <span className="eyebrow">收票方与开票信息</span>
            </div>
            <div className="invoice-copy-action">
              {copied ? <StatusTag tone="success">已复制{copied}</StatusTag> : null}
              <button
                type="button"
                className="button button--secondary"
                onClick={copyAllInvoiceInformation}
              >
                <SolarIcon name="copy" />
                一键复制全部开票信息
              </button>
            </div>
          </div>
          <div className="validation-banner validation-banner--danger invoice-required-notice invoice-required-notice--brief">
            <strong>历史讨论场景：开票后需回原系统提交</strong>
            <span>本原型不会上传发票、触发审核或打款。</span>
          </div>
          <dl className="copy-list">
            {invoiceRecipient.map(({ label, value }) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <div className="period-coverage">
            <span>当前开票账期</span>
            <strong>2026年7月</strong>
            <small>默认一张发票对应一个完整账期，一个账期不能拆成多张。</small>
          </div>
        </section>

        <form
          ref={invoiceFormRef}
          className="invoice-form"
          aria-labelledby="invoice-form-title"
          tabIndex="-1"
          onSubmit={submitInvoice}
          noValidate
        >
          <div className="section-heading">
            <div>
              <span className="eyebrow">发票提交</span>
              <h2 id="invoice-form-title">填写数电专票信息</h2>
            </div>
            <StatusTag tone="warning">待开票</StatusTag>
          </div>
          <div className="validation-banner validation-banner--danger invoice-required-notice" role="alert">
            <strong>历史讨论场景：开票后需回原系统提交</strong>
            <span>本原型不会上传发票、触发审核或打款。</span>
          </div>
          <div className="form-grid">
            <label className="form-grid__wide">
              <span>购买方</span>
              <input name="buyer" value={form.buyer} onChange={updateField} />
            </label>
            <label>
              <span>税率</span>
              <span className="input-with-suffix">
                <input aria-label="税率" name="taxRate" inputMode="numeric" pattern="[0-9]*" value={form.taxRate} onChange={updateField} />
                <span className="input-suffix" aria-hidden="true">%</span>
              </span>
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
              <input aria-label="价税合计" name="total" inputMode="decimal" value={form.total} onChange={updateField} />
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
              <ul>
                <li>购买方必须为比亚迪汽车销售有限公司，税率必须为6%。</li>
                <li>数电专票号码必须为20位纯数字且不得重复。</li>
                <li>不含税金额 + 税额必须等于价税合计。</li>
                <li>不含税金额 × 6% 与税额差异必须小于0.01元。</li>
              </ul>
            )}
          </div>
          <button type="submit" className="button button--primary button--full">
            演示动作：校验并提交发票
          </button>
        </form>
      </div>
    </section>
  );
}
