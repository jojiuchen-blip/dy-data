import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const baseUrl = process.env.PUBLICATION_TEST_BASE_URL ?? "http://127.0.0.1:5195";
const user = { user_id: "pub-test", username: "pub-test", display_name: "Publication QA", role: "highest_admin", is_highest_admin: true, is_initialized: true, store_scope_mode: "all", store_ids: [], page_keys: ["A01", "A02", "A03", "B01", "B02", "B03", "C01", "FIN01", "FIN02", "FIN03", "FIN04", "FIN05", "FIN06"] };
const publication = (module, id) => ({ id, module, dataAsOf: null, publishedAt: "2026-10-19T02:00:00Z", status: "available", nextRefreshAt: "2026-10-19T02:05:00Z" });
const payload = (data, module, id) => ({ data, meta: { generatedAt: "2099-01-01T00:00:00Z", source: "postgres", ...(module ? { publication: publication(module, id) } : {}) } });
const metrics = { storeCount: 1, orderCount: 10, orderAverage: 10, followNumerator: 1, followDenominator: 2, follow24hRate: .5, followRate: .5, followAnyNumerator: 1, followAnyDenominator: 2, followActionRate: .5, followActionNumerator: 1, followActionDenominator: 2, verificationNumerator: 1, verificationDenominator: 2, verificationRate: .5 };
const ranking = { productScope: "jingcheng", dataMode: "business", snapshotId: "source", qualityJson: {}, periodStart: "2026-09-07", periodEnd: "2026-10-19", level: "group", total: 1, page: 1, pageSize: 50, totals: metrics, rows: [{ ...metrics, key: "group", name: "测试集团", rank: 1 }], latestObservedAt: null, metricDefinitions: {} };
const filterMeta = { stores: [{ storeId: "s1", storeName: "门店一" }], productScopes: ["all"], productScopeTypeMap: {}, productTypes: ["all"], defaultProductType: "all", saleMonths: ["2026-10", "2025-09"], verifyMonths: ["2026-10", "2025-09"], statementMonths: ["2026-09"], periodTypes: ["MONTHLY", "CUMULATIVE"], feeDirections: ["PROMOTION", "MANAGEMENT"], formalPeriodStartMonth: "2026-08", timezone: "Asia/Shanghai" };
const sales = { store: { store_id: "", store_name: "全部门店" }, month: "all", product_type: "all", metrics: { total_sales_order_count: 23, self_verify_order_count: 5, self_verify_rate: .2, total_verify_order_count: 6, actual_verify_amount_cent: 1000, avg_verify_cycle_days: 3 }, product_rows: [], trend_rows: [], cycle_rows: [], source_row_count: 23 };

async function withPage(run) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const requests = [];
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let handler = async () => false;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    if (url.pathname.endsWith("/auth/me")) return route.fulfill({ json: payload(user) });
    if (url.pathname.endsWith("/commission-rules/summary")) return route.fulfill({ json: payload({ non_commission_owner_accounts: [], commission_skus: [] }) });
    if (await handler(route, url)) return;
    return route.fulfill({ json: payload({}) });
  });
  try { await run({ page, requests, handle: (next) => { handler = next; } }); assert.deepEqual(errors, []); }
  catch (error) {
    console.error("Browser failure", await page.locator("body").innerText(), errors, requests.map((url) => url.pathname + url.search));
    throw error;
  }
  finally { await browser.close(); }
}

