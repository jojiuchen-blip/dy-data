import { useEffect, useId, useState, type FormEvent } from "react";
import { formatInteger } from "../utils/format";
import { Button } from "./Button";
import { SelectField } from "./FormControls";

interface TablePaginationProps {
  loading?: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
  page: number;
  pageSize: number;
  pageSizeOptions?: number[];
  rowsOnPage?: number;
  total: number;
  totalPages: number;
}

function clampPage(page: number, totalPages: number): number {
  return Math.min(Math.max(1, page), Math.max(1, totalPages));
}

export function TablePagination({
  loading = false,
  onPageChange,
  onPageSizeChange,
  page,
  pageSize,
  pageSizeOptions = [],
  rowsOnPage,
  total,
  totalPages,
}: TablePaginationProps) {
  const inputId = useId();
  const safeTotal = Math.max(0, total);
  const safeTotalPages = Math.max(1, totalPages);
  const safePageSize = Math.max(1, pageSize);
  const currentPage = clampPage(page, safeTotalPages);
  const rangeStart = safeTotal > 0 ? (currentPage - 1) * safePageSize + 1 : 0;
  const computedRangeEnd =
    rowsOnPage !== undefined
      ? rangeStart + Math.max(0, rowsOnPage) - 1
      : currentPage * safePageSize;
  const rangeEnd = safeTotal > 0 ? Math.min(safeTotal, computedRangeEnd) : 0;
  const [pageInput, setPageInput] = useState(String(currentPage));
  const [pageError, setPageError] = useState<string | null>(null);
  const canMoveBackward = !loading && currentPage > 1;
  const canMoveForward = !loading && currentPage < safeTotalPages;
  const canResize = Boolean(onPageSizeChange && pageSizeOptions.length);

  useEffect(() => {
    setPageInput(String(currentPage));
    setPageError(null);
  }, [currentPage]);

  const commitPage = () => {
    const parsed = Number(pageInput);
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > safeTotalPages) {
      setPageError(`请输入 1-${formatInteger(safeTotalPages)} 之间的页码。`);
      return;
    }
    setPageError(null);
    onPageChange(parsed);
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!loading) {
      commitPage();
    }
  };

  return (
    <nav className="table-pagination" aria-label="表格分页">
      <div className="table-pagination__info">
        <strong>
          显示 {formatInteger(rangeStart)}-{formatInteger(rangeEnd)} / 共{" "}
          {formatInteger(safeTotal)} 条
        </strong>
        <span>
          第 {formatInteger(currentPage)} / {formatInteger(safeTotalPages)} 页
        </span>
      </div>

      <form className="table-pagination__controls" onSubmit={handleSubmit}>
        {canResize ? (
          <SelectField
            className="table-pagination__size"
            label="每页条数"
            onChange={(value) => {
              onPageSizeChange?.(Number(value));
            }}
            options={pageSizeOptions.map((option) => ({
              label: `每页 ${formatInteger(option)} 条`,
              value: String(option),
            }))}
            value={String(pageSize)}
          />
        ) : null}

        <Button
          className="table-pagination__button table-pagination__first"
          disabled={!canMoveBackward}
          onClick={() => onPageChange(1)}
          size="sm"
          variant="secondary"
        >
          首页
        </Button>
        <Button
          className="table-pagination__button"
          disabled={!canMoveBackward}
          onClick={() => onPageChange(currentPage - 1)}
          size="sm"
          variant="secondary"
        >
          上一页
        </Button>

        <label className="table-pagination__page" htmlFor={inputId}>
          <span>第</span>
          <input
            aria-invalid={pageError ? true : undefined}
            aria-label="输入页码"
            className="table-pagination__page-input"
            disabled={loading}
            id={inputId}
            inputMode="numeric"
            max={safeTotalPages}
            min={1}
            onChange={(event) => setPageInput(event.target.value)}
            type="number"
            value={pageInput}
          />
          <span>/ {formatInteger(safeTotalPages)} 页</span>
        </label>

        <Button
          className="table-pagination__button table-pagination__jump"
          disabled={loading}
          size="sm"
          type="submit"
          variant="secondary"
        >
          跳转
        </Button>
        <Button
          className="table-pagination__button"
          disabled={!canMoveForward}
          onClick={() => onPageChange(currentPage + 1)}
          size="sm"
          variant="secondary"
        >
          下一页
        </Button>
        <Button
          className="table-pagination__button table-pagination__last"
          disabled={!canMoveForward}
          onClick={() => onPageChange(safeTotalPages)}
          size="sm"
          variant="secondary"
        >
          末页
        </Button>
      </form>

      {pageError ? (
        <p className="table-pagination__error" role="alert">
          {pageError}
        </p>
      ) : null}
    </nav>
  );
}
