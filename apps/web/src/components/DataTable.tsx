import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  title: ReactNode;
  align?: "left" | "right" | "center";
  render: (row: T, index: number) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  emptyText?: string;
  rowHref?: (row: T) => string;
}

function openInternalHref(href: string) {
  window.history.pushState(null, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

export function DataTable<T>({
  columns,
  rows,
  emptyText = "暂无数据",
  rowHref,
}: DataTableProps<T>) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th className={`is-${column.align ?? "left"}`} key={column.key}>
                {column.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="empty-cell" colSpan={columns.length}>
                {emptyText}
              </td>
            </tr>
          ) : (
            rows.map((row, rowIndex) => {
              const href = rowHref?.(row);
              return (
                <tr
                  className={href ? "clickable-row" : undefined}
                  key={rowIndex}
                  onClick={href ? () => openInternalHref(href) : undefined}
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
                  {columns.map((column) => (
                    <td
                      className={`is-${column.align ?? "left"}`}
                      key={column.key}
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
  );
}
