import type { CSSProperties, MouseEvent, ReactNode } from "react";

export interface Column<T> {
  key: string;
  title: ReactNode;
  align?: "left" | "right" | "center";
  sticky?: boolean;
  width?: number;
  minWidth?: number;
  render: (row: T, index: number) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  emptyText?: string;
  errorText?: string;
  loadingText?: string;
  mobileCard?: ((row: T, index: number) => ReactNode) | false;
  onRowDoubleClick?: (row: T, event: MouseEvent<HTMLTableRowElement>) => void;
  rowHref?: (row: T) => string;
  state?: "ready" | "loading" | "error";
  stickyHeader?: "container";
  tableClassName?: string;
}

function openInternalHref(href: string) {
  window.history.pushState(null, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

type PreparedColumn<T> = Column<T> & {
  stickyLeft?: number;
  stickyLast?: boolean;
};

function prepareColumns<T>(columns: Column<T>[]): PreparedColumn<T>[] {
  let stickyLeft = 0;
  const lastStickyIndex = columns.reduce(
    (lastIndex, column, index) => (column.sticky ? index : lastIndex),
    -1,
  );

  return columns.map((column, index) => {
    if (!column.sticky) {
      return column;
    }

    const preparedColumn = {
      ...column,
      stickyLeft,
      stickyLast: index === lastStickyIndex,
    };
    stickyLeft += column.width ?? column.minWidth ?? 140;
    return preparedColumn;
  });
}

function columnStyle<T>(column: PreparedColumn<T>): CSSProperties {
  const style: CSSProperties & { "--sticky-left"?: string } = {};
  if (column.width) {
    style.width = `${column.width}px`;
    style.minWidth = `${column.width}px`;
  } else if (column.minWidth) {
    style.minWidth = `${column.minWidth}px`;
  }
  if (column.sticky && column.stickyLeft !== undefined) {
    style["--sticky-left"] = `${column.stickyLeft}px`;
  }
  return style;
}

function columnClass<T>(column: PreparedColumn<T>): string {
  return [
    `is-${column.align ?? "left"}`,
    column.sticky ? "is-sticky-column" : "",
    column.stickyLast ? "is-sticky-column-last" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

export function DataTable<T>({
  columns,
  rows,
  emptyText = "暂无数据",
  errorText = "数据暂不可用",
  loadingText = "正在加载数据...",
  mobileCard,
  onRowDoubleClick,
  rowHref,
  state = "ready",
  stickyHeader,
  tableClassName,
}: DataTableProps<T>) {
  const preparedColumns = prepareColumns(columns);
  const statusText =
    state === "loading" ? loadingText : state === "error" ? errorText : emptyText;
  const shouldRenderStatus = rows.length === 0 || state !== "ready";
  const hasMobileCards = mobileCard !== false;

  const renderMobileCard = (row: T, rowIndex: number) => {
    if (typeof mobileCard === "function") {
      return mobileCard(row, rowIndex);
    }

    const href = rowHref?.(row);
    return (
      <>
        <dl className="data-table-mobile-card__fields">
          {preparedColumns.map((column) => (
            <div key={column.key}>
              <dt>{column.title}</dt>
              <dd>{column.render(row, rowIndex)}</dd>
            </div>
          ))}
        </dl>
        {href ? (
          <button
            className="primary-button data-table-mobile-card__action"
            onClick={() => openInternalHref(href)}
            type="button"
          >
            查看详情
          </button>
        ) : null}
      </>
    );
  };

  return (
    <>
      <div
        className={[
          "table-wrap",
          hasMobileCards ? "table-wrap--mobile-cards" : "",
          stickyHeader === "container" ? "table-wrap--contained-sticky" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <table
          className={["data-table", tableClassName].filter(Boolean).join(" ")}
        >
          <thead>
            <tr>
              {preparedColumns.map((column) => (
                <th
                  className={columnClass(column)}
                  key={column.key}
                  style={columnStyle(column)}
                >
                  {column.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shouldRenderStatus ? (
              <tr>
                <td
                  aria-live={state === "error" ? "assertive" : "polite"}
                  className="empty-cell"
                  colSpan={columns.length}
                  role={state === "error" ? "alert" : "status"}
                >
                  {statusText}
                </td>
              </tr>
            ) : (
              rows.map((row, rowIndex) => {
                const href = rowHref?.(row);
                return (
                  <tr
                    className={
                      href || onRowDoubleClick ? "clickable-row" : undefined
                    }
                    key={rowIndex}
                    onClick={href ? () => openInternalHref(href) : undefined}
                    onDoubleClick={
                      onRowDoubleClick
                        ? (event) => onRowDoubleClick(row, event)
                        : undefined
                    }
                    onKeyDown={
                      href
                        ? (event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              openInternalHref(href);
                            }
                          }
                        : undefined
                    }
                    role={href ? "link" : undefined}
                    tabIndex={href ? 0 : undefined}
                  >
                    {preparedColumns.map((column) => (
                      <td
                        className={columnClass(column)}
                        key={column.key}
                        style={columnStyle(column)}
                      >
                        {column.render(row, rowIndex)}
                      </td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      {hasMobileCards ? (
        <div className="data-table-mobile-list">
          {shouldRenderStatus ? (
            <div
              aria-live={state === "error" ? "assertive" : "polite"}
              className="resource-panel"
              role={state === "error" ? "alert" : "status"}
            >
              {statusText}
            </div>
          ) : (
            rows.map((row, rowIndex) => (
              <div className="data-table-mobile-card" key={rowIndex}>
                {renderMobileCard(row, rowIndex)}
              </div>
            ))
          )}
        </div>
      ) : null}
    </>
  );
}
