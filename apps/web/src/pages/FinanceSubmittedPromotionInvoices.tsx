import { useState } from "react";
import { downloadSubmittedPromotionInvoices, fetchSubmittedPromotionInvoices } from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { SelectField, TextField } from "../components/FormControls";
import { TablePagination } from "../components/TablePagination";
import { useApiResource } from "../hooks/useApiResource";
import type { SubmittedPromotionInvoiceRow } from "../types/dashboard";
import { formatCurrency, formatDateTime } from "../utils/format";
import { isStatementMonth } from "../utils/statementMonth";
import { userFacingError } from "../utils/userFacingError";
import { displayFinanceInvoiceStatus } from "../utils/userFacingLabels";

export const promotionInvoiceStatusOptions = [
  { value: "", label: "全部状态" },
  { value: "SUBMITTED_PENDING_FACTORY_REVIEW", label: "提交成功，待厂端审核" },
  { value: "APPROVED_SETTLED", label: "审核通过，已结算" },
  { value: "REJECTED_REUPLOAD", label: "审核不通过" },
];

const PAGE_SIZE = 50;
const columns: Column<SubmittedPromotionInvoiceRow>[] = [
  { key: "store", title: "门店", minWidth: 210, sticky: true, render: (row) => row.storeName ?? row.storeId },
  { key: "number", title: "数电专票号码", minWidth: 210, render: (row) => row.invoiceNumber },
  { key: "amount", title: "发票金额", align: "right", render: (row) => formatCurrency(row.invoiceAmountCent) },
  { key: "submitted", title: "提交时间", minWidth: 160, render: (row) => formatDateTime(row.registeredAt) },
  { key: "month", title: "原账期", minWidth: 110, render: (row) => row.statementMonths.join("、") || "—" },
  { key: "settlementMonth", title: "结算归属月", minWidth: 110, render: (row) => row.settlementBatchMonths.join("、") || "—" },
  { key: "status", title: "发票审核状态", minWidth: 165, render: (row) => displayFinanceInvoiceStatus(row.status) },
  { key: "reason", title: "审核原因", minWidth: 150, render: (row) => row.rejectionReason ?? "—" },
  { key: "sap", title: "有效 SAP", minWidth: 120, render: (row) => row.effectiveSapCode ?? "—" },
];

export function FinanceSubmittedPromotionInvoices() {
  const [month, setMonth] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [exportBusy, setExportBusy] = useState(false);
  const [notice, setNotice] = useState<{ key: string; text: string; error?: boolean }>();
  const query = {
    month: isStatementMonth(month) ? month : undefined,
    q: search.trim() || undefined,
    invoiceStatus: status || undefined,
  };
  const filterKey = JSON.stringify(query);
  const requestKey = JSON.stringify([filterKey, page]);
  const resource = useApiResource(async () => {
    const response = await fetchSubmittedPromotionInvoices({ ...query, page, pageSize: PAGE_SIZE });
    return { ...response, data: { ...response.data, requestKey } };
  }, [requestKey], { clearOnReload: true });
  const data = resource.data?.data.requestKey === requestKey ? resource.data.data : undefined;
  const busy = resource.loading || resource.refreshing;
  const error = resource.rawError ? userFacingError(resource.rawError, "门店发票读取失败，请重试。") : undefined;
  const handleExport = async () => {
    setExportBusy(true);
    setNotice(undefined);
    try {
      const result = await downloadSubmittedPromotionInvoices(query);
      setNotice({ key: filterKey, text: result.result === "EMPTY" ? "已导出空表。" : "发票已导出。" });
    } catch (error) {
      setNotice({ key: filterKey, text: userFacingError(error, "导出失败，请稍后重试。"), error: true });
    } finally {
      setExportBusy(false);
    }
  };

  return (
    <>
      <section className="finance-workbench" aria-label="门店提交发票筛选">
        <div className="finance-workbench__filters">
          <TextField label="搜索" maxLength={255} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="搜索门店、SAP 或发票号码" type="search" value={search} />
          <TextField label="原账期（可选）" onChange={(event) => { setMonth(event.target.value); setPage(1); }} type="month" value={month} />
          <SelectField label="发票审核状态" onChange={(value) => { setStatus(value); setPage(1); }} options={promotionInvoiceStatusOptions} value={status} />
        </div>
        <div className="finance-workbench__actions">
          <Button disabled={busy || !data} loading={exportBusy} onClick={handleExport} variant="secondary">导出发票</Button>
          <Button disabled={busy} onClick={resource.reload} variant="text">刷新发票</Button>
          <Button onClick={() => { setSearch(""); setMonth(""); setStatus(""); setPage(1); setNotice(undefined); }} variant="text">重置筛选</Button>
        </div>
      </section>
      {notice?.key === filterKey ? <p role={notice.error ? "alert" : "status"}>{notice.text}</p> : null}
      <section className="content-section" aria-label="门店提交的推广费发票">
        <DataTable columns={columns} emptyText="当前筛选下没有门店提交的发票" errorText={error}
          rows={data?.list ?? []} state={busy || (!data && !error) ? "loading" : error ? "error" : "ready"}
          tableClassName="finance-fee-table" />
        {data ? <TablePagination loading={busy} onPageChange={setPage} page={data.page} pageSize={PAGE_SIZE}
          rowsOnPage={data.list.length} total={data.total} totalPages={Math.max(1, Math.ceil(data.total / PAGE_SIZE))} /> : null}
      </section>
    </>
  );
}
