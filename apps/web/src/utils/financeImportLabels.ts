const labels: Record<string, string> = {
  businessKey: "业务唯一键", file: "文件",
  storeId: "门店ID", storeName: "门店名称", sapCode: "SAP编码", importedAt: "资料导入时间",
  financeInitialSap: "财务初始SAP编码", serviceStoreCode: "服务门店编码", finalSapCode: "最终有效SAP编码",
  factoryConfirmationResult: "厂家确认结果", confirmedAt: "厂家确认时间", invoiceNumber: "发票号码",
  reviewResult: "厂家审核结果", rejectionReason: "审核不通过原因", settlementDate: "结算日期",
  settlementAmountCent: "结算金额", statementMonth: "业务账期", invoiceDate: "开票日期",
  deductionDate: "厂家扣款日期", deductionAmountCent: "厂家扣款金额", invoiceStatus: "开票状态",
};

export function displayFinanceImportField(field: string): string {
  return labels[field] ?? "其他业务字段";
}
