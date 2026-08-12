import { describe, expect, it } from "vitest";
import {
  getConfirmationState,
  getRecomputeOutcome,
  getSettlementMonth,
  validateImportBatch,
  validateInvoice,
} from "./financeRules.js";

describe("DYDATA-19 财务规则", () => {
  it("在无阻断时于6日24点后自动确认", () => {
    expect(
      getConfirmationState({
        day: 7,
        confirmed: false,
        disputed: false,
        systemBlocked: false,
      }),
    ).toBe("已确认");
  });

  it("存在异议时保持整个费用方向未确认", () => {
    expect(
      getConfirmationState({
        day: 7,
        confirmed: false,
        disputed: true,
        systemBlocked: false,
      }),
    ).toBe("异议处理中");
  });

  it("按提交成功时间判断结算归属月", () => {
    expect(getSettlementMonth("2026-08-10T23:59:59+08:00")).toBe("2026-08");
    expect(getSettlementMonth("2026-08-11T00:00:00+08:00")).toBe("2026-09");
  });

  it("拒绝错误的购买方、税率、号码和金额", () => {
    const errors = validateInvoice({
      buyer: "其他公司",
      taxRate: 3,
      invoiceNumber: "123",
      netAmount: 94,
      taxAmount: 5,
      total: 99,
      expectedTotal: 100,
    });

    expect(errors).toHaveLength(5);
    expect(errors[0]).toContain("比亚迪汽车销售有限公司");
  });

  it("强校验不含税金额、税额和价税合计的勾稽关系", () => {
    const errors = validateInvoice({
      buyer: "比亚迪汽车销售有限公司",
      taxRate: 6,
      invoiceNumber: "25322000000178435216",
      netAmount: 100,
      taxAmount: 5,
      total: 106,
      expectedTotal: 106,
    });

    expect(errors).toContain("不含税金额 + 税额必须等于价税合计");
    expect(errors).toContain("不含税金额 × 6% 与税额差异必须小于0.01元");
  });

  it("允许税额与六个百分点计算结果存在小于一分钱的尾差", () => {
    expect(validateInvoice({
      buyer: "比亚迪汽车销售有限公司",
      taxRate: 6,
      invoiceNumber: "25322000000178435216",
      netAmount: 121358.96,
      taxAmount: 7281.54,
      total: 128640.5,
      expectedTotal: 128640.5,
    })).toEqual([]);
  });

  it("任一行失败时整批导入失败且零写入", () => {
    expect(
      validateImportBatch([
        { invoiceNumber: "12345678901234567890", valid: true },
        { invoiceNumber: "bad", valid: false },
      ]),
    ).toEqual({ ok: false, accepted: 0, rejected: 2 });
  });

  it("已打款重算不回滚并把差额放到下一账期", () => {
    expect(getRecomputeOutcome({ paid: true, before: 1000, after: 900 })).toEqual({
      rollback: false,
      notifyStore: false,
      adjustment: -100,
      target: "下一账期",
    });
  });
});
