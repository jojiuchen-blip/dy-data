import assert from "node:assert/strict";
import test from "node:test";
import {
  RANKING_EARLIEST_DATE,
  getBeijingDate,
  normalizeRankingDateRange,
  updateRankingPeriodEnd,
  updateRankingPeriodStart,
} from "../src/utils/douyinRankingDates.ts";

test("uses the Beijing calendar date across the UTC midnight boundary", () => {
  assert.equal(getBeijingDate(new Date("2026-09-10T15:59:59Z")), "2026-09-10");
  assert.equal(getBeijingDate(new Date("2026-09-10T16:00:00Z")), "2026-09-11");
});

test("defaults to September 7 through Beijing today", () => {
  assert.deepEqual(
    normalizeRankingDateRange(new URLSearchParams(), new Date("2026-09-10T16:30:00Z")),
    { periodStart: "2026-09-07", periodEnd: "2026-09-11", today: "2026-09-11" },
  );
});

test("keeps a valid date range from the URL", () => {
  const params = new URLSearchParams({
    periodStart: "2026-09-03",
    periodEnd: "2026-09-09",
  });

  assert.deepEqual(normalizeRankingDateRange(params, new Date("2026-09-10T16:30:00Z")), {
    periodStart: "2026-09-03",
    periodEnd: "2026-09-09",
    today: "2026-09-11",
  });
});

test("replaces invalid URL dates and ranges with safe defaults", () => {
  const malformed = new URLSearchParams({ periodStart: "2026-02-30", periodEnd: "tomorrow" });
  assert.deepEqual(normalizeRankingDateRange(malformed, new Date("2026-09-10T16:30:00Z")), {
    periodStart: "2026-09-07",
    periodEnd: "2026-09-11",
    today: "2026-09-11",
  });

  const reversed = new URLSearchParams({ periodStart: "2026-09-10", periodEnd: "2026-09-08" });
  assert.deepEqual(normalizeRankingDateRange(reversed, new Date("2026-09-10T16:30:00Z")), {
    periodStart: "2026-09-10",
    periodEnd: "2026-09-11",
    today: "2026-09-11",
  });

  const tooEarly = new URLSearchParams({ periodStart: "2026-08-31", periodEnd: "2026-09-02" });
  assert.equal(normalizeRankingDateRange(tooEarly, new Date("2026-09-10T16:30:00Z")).periodStart, RANKING_EARLIEST_DATE);
});

test("keeps interactive changes within the available date range", () => {
  assert.deepEqual(updateRankingPeriodStart("2026-09-10", "2026-09-08", "2026-09-11"), {
    periodStart: "2026-09-10",
    periodEnd: "2026-09-10",
  });
  assert.equal(updateRankingPeriodEnd("2026-09-08", "2026-09-10", "2026-09-11"), "2026-09-10");
  assert.equal(updateRankingPeriodEnd("2026-09-12", "2026-09-10", "2026-09-11"), "2026-09-11");
});