test("ranking pins filters and export, latest refresh and visible five-minute poll only read", async () => withPage(async ({ page, requests, handle }) => {
  let latest = "r1";
  handle(async (route, url) => {
    if (url.pathname.endsWith("/douyin-ranking/export")) {
      await route.fulfill({ contentType: "application/octet-stream", headers: { "Content-Disposition": "attachment; filename=ranking.xlsx" }, body: "test" });
      return true;
    }
    if (!url.pathname.endsWith("/douyin-ranking")) return false;
    await route.fulfill({ json: payload(ranking, "douyin-ranking", url.searchParams.get("publication_id") ?? latest) });
    return true;
  });
  await page.clock.install();
  await page.goto(`${baseUrl}/metrics/douyin-ranking`);
  await page.getByText("来源时间未知", { exact: false }).waitFor();
  assert.doesNotMatch(await page.locator(".page-publication-time").innerText(), /2099/);
  await page.setViewportSize({ width: 390, height: 844 });
  const timeBox = await page.locator(".page-publication-time").boundingBox();
  assert.ok(timeBox.x >= 0 && timeBox.x + timeBox.width <= 390, "publication times fit the mobile page");
  await page.setViewportSize({ width: 1440, height: 1000 });
  const filtered = page.waitForResponse((response) => response.url().includes("groupName=") && response.url().includes("publication_id=r1"));
  await page.getByLabel("集团", { exact: true }).fill("测试集团");
  await filtered;
  await page.getByRole("button", { name: "导出排行", exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 Excel", exact: true }).click();
  await download;
  assert.equal(requests.find((url) => url.pathname.endsWith("/export")).searchParams.get("publication_id"), "r1");
  latest = "r2";
  const refresh = page.waitForResponse((response) => response.url().includes("/douyin-ranking?") && !response.url().includes("publication_id="));
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await refresh;
  const nextFilter = page.waitForResponse((response) => response.url().includes("publication_id=r2"));
  await page.getByLabel("集团", { exact: true }).fill("新集团");
  await nextFilter;
  const before = requests.filter((url) => url.pathname.endsWith("/douyin-ranking")).length;
  const polled = page.waitForResponse((response) => response.url().includes("/douyin-ranking?") && !response.url().includes("publication_id="));
  await page.clock.fastForward(300_001);
  await polled;
  assert.equal(requests.filter((url) => url.pathname.endsWith("/douyin-ranking")).length, before + 1);
}));

test("sales metadata prevents duplicate first data request and separates selected year from history", async () => withPage(async ({ page, requests, handle }) => {
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/sales/filters")) {
      const response = payload(filterMeta, "sales", "s1");
      response.meta.publication.status = "refreshing";
      await route.fulfill({ json: response }); return true;
    }
    if (!url.pathname.endsWith("/dashboard/sales")) return false;
    await route.fulfill({ json: payload(sales, "sales", url.searchParams.get("publication_id")) }); return true;
  });
  await page.goto(`${baseUrl}/sales?year=2026`);
  await page.locator(".metric-grid--sales").waitFor();
  const dataRequests = () => requests.filter((url) => url.pathname.endsWith("/dashboard/sales"));
  assert.equal(dataRequests().length, 1);
  await page.getByText("后台更新中，展示上一完整结果", { exact: true }).waitFor();
  assert.equal(dataRequests()[0].searchParams.get("publication_id"), "s1");
  assert.equal(dataRequests()[0].searchParams.get("year"), "2026");
  assert.deepEqual(dataRequests()[0].searchParams.getAll("trend_months"), ["2026-10"]);
  await page.getByLabel("月份", { exact: true }).click();
  const history = page.waitForResponse((response) => response.url().includes("month=history"));
  await page.getByRole("option", { name: "全部历史", exact: true }).click();
  await history;
  assert.equal(dataRequests().at(-1).searchParams.has("year"), false);
  assert.equal(dataRequests().at(-1).searchParams.get("publication_id"), "s1");
}));

test("expired fixed version recovers once, 422 never retries, and 503 refresh keeps same-scope result", async () => withPage(async ({ page, requests, handle }) => {
  let mode = "ok";
  handle(async (route, url) => {
    if (!url.pathname.endsWith("/douyin-ranking")) return false;
    const id = url.searchParams.get("publication_id");
    const code = mode === "expired" && id === "r1" ? 410 : mode === "invalid" ? 422 : mode === "unavailable" ? 503 : 200;
    await route.fulfill(code === 200 ? { json: payload(ranking, "douyin-ranking", id ?? (mode === "expired" ? "r2" : "r1")) } : { status: code, json: { detail: { message: "test error" } } });
    return true;
  });
  await page.goto(`${baseUrl}/metrics/douyin-ranking`);
  await page.locator(".publication-time").waitFor();
  mode = "expired";
  await page.getByLabel("集团", { exact: true }).fill("expired");
  await page.getByText("原结果版本已过期，已重新读取最新发布结果。", { exact: true }).waitFor();
  await page.locator("tbody tr").first().waitFor();
  const expiredRequests = requests.filter((url) => url.pathname.endsWith("/douyin-ranking"));
  assert.equal(expiredRequests.filter((url) => url.searchParams.get("publication_id") === "r1").length, 1);
  assert.equal(expiredRequests.filter((url) => !url.searchParams.has("publication_id")).length, 2);
  mode = "unavailable";
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await page.getByText("发布结果暂不可用", { exact: false }).waitFor();
  assert.equal(await page.locator("tbody tr").count(), 1);
  mode = "invalid";
  const before = requests.length;
  const invalid = page.waitForResponse((response) => response.status() === 422);
  await page.getByLabel("集团", { exact: true }).fill("invalid");
  await invalid;
  await page.getByRole("button", { name: "导出排行", exact: true }).isDisabled().then((value) => assert.equal(value, true));
  assert.equal(requests.length, before + 1);
}));

