/**
 * Shanghai business-period helpers shared by the settlement and finance pages.
 *
 * A statement period is a Shanghai natural month, so the visitor's own clock
 * and timezone must never decide which period a page opens on. The rule matches
 * the server's `previous_business_month`: during 2026-10 the current period is
 * 2026-09, and it stays selectable even before its first close.
 */

export const SHANGHAI_TIME_ZONE = "Asia/Shanghai";

const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;

export function isStatementMonth(value: string | null | undefined): value is string {
  return typeof value === "string" && MONTH_PATTERN.test(value);
}

function shanghaiYearMonth(now: Date): { year: number; month: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: SHANGHAI_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
  }).formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((item) => item.type === type)?.value ?? "";
  return { year: Number(part("year")), month: Number(part("month")) };
}

/** The last fully completed Shanghai calendar month, as `YYYY-MM`. */
export function previousShanghaiStatementMonth(now = new Date()): string {
  const { year, month } = shanghaiYearMonth(now);
  // Date.UTC normalizes month 0 / -1 into the previous year.
  const previous = new Date(Date.UTC(year, month - 2, 1));
  return `${previous.getUTCFullYear()}-${String(previous.getUTCMonth() + 1).padStart(2, "0")}`;
}

/**
 * Mirror the selected period into the address bar.
 *
 * `replaceState` (not `pushState` + `popstate`) keeps the period shareable and
 * refresh-safe without remounting the page, so the other filters the operator
 * already typed are not discarded by their own month change.
 */
export function replaceStatementMonthInUrl(month: string): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  if (isStatementMonth(month)) {
    params.set("month", month);
  } else {
    params.delete("month");
  }
  const search = params.toString();
  const href = `${window.location.pathname}${search ? `?${search}` : ""}`;
  const current = `${window.location.pathname}${window.location.search}`;
  if (href !== current) {
    window.history.replaceState(null, "", href);
  }
}

/** The page's initial period: the URL when it names one, else the last closed month. */
export function initialStatementMonth(
  searchParams: URLSearchParams,
  now = new Date(),
): string {
  const requested = [searchParams.get("month"), searchParams.get("periodKey")].find(isStatementMonth);
  return isStatementMonth(requested) ? requested : previousShanghaiStatementMonth(now);
}
