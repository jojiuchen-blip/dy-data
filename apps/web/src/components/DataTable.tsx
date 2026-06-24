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
  onRowDoubleClick?: (row: T, event: MouseEvent<HTMLTableRowElement>) => void;
  rowHref?: (row: T) => string;
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
  onRowDoubleClick,
  rowHref,
  tableClassName,
}: DataTableProps<T>) {
  const preparedColumns = prepareColumns(columns);

  return (
    <div className="table-wrap">
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
  );
}