test("finance first summary pins list and export to same version", async () => withPage(async ({ page, requests, handle }) => {
  handle(async (route, url) => {
    if (url.pathname.endsWith("/finance/summary")) {
      await route.fulfill({ json: payload({ month: "2026-09", feeDirection: "PROMOTION", metricScope: "MONTH", metrics: {} }, "finance", url.searchParams.get("publication_id") ?? "f1") }); return true;
    }
    if (url.pathname.endsWith("/finance/invoices/export")) {
      await route.fulfill({ contentType: "text/csv", headers: { "Content-Disposition": "attachment; filename=finance.csv" }, body: "store\n" }); return true;
    }
    if (url.pathname.endsWith("/finance/invoices")) {
      await route.fulfill({ json: payload({ list: [], total: 0, page: 1, pageSize: 50 }, "finance", url.searchParams.get("publication_id")) }); return true;
    }
    return false;
  });
  await page.goto(`${baseUrl}/finance/promotion?month=2026-09`);
  await page.locator(".publication-time").waitFor();
  assert.equal(requests.filter((url) => url.pathname.endsWith("/finance/summary")).length, 1);
  const list = requests.find((url) => url.pathname.endsWith("/finance/invoices"));
  assert.equal(list.searchParams.get("publication_id"), "f1");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出当前筛选结果", exact: true }).click();
  await download;
  assert.equal(requests.find((url) => url.pathname.endsWith("/finance/invoices/export")).searchParams.get("publication_id"), "f1");
}));

test("settlement analysis pins metadata while billing and fee-detail operations stay live", async () => withPage(async ({ page, requests, handle }) => {
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/settlement/filters")) {
      await route.fulfill({ json: payload(filterMeta, "settlement", "st1") }); return true;
    }
    if (url.pathname.endsWith("/dashboard/store-ranking")) {
      await route.fulfill({ json: payload({ list: [], totals: {}, total: 0, page: 1, pageSize: 20 }, "settlement", url.searchParams.get("publication_id")) }); return true;
    }
    if (url.pathname.endsWith("/monthly-settlement")) {
      await route.fulfill({ json: payload({ store: { storeId: "s1", storeName: "门店一" }, month: "2026-09", isFormalPeriod: true, metrics: {}, computedCumulative: {}, lines: [] }, "settlement", url.searchParams.get("publication_id")) }); return true;
    }
    if (url.pathname.endsWith("/store-settlements") || url.pathname.endsWith("/order-fee-details")) {
      await route.fulfill({ json: payload({ list: [], total: 0, page: 1, pageSize: 50 }) }); return true;
    }
    return false;
  });
  await page.goto(`${baseUrl}/ranking`);
  await page.locator(".publication-time").waitFor();
  assert.equal(requests.find((url) => url.pathname.endsWith("/dashboard/store-ranking")).searchParams.get("publication_id"), "st1");
  const filterRead = page.waitForResponse((response) => response.url().includes("q="));
  await page.getByLabel("搜索门店", { exact: true }).fill("门店一");
  await filterRead;
  assert.equal(requests.filter((url) => url.pathname.endsWith("/dashboard/store-ranking")).at(-1).searchParams.get("publication_id"), "st1");
  await page.goto(`${baseUrl}/settlement?storeId=s1&month=2026-09`);
  await page.locator(".publication-time").waitFor();
  assert.equal(requests.find((url) => url.pathname.endsWith("/monthly-settlement")).searchParams.get("publication_id"), "st1");
  for (const url of requests.filter((url) => url.pathname.endsWith("/store-settlements") || url.pathname.endsWith("/order-fee-details"))) {
    assert.equal(url.searchParams.has("publication_id"), false);
  }
}));

