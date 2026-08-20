import { describe, expect, it } from "vitest";
import { financeOrderDetails } from "../data/financeData.js";
import * as csvExport from "./csvExport.js";

function expectedOriginalFee(row) {
  const amountCent = Math.round(row.receivedAmount * 100);
  const rateBasisPoints = Math.round(Number.parseFloat(row.feeRate) * 100);
  return Math.round((amountCent * rateBasisPoints) / 10000) / 100;
}

describe("订单费用 CSV", () => {
  it("每行原始费用按该行实收金额和有效费率计算", () => {
    for (const row of financeOrderDetails) {
      expect(row.originalFee).toBe(expectedOriginalFee(row));
    }
  });

  it("CSV 中逐行保留与页面数据相同的原始费用", () => {
    expect(csvExport.buildCsv).toBeTypeOf("function");
    const csv = csvExport.buildCsv(financeOrderDetails);
    const [header, ...lines] = csv.split("\n");
    const fields = header.split(",");
    const originalFeeIndex = fields.indexOf("originalFee");

    expect(originalFeeIndex).toBeGreaterThanOrEqual(0);
    expect(lines.map((line) => Number(line.split(",")[originalFeeIndex]))).toEqual(
      financeOrderDetails.map((row) => row.originalFee),
    );
  });
});
