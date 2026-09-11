export const RANKING_EARLIEST_DATE = "2026-09-01";
export const RANKING_DEFAULT_START_DATE = "2026-09-07";

export interface RankingDateRange {
  periodStart: string;
  periodEnd: string;
  today: string;
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function isCalendarDate(value: string | null): value is string {
  if (!value || !DATE_PATTERN.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day;
}

function clampDate(value: string, minimum: string, maximum: string) {
  if (value < minimum) return minimum;
  if (value > maximum) return maximum;
  return value;
}

export function getBeijingDate(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function normalizeRankingDateRange(
  searchParams: URLSearchParams,
  now = new Date(),
): RankingDateRange {
  const today = getBeijingDate(now);
  const defaultStart = clampDate(RANKING_DEFAULT_START_DATE, RANKING_EARLIEST_DATE, today);
  const requestedStart = searchParams.get("periodStart");
  const periodStart = isCalendarDate(requestedStart)
    ? clampDate(requestedStart, RANKING_EARLIEST_DATE, today)
    : defaultStart;
  const requestedEnd = searchParams.get("periodEnd");
  const periodEnd = isCalendarDate(requestedEnd) && requestedEnd >= periodStart
    ? clampDate(requestedEnd, periodStart, today)
    : today;

  return { periodStart, periodEnd, today };
}

export function updateRankingPeriodStart(
  requestedStart: string,
  currentEnd: string,
  today: string,
) {
  const periodStart = isCalendarDate(requestedStart)
    ? clampDate(requestedStart, RANKING_EARLIEST_DATE, today)
    : RANKING_EARLIEST_DATE;
  return {
    periodStart,
    periodEnd: currentEnd < periodStart ? periodStart : currentEnd,
  };
}

export function updateRankingPeriodEnd(
  requestedEnd: string,
  currentStart: string,
  today: string,
) {
  return isCalendarDate(requestedEnd)
    ? clampDate(requestedEnd, currentStart, today)
    : currentStart;
}