test("clue overview pins its filters but detail workflow has no analysis publication", async () => withPage(async ({ page, requests, handle }) => {
  const clueFilters = { assigned_stores: [], assigned_provinces: [], assigned_cities: [], product_types: ["all"], default_product_type: "all", lead_statuses: [], round_statuses: [], verification_statuses: [] };
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/clue-overview/filters")) {
      await route.fulfill({ json: payload(clueFilters, "clue-overview", "c1") }); return true;
    }
    if (url.pathname.endsWith("/clues/overview")) {
      await route.fulfill({ json: payload({ total_clues: 8, active_clues: 4, follow_rate: .5, follow_success_rate: .5, verified_count: 1, self_store_verify_rate: .25, pending_reassign_count: 1 }, "clue-overview", url.searchParams.get("publication_id")) }); return true;
    }
    if (url.pathname.endsWith("/clues/filters")) {
      await route.fulfill({ json: payload(clueFilters) }); return true;
    }
    if (url.pathname.endsWith("/clues/assignment-rounds")) {
      await route.fulfill({ json: payload({ rows: [], pagination: { page: 1, page_size: 50, total: 0, total_pages: 0 } }) }); return true;
    }
    return false;
  });
  await page.goto(`${baseUrl}/clues`);
  await page.locator(".publication-time").waitFor();
  assert.equal(requests.find((url) => url.pathname.endsWith("/clues/overview")).searchParams.get("publication_id"), "c1");
  assert.equal(requests.some((url) => url.pathname.endsWith("/clues/assignment-rounds")), false);
  await page.goto(`${baseUrl}/clues/details`);
  await page.getByRole("heading", { name: "线索跟进列表", exact: true }).waitFor();
  assert.equal(await page.locator(".page-publication-time").count(), 0);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/clues/assignment-rounds")).at(-1).searchParams.has("publication_id"), false);
}));

test("changing filters hides old-scope rows and blocks export until the matching result arrives", async () => withPage(async ({ page, handle }) => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  handle(async (route, url) => {
    if (!url.pathname.endsWith("/douyin-ranking")) return false;
    if (url.searchParams.get("groupName") === "等待") await pending;
    await route.fulfill({ json: payload(ranking, "douyin-ranking", "r1") }); return true;
  });
  await page.goto(`${baseUrl}/metrics/douyin-ranking`);
  await page.locator(".publication-time").waitFor();
  await page.getByLabel("集团", { exact: true }).fill("等待");
  await page.locator(".metric-card").first().waitFor({ state: "hidden" });
  assert.equal(await page.getByRole("button", { name: "导出排行", exact: true }).isDisabled(), true);
  release();
  await page.locator(".metric-card").first().waitFor();
}));

test("a permission denial removes previously displayed analytical rows immediately", async () => withPage(async ({ page, requests, handle }) => {
  let denied = false;
  handle(async (route, url) => {
    if (!url.pathname.endsWith("/douyin-ranking")) return false;
    await route.fulfill(denied
      ? { status: 403, json: { detail: { message: "denied" } } }
      : { json: payload(ranking, "douyin-ranking", "r1") });
    return true;
  });
  await page.goto(`${baseUrl}/metrics/douyin-ranking`);
  await page.locator(".publication-time").waitFor();
  denied = true;
  const before = requests.filter((url) => url.pathname.endsWith("/douyin-ranking")).length;
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await page.getByText("当前账号没有查看此分析结果的权限。", { exact: true }).waitFor();
  assert.equal(await page.locator("tbody tr").count(), 0);
  assert.equal(await page.getByRole("button", { name: "导出排行", exact: true }).isDisabled(), true);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/douyin-ranking")).length, before + 1);
}));
