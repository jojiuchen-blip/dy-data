import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_NODE_PACKAGE || "playwright");
const baseUrl = process.env.PUBLICATION_TEST_BASE_URL ?? "http://127.0.0.1:5195";
const user = { user_id: "pub-test", username: "pub-test", display_name: "Publication QA", role: "highest_admin", is_highest_admin: true, can_manage_global_settings: true, is_initialized: true, store_scope_mode: "all", store_ids: [], page_keys: ["A01", "A02", "A03", "B01", "B02", "B03", "C01", "FIN01", "FIN02", "FIN03", "FIN04", "FIN05", "FIN06", "D04"] };
const publication = (module, id) => ({ id, module, dataAsOf: null, publishedAt: "2026-10-19T02:00:00Z", status: "available", nextRefreshAt: "2026-10-19T02:05:00Z" });
const payload = (data, module, id) => ({ data, meta: { generatedAt: "2099-01-01T00:00:00Z", source: "postgres", ...(module ? { publication: publication(module, id) } : {}) } });
const metrics = { storeCount: 1, orderCount: 10, orderAverage: 10, followNumerator: 1, followDenominator: 2, follow24hRate: .5, followRate: .5, followAnyNumerator: 1, followAnyDenominator: 2, followActionRate: .5, followActionNumerator: 1, followActionDenominator: 2, verificationNumerator: 1, verificationDenominator: 2, verificationRate: .5 };
const ranking = { productScope: "jingcheng", dataMode: "business", snapshotId: "source", qualityJson: {}, periodStart: "2026-09-07", periodEnd: "2026-10-19", level: "group", total: 1, page: 1, pageSize: 50, totals: metrics, rows: [{ ...metrics, key: "group", name: "测试集团", rank: 1 }], latestObservedAt: null, metricDefinitions: {} };
const filterMeta = { stores: [{ storeId: "s1", storeName: "门店一" }], productScopes: ["all"], productScopeTypeMap: {}, productTypes: ["all"], defaultProductType: "all", saleMonths: ["2026-10", "2025-09"], verifyMonths: ["2026-10", "2025-09"], statementMonths: ["2026-09"], periodTypes: ["MONTHLY", "CUMULATIVE"], feeDirections: ["PROMOTION", "MANAGEMENT"], formalPeriodStartMonth: "2026-08", timezone: "Asia/Shanghai" };
const sales = { store: { store_id: "", store_name: "全部门店" }, month: "all", product_type: "all", metrics: { total_sales_order_count: 23, self_verify_order_count: 5, self_verify_rate: .2, total_verify_order_count: 6, actual_verify_amount_cent: 1000, avg_verify_cycle_days: 3 }, product_rows: [], trend_rows: [], cycle_rows: [], source_row_count: 23 };

async function withPage(run) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(8_000);
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
  assert.equal(requests.filter((url) => url.pathname.endsWith("/publications/sales/filters")).length, 2, "ordinary filters revalidate same-version metadata permissions");
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
  await page.getByText("发布结果读取失败", { exact: false }).waitFor();
  assert.equal(await page.locator("tbody tr").count(), 1);
  mode = "invalid";
  const before = requests.length;
  const invalid = page.waitForResponse((response) => response.status() === 422);
  await page.getByLabel("集团", { exact: true }).fill("invalid");
  await invalid;
  await page.getByRole("button", { name: "导出排行", exact: true }).isDisabled().then((value) => assert.equal(value, true));
  assert.equal(requests.length, before + 1);
  assert.equal(requests.at(-1).searchParams.get("publication_id"), "r2", "failed latest refresh must keep the previous version pinned");
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

test("sales commits refreshed filters, data and time only after the complete candidate succeeds", async () => withPage(async ({ page, requests, handle }) => {
  let latest = "s1";
  let fail = true;
  let release;
  let pending = new Promise((resolve) => { release = resolve; });
  const versioned = (data, id) => {
    const response = payload(data, "sales", id);
    if (id === "s2") response.meta.publication.publishedAt = "2026-10-19T03:00:00Z";
    return response;
  };
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/sales/filters")) {
      await route.fulfill({ json: versioned(filterMeta, url.searchParams.get("publication_id") ?? latest) }); return true;
    }
    if (!url.pathname.endsWith("/dashboard/sales")) return false;
    const id = url.searchParams.get("publication_id");
    if (id === "s2") await pending;
    await route.fulfill(id === "s2" && fail
      ? { status: 503, json: { detail: { message: "candidate unavailable" } } }
      : { json: versioned({ ...sales, metrics: { ...sales.metrics, total_sales_order_count: id === "s1" ? 23 : 99 } }, id) });
    return true;
  });
  await page.goto(`${baseUrl}/sales?year=2026`);
  const total = page.locator(".metric-card").filter({ has: page.getByText("总销售订单量", { exact: true }) });
  await total.getByText("23", { exact: true }).waitFor();
  latest = "s2";
  const candidate = page.waitForRequest((request) => request.url().includes("/dashboard/sales?") && request.url().includes("publication_id=s2"));
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await candidate;
  assert.equal(await total.count(), 1, "the previous complete sales view must remain during candidate loading");
  assert.match(await total.innerText(), /23/);
  assert.match(await page.locator(".publication-time").innerText(), /10:00/);
  release();
  await page.getByText("发布结果读取失败", { exact: false }).waitFor();
  assert.match(await total.innerText(), /23/);
  assert.match(await page.locator(".publication-time").innerText(), /10:00/);
  fail = false;
  pending = new Promise((resolve) => { release = resolve; });
  const retry = page.waitForRequest((request) => request.url().includes("/dashboard/sales?") && request.url().includes("publication_id=s2"));
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await retry;
  assert.match(await total.innerText(), /23/);
  release();
  await total.getByText("99", { exact: true }).waitFor();
  assert.match(await page.locator(".publication-time").innerText(), /11:00/);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/dashboard/sales") && url.searchParams.get("publication_id") === "s1").length, 1);
}));

test("finance keeps complete old cards, rows, time and export while a new list is delayed or fails", async () => withPage(async ({ page, requests, handle }) => {
  let latest = "f1";
  let fail = true;
  let release;
  let pending = new Promise((resolve) => { release = resolve; });
  const versioned = (data, id) => {
    const response = payload(data, "finance", id);
    if (id === "f2") response.meta.publication.publishedAt = "2026-10-19T03:00:00Z";
    return response;
  };
  handle(async (route, url) => {
    const id = url.searchParams.get("publication_id") ?? latest;
    if (url.pathname.endsWith("/finance/summary")) {
      await route.fulfill({ json: versioned({ month: "2026-09", feeDirection: "PROMOTION", metricScope: "MONTH", metrics: { statementTotalCent: id === "f1" ? 10000 : 20000 } }, id) }); return true;
    }
    if (url.pathname.endsWith("/finance/invoices/export")) {
      await route.fulfill({ contentType: "text/csv", headers: { "Content-Disposition": "attachment; filename=finance.csv" }, body: "store\n" }); return true;
    }
    if (!url.pathname.endsWith("/finance/invoices")) return false;
    if (id === "f2") await pending;
    await route.fulfill(id === "f2" && fail
      ? { status: 503, json: { detail: { message: "candidate unavailable" } } }
      : { json: versioned({ list: [{ storeId: "s1", storeName: id === "f1" ? "旧版本门店" : "新版本门店", statementMonth: "2026-09", statementAmountCent: id === "f1" ? 10000 : 20000, confirmedAmountCent: 0, feeDirection: "PROMOTION", status: "PENDING_STATEMENT", processingStatus: "PENDING_STATEMENT", invoiceId: null, invoiceNumber: null, versionNo: null, isCurrent: null }], total: 1, page: 1, pageSize: 50 }, id) });
    return true;
  });
  await page.goto(`${baseUrl}/finance/promotion?month=2026-09`);
  const total = page.locator(".metric-card").filter({ hasText: "推广费总额" });
  await page.locator("tbody").getByText("旧版本门店", { exact: true }).waitFor();
  latest = "f2";
  const candidate = page.waitForRequest((request) => request.url().includes("/finance/invoices?") && request.url().includes("publication_id=f2"));
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await candidate;
  assert.match(await total.innerText(), /100\.00/);
  assert.match(await page.locator("tbody").innerText(), /旧版本门店/);
  assert.match(await page.locator(".publication-time").innerText(), /10:00/);
  const exportOld = async () => {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出当前筛选结果", exact: true }).click();
    await download;
    assert.equal(requests.filter((url) => url.pathname.endsWith("/finance/invoices/export")).at(-1).searchParams.get("publication_id"), "f1");
  };
  await exportOld();
  release();
  await page.getByText("发布结果读取失败", { exact: false }).waitFor();
  assert.match(await total.innerText(), /100\.00/);
  assert.match(await page.locator("tbody").innerText(), /旧版本门店/);
  assert.match(await page.locator(".publication-time").innerText(), /10:00/);
  await exportOld();
  fail = false;
  pending = new Promise((resolve) => { release = resolve; });
  const retry = page.waitForRequest((request) => request.url().includes("/finance/invoices?") && request.url().includes("publication_id=f2"));
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await retry;
  assert.match(await total.innerText(), /100\.00/);
  release();
  await page.locator("tbody").getByText("新版本门店", { exact: true }).waitFor();
  assert.match(await total.innerText(), /200\.00/);
  assert.match(await page.locator(".publication-time").innerText(), /11:00/);
  const exportNew = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出当前筛选结果", exact: true }).click();
  await exportNew;
  assert.equal(requests.filter((url) => url.pathname.endsWith("/finance/invoices/export")).at(-1).searchParams.get("publication_id"), "f2");
}));

for (const module of ["sales", "finance"]) {
  for (const phase of ["initial", "refresh"]) {
    test(`${module} ${phase} nested fixed-ID 410 recovers the complete view once`, async () => withPage(async ({ page, requests, handle }) => {
      let expired = phase === "initial";
      let prepares = 0;
      handle(async (route, url) => {
        const prepare = module === "sales" ? url.pathname.endsWith("/publications/sales/filters") : url.pathname.endsWith("/finance/summary");
        const data = module === "sales" ? url.pathname.endsWith("/dashboard/sales") : url.pathname.endsWith("/finance/invoices");
        if (prepare) {
          prepares++;
          const id = expired ? (prepares === (phase === "initial" ? 1 : 2) ? "old" : "new") : "initial";
          await route.fulfill({ json: payload(module === "sales" ? filterMeta : { metrics: {} }, module, id) }); return true;
        }
        if (!data) return false;
        const id = url.searchParams.get("publication_id");
        await route.fulfill(id === "old"
          ? { status: 410, json: { detail: { message: "expired" } } }
          : { json: payload(module === "sales" ? sales : { list: [], total: 0 }, module, id) }); return true;
      });
      await page.goto(`${baseUrl}/${module === "sales" ? "sales?year=2026" : "finance/promotion?month=2026-09"}`);
      await page.locator(".publication-time").waitFor();
      if (phase === "refresh") {
        expired = true;
        await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
      }
      await page.getByText("原结果版本已过期，已重新读取最新发布结果。", { exact: true }).waitFor();
      assert.equal(prepares, phase === "initial" ? 2 : 3);
      assert.equal(requests.filter((url) => url.searchParams.get("publication_id") === "new").length, 1);
    }));
  }
  for (const status of [410, 422, 503]) {
    test(`${module} nested ${status} is bounded with no automatic retry loop`, async () => withPage(async ({ page, requests, handle }) => {
      handle(async (route, url) => {
        if (url.pathname.endsWith("/publications/sales/filters")) {
          await route.fulfill({ json: payload(filterMeta, "sales", "expired") }); return true;
        }
        if (url.pathname.endsWith("/finance/summary")) {
          await route.fulfill({ json: payload({ metrics: {} }, "finance", "expired") }); return true;
        }
        if (!url.pathname.endsWith("/dashboard/sales") && !url.pathname.endsWith("/finance/invoices")) return false;
        await route.fulfill({ status, json: { detail: { message: "test failure" } } }); return true;
      });
      await page.goto(`${baseUrl}/${module === "sales" ? "sales?year=2026" : "finance/promotion?month=2026-09"}`);
      await page.getByText(status === 410 ? "原结果版本已过期，请读取最新结果。" : status === 422 ? "筛选条件不正确，请调整后重试。" : "发布结果读取失败，请稍后重试。", { exact: true }).first().waitFor();
      await page.waitForTimeout(150);
      const data = requests.filter((url) => url.pathname.endsWith(module === "sales" ? "/dashboard/sales" : "/finance/invoices"));
      assert.equal(data.length, status === 410 ? 2 : 1);
    }));
  }
}

test("ordinary sales filtering revalidates same-version metadata after scope shrink and clears denied options", async () => withPage(async ({ page, requests, handle }) => {
  let narrowed = false;
  let denied = false;
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/sales/filters")) {
      await route.fulfill(denied ? { status: 403, json: { detail: { message: "denied" } } }
        : { json: payload({ ...filterMeta, stores: narrowed ? filterMeta.stores : [...filterMeta.stores, { storeId: "s2", storeName: "范围门店B" }] }, "sales", "s1") }); return true;
    }
    if (!url.pathname.endsWith("/dashboard/sales")) return false;
    await route.fulfill({ json: payload(sales, "sales", "s1") }); return true;
  });
  await page.goto(`${baseUrl}/sales?year=2026`);
  await page.locator(".publication-time").waitFor();
  await page.getByPlaceholder("输入门店名称").click();
  await page.getByRole("option", { name: "范围门店B", exact: true }).waitFor();
  await page.keyboard.press("Escape");
  narrowed = true;
  await page.getByLabel("月份", { exact: true }).click();
  const loaded = page.waitForResponse((response) => response.url().includes("month=history"));
  await page.getByRole("option", { name: "全部历史", exact: true }).click();
  await loaded;
  await page.getByPlaceholder("输入门店名称").click();
  assert.equal(await page.getByRole("option", { name: "范围门店B", exact: true }).count(), 0);
  await page.keyboard.press("Escape");
  assert.equal(requests.filter((url) => url.pathname.endsWith("/publications/sales/filters")).at(-1).searchParams.get("publication_id"), "s1");
  denied = true;
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await page.getByText("当前账号没有查看此分析结果的权限。", { exact: true }).first().waitFor();
  await page.getByPlaceholder("输入门店名称").click();
  assert.equal(await page.getByRole("option", { name: "门店一", exact: true }).count(), 0);
}));

const clueFilters = { assigned_stores: [], assigned_provinces: [], assigned_cities: [], product_types: ["all"], default_product_type: "all", lead_statuses: [], round_statuses: [], verification_statuses: [] };
const clueOverview = { total_clues: 8, active_clues: 4, follow_rate: .5, follow_success_rate: .5, verified_count: 1, self_store_verify_rate: .25, pending_reassign_count: 1 };

test("clue options follow committed overview, clear old-version options while pending and on 403", async () => withPage(async ({ page, requests, handle }) => {
  let latest = "c1";
  let denied = false;
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  handle(async (route, url) => {
    const id = url.searchParams.get("publication_id") ?? latest;
    if (url.pathname.endsWith("/publications/clue-overview/filters")) {
      await route.fulfill({ json: payload(clueFilters, "clue-overview", id) }); return true;
    }
    if (url.pathname.endsWith("/clues/overview")) {
      await route.fulfill({ json: payload(clueOverview, "clue-overview", id) }); return true;
    }
    if (!url.pathname.endsWith("/clues/filter-options/stores")) return false;
    if (id === "c2") await pending;
    await route.fulfill(denied ? { status: 403, json: { detail: { message: "denied" } } }
      : { json: payload({ stores: [{ store_id: id, store_name: id === "c1" ? "旧版本选项" : "新版本选项" }] }, "clue-overview", id) }); return true;
  });
  await page.goto(`${baseUrl}/clues`);
  await page.locator(".publication-time").waitFor();
  await page.getByPlaceholder("搜索门店名称").click();
  await page.getByRole("option", { name: "旧版本选项", exact: true }).waitFor();
  latest = "c2";
  const next = page.waitForRequest((request) => request.url().includes("/clues/filter-options/stores?") && request.url().includes("publication_id=c2"));
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await next;
  await page.getByPlaceholder("搜索门店名称").click();
  assert.equal(await page.getByRole("option", { name: "旧版本选项", exact: true }).count(), 0);
  const optionsReady = page.waitForResponse((response) => response.url().includes("/clues/filter-options/stores?") && response.url().includes("publication_id=c2"));
  release();
  await optionsReady;
  await page.getByPlaceholder("搜索门店名称").blur();
  await page.waitForTimeout(150);
  await page.getByPlaceholder("搜索门店名称").focus();
  await page.getByRole("option", { name: "新版本选项", exact: true }).waitFor();
  denied = true;
  const deniedRead = page.waitForResponse((response) => response.url().includes("/clues/filter-options/stores?") && response.status() === 403);
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await deniedRead;
  await page.getByText("当前账号没有查看此分析结果的权限。", { exact: true }).waitFor();
  await page.getByPlaceholder("搜索门店名称").click();
  assert.equal(await page.getByRole("option", { name: "新版本选项", exact: true }).count(), 0);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/clues/filter-options/stores")).length, 3);
}));

for (const failure of ["mismatch", "expired"]) {
  test(`clue option ${failure} never exposes a wrong version or loops recovery`, async () => withPage(async ({ page, requests, handle }) => {
    let latestReads = 0;
    handle(async (route, url) => {
      if (url.pathname.endsWith("/publications/clue-overview/filters")) {
        latestReads++;
        await route.fulfill({ json: payload(clueFilters, "clue-overview", `c${latestReads}`) }); return true;
      }
      if (url.pathname.endsWith("/clues/overview")) {
        await route.fulfill({ json: payload(clueOverview, "clue-overview", url.searchParams.get("publication_id")) }); return true;
      }
      if (!url.pathname.endsWith("/clues/filter-options/stores")) return false;
      await route.fulfill(failure === "expired"
        ? { status: 410, json: { detail: { message: "expired" } } }
        : { json: payload({ stores: [{ store_id: "wrong", store_name: "禁止显示" }] }, "clue-overview", "wrong") }); return true;
    });
    await page.goto(`${baseUrl}/clues`);
    await page.locator(".publication-time").waitFor();
    await page.getByPlaceholder("搜索门店名称").click();
    await page.getByText(failure === "expired" ? "原结果版本已过期，请读取最新结果。" : "发布结果或版本信息暂不可用，请读取最新结果。", { exact: true }).waitFor();
    await page.waitForTimeout(150);
    assert.equal(await page.getByRole("option", { name: "禁止显示", exact: true }).count(), 0);
    assert.equal(latestReads, failure === "expired" ? 2 : 1);
    assert.equal(requests.filter((url) => url.pathname.endsWith("/clues/overview")).length, latestReads);
  }));
}

test("management correction reads live V2 over published V1, preserves conflict input, explicitly reloads V3", async () => withPage(async ({ page, requests, handle }) => {
  let currentVersion = 2;
  const posts = [];
  const invoice = (version) => ({ storeId: "s1", storeName: "已发布门店", statementId: "statement1", statementMonth: "2026-09", statementAmountCent: 10000, confirmedAmountCent: 10000, feeDirection: "MANAGEMENT", status: "APPROVED_SETTLED", processingStatus: "SETTLED", invoiceId: `invoice${version}`, invoiceNumber: String(version).repeat(20), invoiceDate: "2026-10-01", invoiceAmountCent: version * 10000, factoryDeductionDate: "2026-10-01", factoryDeductionAmountCent: version * 10000, versionNo: version, isCurrent: true });
  handle(async (route, url) => {
    if (url.pathname.endsWith("/finance/summary")) {
      await route.fulfill({ json: payload({ metrics: { statementTotalCent: 10000 } }, "finance", "f1") }); return true;
    }
    if (url.pathname.endsWith("/finance/invoices")) {
      await route.fulfill({ json: payload({ list: [invoice(1)], total: 1 }, "finance", "f1") }); return true;
    }
    if (url.pathname.endsWith("/management-invoices/s1/2026-09/current")) {
      assert.equal(url.searchParams.has("publication_id"), false);
      await route.fulfill({ json: payload(invoice(currentVersion)) }); return true;
    }
    if (!url.pathname.endsWith("/management-invoices/s1/2026-09/corrections")) return false;
    posts.push({ body: route.request().postDataJSON(), key: route.request().headers()["idempotency-key"] });
    if (posts.length === 1) {
      currentVersion = 3;
      await route.fulfill({ status: 409, json: { detail: { message: "version conflict" } } });
    } else await route.fulfill({ json: payload(invoice(4)) });
    return true;
  });
  await page.goto(`${baseUrl}/finance/management?month=2026-09`);
  await page.locator("tbody tr").first().dblclick();
  const panel = page.locator(".finance-correction-panel");
  await panel.getByText("已读取实时当前记录。", { exact: false }).waitFor();
  assert.equal(await panel.getByLabel("发票号码", { exact: true }).inputValue(), "2".repeat(20));
  await panel.getByLabel("更正原因", { exact: true }).fill("核对当前实时记录");
  await panel.getByLabel("发票号码", { exact: true }).fill("9".repeat(20));
  await panel.getByRole("button", { name: "确认更正", exact: true }).click();
  await panel.getByText("版本已变化，输入已保留。", { exact: false }).waitFor();
  assert.equal(posts[0].body.readVersion, 2);
  assert.equal(await panel.getByLabel("发票号码", { exact: true }).inputValue(), "9".repeat(20));
  assert.equal(await panel.getByRole("button", { name: "确认更正", exact: true }).isDisabled(), true);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/current")).length, 1);
  await panel.getByRole("button", { name: "读取当前记录", exact: true }).click();
  await panel.getByText("已读取实时当前记录。", { exact: false }).waitFor();
  assert.equal(await panel.getByLabel("发票号码", { exact: true }).inputValue(), "3".repeat(20));
  await panel.getByLabel("更正原因", { exact: true }).fill("重新核对第三版");
  await panel.getByRole("button", { name: "确认更正", exact: true }).click();
  await panel.getByText("更正已保存并保留历史版本", { exact: false }).waitFor();
  assert.equal(posts[1].body.readVersion, 3);
  assert.notEqual(posts[1].key, posts[0].key);
  assert.match(await page.locator("tbody").innerText(), new RegExp("1".repeat(20)));
  assert.equal(requests.filter((url) => url.pathname.endsWith("/finance/summary")).length, 1);
  assert.match(await page.locator(".publication-time").innerText(), /10:00/);
}));


for (const status of [403, 404, 503]) {
  test(`management current read ${status} leaves a clear closable error and cannot submit`, async () => withPage(async ({ page, requests, handle }) => {
    handle(async (route, url) => {
      if (url.pathname.endsWith("/finance/summary")) {
        await route.fulfill({ json: payload({ metrics: {} }, "finance", "f1") }); return true;
      }
      if (url.pathname.endsWith("/finance/invoices")) {
        await route.fulfill({ json: payload({ list: [{ storeId: "s1", storeName: "定位门店", statementMonth: "2026-09", statementAmountCent: 10000, confirmedAmountCent: 10000, feeDirection: "MANAGEMENT", invoiceId: "frozen1", invoiceNumber: "1".repeat(20), invoiceAmountCent: 10000, invoiceDate: "2026-10-01", versionNo: 1, isCurrent: false }], total: 1 }, "finance", "f1") }); return true;
      }
      if (!url.pathname.endsWith("/management-invoices/s1/2026-09/current")) return false;
      await route.fulfill({ status, json: { detail: { message: "current unavailable" } } }); return true;
    });
    await page.goto(`${baseUrl}/finance/management?month=2026-09`);
    await page.locator("tbody").getByText("定位门店", { exact: true }).waitFor();
    await page.locator("tbody tr").first().dblclick();
    const panel = page.locator(".finance-correction-panel");
    await panel.getByRole("alert").waitFor();
    assert.equal(await panel.getByLabel("发票号码", { exact: true }).count(), 0);
    assert.equal(await panel.getByRole("button", { name: "确认更正", exact: true }).isDisabled(), true);
    assert.equal(requests.filter((url) => url.pathname.endsWith("/corrections")).length, 0);
    await panel.getByRole("button", { name: "关闭", exact: true }).click();
    await panel.waitFor({ state: "hidden" });
    assert.match(await page.locator("tbody").innerText(), /定位门店/);
  }));
}


test("mobile published pending V1 locates live V2, and absent current stays a non-submitting 404", async () => withPage(async ({ page, requests, handle }) => {
  let missing = false;
  const pendingRow = { storeId: "s1", storeName: "静态待开票门店", statementMonth: "2026-09", statementAmountCent: 10000, confirmedAmountCent: null, feeDirection: "MANAGEMENT", status: "PENDING_INVOICE", processingStatus: "PENDING_INVOICE", invoiceId: null, invoiceNumber: null, invoiceDate: null, invoiceAmountCent: null, versionNo: null, isCurrent: null };
  handle(async (route, url) => {
    if (url.pathname.endsWith("/finance/summary")) {
      await route.fulfill({ json: payload({ metrics: {} }, "finance", "f1") }); return true;
    }
    if (url.pathname.endsWith("/finance/invoices")) {
      await route.fulfill({ json: payload({ list: [pendingRow], total: 1 }, "finance", "f1") }); return true;
    }
    if (!url.pathname.endsWith("/management-invoices/s1/2026-09/current")) return false;
    await route.fulfill(missing ? { status: 404, json: { detail: { message: "current not found" } } }
      : { json: payload({ ...pendingRow, invoiceId: "live2", versionNo: 2, isCurrent: true, invoiceNumber: "2".repeat(20), invoiceDate: "2026-10-01", invoiceAmountCent: 20000, factoryDeductionDate: "2026-10-01", factoryDeductionAmountCent: 20000 }) }); return true;
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${baseUrl}/finance/management?month=2026-09`);
  const card = page.locator(".data-table-mobile-card").filter({ hasText: "静态待开票门店" });
  await card.getByRole("button", { name: "更正", exact: true }).click();
  const panel = page.locator(".finance-correction-panel");
  await panel.getByText("已读取实时当前记录。", { exact: false }).waitFor();
  assert.equal(await panel.getByLabel("发票号码", { exact: true }).inputValue(), "2".repeat(20));
  assert.match(await panel.innerText(), /当前 V2/);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/current")).length, 1);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/corrections")).length, 0);
  await panel.getByRole("button", { name: "关闭", exact: true }).click();
  missing = true;
  await card.getByRole("button", { name: "更正", exact: true }).click();
  await panel.getByRole("alert").waitFor();
  assert.equal(await panel.getByLabel("发票号码", { exact: true }).count(), 0);
  assert.equal(await panel.getByRole("button", { name: "确认更正", exact: true }).isDisabled(), true);
  await panel.getByRole("button", { name: "关闭", exact: true }).click();
  await panel.waitFor({ state: "hidden" });
  // The same pending row remains keyboard reachable on desktop, using only store/month.
  await page.setViewportSize({ width: 1440, height: 1000 });
  const row = page.locator("tbody tr").first();
  assert.equal(await row.getAttribute("role"), "button");
  await row.focus();
  await row.press("Enter");
  await panel.getByRole("alert").waitFor();
  assert.equal(await panel.getByRole("button", { name: "确认更正", exact: true }).isDisabled(), true);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/current")).length, 3);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/corrections")).length, 0);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/finance/summary")).length, 1);
}));


const authorizationInvoice = { storeId: "s1", storeName: "权限测试门店", statementMonth: "2026-09", statementAmountCent: 10000, confirmedAmountCent: 10000, feeDirection: "MANAGEMENT", status: "APPROVED_SETTLED", processingStatus: "SETTLED", invoiceId: "live2", invoiceNumber: "2".repeat(20), invoiceDate: "2026-10-01", invoiceAmountCent: 20000, factoryDeductionDate: "2026-10-01", factoryDeductionAmountCent: 20000, versionNo: 2, isCurrent: true };

for (const action of ["reread", "submit"]) {
  for (const status of [401, 403]) {
    test(`management ${action} ${status} clears loaded invoice fields and prevents another submit`, async () => withPage(async ({ page, requests, handle }) => {
      let reads = 0;
      handle(async (route, url) => {
        if (url.pathname.endsWith("/finance/summary")) {
          await route.fulfill({ json: payload({ metrics: {} }, "finance", "f1") }); return true;
        }
        if (url.pathname.endsWith("/finance/invoices")) {
          await route.fulfill({ json: payload({ list: [authorizationInvoice], total: 1 }, "finance", "f1") }); return true;
        }
        if (url.pathname.endsWith("/management-invoices/s1/2026-09/current")) {
          reads++;
          await route.fulfill(action === "reread" && reads > 1
            ? { status, json: { detail: { message: "authorization revoked" } } }
            : { json: payload(authorizationInvoice) }); return true;
        }
        if (!url.pathname.endsWith("/management-invoices/s1/2026-09/corrections")) return false;
        await route.fulfill({ status, json: { detail: { message: "authorization revoked" } } }); return true;
      });
      await page.goto(`${baseUrl}/finance/management?month=2026-09`);
      await page.locator("tbody").getByText("权限测试门店", { exact: true }).waitFor();
      await page.locator("tbody tr").first().dblclick();
      const panel = page.locator(".finance-correction-panel");
      await panel.getByText("已读取实时当前记录。", { exact: false }).waitFor();
      await panel.getByLabel("更正原因", { exact: true }).fill("撤权前已核对");
      assert.equal(await panel.getByLabel("发票号码", { exact: true }).inputValue(), "2".repeat(20));
      assert.equal(await panel.getByRole("button", { name: "确认更正", exact: true }).isEnabled(), true);
      await panel.getByRole("button", { name: action === "reread" ? "读取当前记录" : "确认更正", exact: true }).click();
      await panel.getByRole("alert").filter({ hasText: "旧表单已清除" }).waitFor();
      for (const label of ["发票号码", "发票金额（分）", "厂家扣款金额（分）", "更正原因"]) {
        assert.equal(await panel.getByLabel(label, { exact: true }).count(), 0);
      }
      assert.doesNotMatch(await panel.innerText(), /22222222222222222222|输入已保留/);
      assert.equal(await panel.getByRole("button", { name: "确认更正", exact: true }).isDisabled(), true);
      assert.equal(requests.filter((url) => url.pathname.endsWith("/corrections")).length, action === "submit" ? 1 : 0);
      await panel.getByRole("button", { name: "关闭", exact: true }).click();
      await panel.waitFor({ state: "hidden" });
    }));
  }
}

for (const status of [401, 403]) {
  test(`finance analysis ${status} clears the open correction and invalidates an inflight current read`, async () => withPage(async ({ page, requests, handle }) => {
    let denied = false;
    let reads = 0;
    let release;
    const pending = new Promise((resolve) => { release = resolve; });
    handle(async (route, url) => {
      if (url.pathname.endsWith("/finance/summary")) {
        await route.fulfill(denied ? { status, json: { detail: { message: "authorization revoked" } } }
          : { json: payload({ metrics: {} }, "finance", "f1") }); return true;
      }
      if (url.pathname.endsWith("/finance/invoices")) {
        await route.fulfill({ json: payload({ list: [authorizationInvoice], total: 1 }, "finance", "f1") }); return true;
      }
      if (!url.pathname.endsWith("/management-invoices/s1/2026-09/current")) return false;
      reads++;
      if (reads > 1) await pending;
      await route.fulfill({ json: payload(authorizationInvoice) }); return true;
    });
    await page.goto(`${baseUrl}/finance/management?month=2026-09`);
    await page.locator("tbody").getByText("权限测试门店", { exact: true }).waitFor();
    await page.locator("tbody tr").first().dblclick();
    const panel = page.locator(".finance-correction-panel");
    await panel.getByText("已读取实时当前记录。", { exact: false }).waitFor();
    const reread = page.waitForRequest((request) => request.url().includes("/management-invoices/s1/2026-09/current"));
    await panel.getByRole("button", { name: "读取当前记录", exact: true }).click();
    await reread;
    denied = true;
    await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
    await panel.getByRole("alert").filter({ hasText: "旧表单已清除" }).waitFor();
    assert.equal(await panel.getByLabel("发票号码", { exact: true }).count(), 0);
    const lateResponse = page.waitForResponse((response) => response.url().includes("/management-invoices/s1/2026-09/current"));
    release();
    await lateResponse;
    await page.waitForTimeout(100);
    assert.equal(await panel.getByLabel("发票号码", { exact: true }).count(), 0, "late current responses cannot restore revoked invoice fields");
    assert.equal(await panel.getByRole("button", { name: "确认更正", exact: true }).isDisabled(), true);
    assert.equal(requests.filter((url) => url.pathname.endsWith("/corrections")).length, 0);
    await panel.getByRole("button", { name: "关闭", exact: true }).click();
    await panel.waitFor({ state: "hidden" });
  }));
}


test("clue route family retains its pin while other modules get independent publications", async () => withPage(async ({ page, requests, handle }) => {
  let latest = "c1";
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/clue-overview/filters")) {
      await route.fulfill({ json: payload(clueFilters, "clue-overview", url.searchParams.get("publication_id") ?? latest) }); return true;
    }
    if (url.pathname.endsWith("/clues/overview")) {
      await route.fulfill({ json: payload(clueOverview, "clue-overview", url.searchParams.get("publication_id")) }); return true;
    }
    if (url.pathname.endsWith("/clues/filters")) {
      await route.fulfill({ json: payload(clueFilters) }); return true;
    }
    if (url.pathname.endsWith("/clues/assignment-rounds")) {
      assert.equal(url.searchParams.has("publication_id"), false);
      await route.fulfill({ json: payload({ rows: [], pagination: { page: 1, page_size: 50, total: 0, total_pages: 0 } }) }); return true;
    }
    if (url.pathname.endsWith("/publications/sales/filters")) {
      await route.fulfill({ json: payload(filterMeta, "sales", "s1") }); return true;
    }
    if (!url.pathname.endsWith("/dashboard/sales")) return false;
    await route.fulfill({ json: payload(sales, "sales", url.searchParams.get("publication_id")) }); return true;
  });
  await page.goto(`${baseUrl}/clues`);
  await page.locator(".publication-time").waitFor();
  latest = "c2";
  await page.locator('a[href="/clues/details"]').first().click();
  await page.getByRole("heading", { name: "线索跟进列表", exact: true }).waitFor();
  await page.locator(".page-publication-time").waitFor({ state: "hidden" });
  const sameFamily = page.waitForResponse((response) => response.url().includes("/clues/overview?") && response.url().includes("publication_id=c1"));
  await page.locator('a[href="/clues"]').first().click();
  await sameFamily;
  assert.equal(requests.filter((url) => url.pathname.endsWith("/publications/clue-overview/filters")).at(-1).searchParams.get("publication_id"), "c1");
  await page.locator('a[href="/sales"]').first().click();
  await page.locator(".metric-grid--sales").waitFor();
  assert.equal(requests.filter((url) => url.pathname.endsWith("/publications/sales/filters")).at(-1).searchParams.has("publication_id"), false);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/dashboard/sales")).at(-1).searchParams.get("publication_id"), "s1");
  const freshFamily = page.waitForResponse((response) => response.url().includes("/clues/overview?") && response.url().includes("publication_id=c2"));
  await page.locator('a[href="/clues"]').first().click();
  await freshFamily;
  assert.equal(requests.filter((url) => url.pathname.endsWith("/publications/clue-overview/filters")).at(-1).searchParams.has("publication_id"), false);
}));

const periodUnavailable = { status: 503, json: { detail: { code: "PUBLICATION_PERIOD_NOT_READY", message: "period incomplete" } } };
const periodNotice = "所选账期尚未完成，暂不展示金额或提供导出。请选择其他账期，或稍后读取最新结果。";
const settlementPeriods = { ...filterMeta, saleMonths: ["2026-09", "2026-08"], statementMonths: ["2026-09", "2026-08"] };
const settlementRows = { list: [{ storeId: "s1", storeName: "完整账期门店", rank: 1, promotionMonthFeeCent: 12345 }], totals: { promotionMonthFeeCent: 12345 }, total: 1, page: 1, pageSize: 20 };

for (const phase of ["initial", "month", "refresh"]) {
  test(`settlement ${phase} incomplete period commits only same-version filters and clears amounts without retries`, async () => withPage(async ({ page, requests, handle }) => {
    let latest = "period1";
    let incomplete = phase === "initial";
    handle(async (route, url) => {
      const id = url.searchParams.get("publication_id") ?? latest;
      if (url.pathname.endsWith("/publications/settlement/filters")) {
        const response = payload(settlementPeriods, "settlement", id);
        if (id === "period2") response.meta.publication.publishedAt = "2026-10-19T03:00:00Z";
        await route.fulfill({ json: response }); return true;
      }
      if (!url.pathname.endsWith("/dashboard/store-ranking")) return false;
      await route.fulfill(incomplete ? periodUnavailable : { json: payload(settlementRows, "settlement", id) }); return true;
    });
    await page.goto(`${baseUrl}/ranking?periodKey=2026-09`);
    if (phase !== "initial") {
      await page.locator("tbody").getByText("完整账期门店", { exact: true }).waitFor();
      incomplete = true;
      if (phase === "refresh") {
        latest = "period2";
        await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
      } else {
        await page.getByLabel("账期", { exact: true }).click();
        await page.getByRole("option", { name: "2026-08", exact: true }).click();
      }
    }
    await page.getByText(periodNotice, { exact: false }).first().waitFor();
    assert.equal(await page.getByLabel("账期", { exact: true }).isEnabled(), true);
    assert.equal(await page.locator("tbody").getByText("完整账期门店", { exact: true }).count(), 0);
    assert.equal(await page.locator(".metric-card").count(), 0, "unready must not render normal zero metrics");
    if (phase === "refresh") assert.match(await page.locator(".publication-time").innerText(), /11:00/);
    const before = requests.length;
    await page.waitForTimeout(150);
    assert.equal(requests.length, before, "503 has no immediate automatic retry");
    incomplete = false;
    const recovered = page.waitForResponse((response) => response.url().includes("/dashboard/store-ranking?") && response.status() === 200);
    await page.getByLabel("账期", { exact: true }).click();
    await page.getByRole("option", { name: phase === "month" ? "2026-09" : "2026-08", exact: true }).click();
    await recovered;
    await page.locator("tbody").getByText("完整账期门店", { exact: true }).waitFor();
    const id = phase === "refresh" ? "period2" : "period1";
    assert.equal(requests.filter((url) => url.pathname.endsWith("/publications/settlement/filters")).at(-1).searchParams.get("publication_id"), id);
    assert.equal(requests.filter((url) => url.pathname.endsWith("/dashboard/store-ranking")).at(-1).searchParams.get("publication_id"), id);
  }));
}

for (const phase of ["month", "refresh"]) {
  test(`finance ${phase} period-not-ready clears previous money and disables export`, async () => withPage(async ({ page, requests, handle }) => {
    let incomplete = false;
    let latest = "money1";
    handle(async (route, url) => {
      const id = url.searchParams.get("publication_id") ?? latest;
      if (url.pathname.endsWith("/finance/summary")) {
        await route.fulfill(incomplete ? periodUnavailable : { json: payload({ month: "2026-09", metrics: { statementTotalCent: 12345 } }, "finance", id) }); return true;
      }
      if (url.pathname.endsWith("/finance/invoices")) {
        await route.fulfill({ json: payload({ list: [], total: 0 }, "finance", id) }); return true;
      }
      return false;
    });
    await page.goto(`${baseUrl}/finance/promotion?month=2026-09`);
    const total = page.locator(".metric-card").filter({ hasText: "推广费总额" });
    await total.getByText("¥123.45", { exact: true }).waitFor();
    incomplete = true;
    if (phase === "month") await page.getByLabel("筛选账期", { exact: true }).fill("2026-08");
    else {
      latest = "money2";
      await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
    }
    await page.getByText(periodNotice, { exact: true }).first().waitFor();
    assert.doesNotMatch(await total.innerText(), /123\.45|0\.00/);
    assert.equal(await page.getByRole("button", { name: "导出当前筛选结果", exact: true }).isDisabled(), true);
    assert.equal(await page.getByLabel("筛选账期", { exact: true }).isEnabled(), true);
    const before = requests.length;
    await page.waitForTimeout(150);
    assert.equal(requests.length, before);
  }));
}

for (const status of [401, 403]) {
  for (const boundary of ["filters", "data"]) {
    test(`period filters are removed after ${boundary} authorization denial ${status}`, async () => withPage(async ({ page, requests, handle }) => {
      let denied = false;
      handle(async (route, url) => {
        const filters = url.pathname.endsWith("/publications/settlement/filters");
        const data = url.pathname.endsWith("/dashboard/store-ranking");
        if (!filters && !data) return false;
        await route.fulfill(denied && (boundary === "filters" ? filters : data)
          ? { status, json: { detail: { message: "denied" } } }
          : filters ? { json: payload(settlementPeriods, "settlement", "permission1") } : periodUnavailable);
        return true;
      });
      await page.goto(`${baseUrl}/ranking?periodKey=2026-09`);
      await page.getByText(periodNotice, { exact: false }).first().waitFor();
      assert.equal(await page.getByLabel("账期", { exact: true }).isEnabled(), true);
      denied = true;
      const denial = page.waitForResponse((response) => response.status() === status);
      await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
      await denial;
      await page.waitForTimeout(100);
      assert.equal(await page.getByLabel("账期", { exact: true }).isDisabled(), true);
      assert.equal(await page.getByRole("option", { name: "2026-08", exact: true }).count(), 0);
      const latestData = requests.filter((url) => url.pathname.endsWith("/dashboard/store-ranking"));
      assert.equal(latestData.length, boundary === "filters" ? 1 : 2);
    }));
  }
}

test("unready analytical period keeps protected historical billing and invoice entry live", async () => withPage(async ({ page, requests, handle }) => {
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/settlement/filters")) {
      await route.fulfill({ json: payload(settlementPeriods, "settlement", "protected1") }); return true;
    }
    if (url.pathname.endsWith("/monthly-settlement")) {
      await route.fulfill(periodUnavailable); return true;
    }
    if (url.pathname.endsWith("/store-settlements")) {
      await route.fulfill({ json: payload({ list: [{ statementId: "protected-statement", storeId: "s1", storeName: "门店一", month: "2026-08", versionNo: 2, isCurrent: true, status: "CONFIRMED", promotionConfirmableAmountCent: 38000, managementConfirmableAmountCent: 9000, promotionConfirmation: { status: "CONFIRMED", confirmedAt: "2026-09-02T02:00:00Z", confirmedAmountCent: 38000 }, managementConfirmation: null }], total: 1 }) }); return true;
    }
    if (url.pathname.endsWith("/order-fee-details") || url.pathname.endsWith("/disputes")) {
      await route.fulfill({ json: payload({ list: [], total: 0 }) }); return true;
    }
    return false;
  });
  await page.goto(`${baseUrl}/settlement?storeId=s1&month=2026-08`);
  await page.getByText(periodNotice, { exact: false }).first().waitFor();
  const invoice = page.getByRole("link", { name: "进入推广费开票", exact: true });
  await invoice.waitFor();
  assert.match(await invoice.getAttribute("href"), /storeId=s1&month=2026-08/);
  assert.equal(await page.getByRole("button", { name: "确认管理服务费", exact: true }).isEnabled(), true);
  const live = requests.find((url) => url.pathname.endsWith("/store-settlements"));
  assert.equal(live.searchParams.get("month"), "2026-08");
  assert.equal(live.searchParams.has("publication_id"), false);
  assert.equal(requests.filter((url) => url.pathname.endsWith("/monthly-settlement")).length, 1);
}));


// DYDATA-104 ordinary business classification uses actual metadata values.
const realTypes = ["all", "精诚养车", "自定义类型A", "历史类型B"];
const typedMeta = { ...filterMeta, productTypes: realTypes, productScopes: ["旧范围"], productScopeTypeMap: { "旧范围": ["错误类型"] }, statementMonths: ["2026-10", "2026-09", "2026-08"] };
const choose = async (page, label, option) => {
  await page.getByLabel(label, { exact: true }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
};
const assertNoScope = (url) => {
  assert.equal(url.searchParams.has("productScope"), false, url.href);
  assert.equal(url.searchParams.has("product_scope"), false, url.href);
};

test("ordinary sales uses actual type options and removes old scope bookmarks", async () => withPage(async ({ page, requests, handle }) => {
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/sales/filters")) { await route.fulfill({ json: payload(typedMeta, "sales", "types1") }); return true; }
    if (url.pathname.endsWith("/dashboard/sales")) { await route.fulfill({ json: payload(sales, "sales", "types1") }); return true; }
    return false;
  });
  await page.goto(`${baseUrl}/sales?product_scope=旧范围`);
  await page.locator(".metric-card").first().waitFor();
  assert.equal(await page.getByLabel("产品范围", { exact: true }).count(), 0);
  const filtered = page.waitForResponse((r) => new URL(r.url()).searchParams.get("product_type") === "自定义类型A");
  await choose(page, "商品类型", "自定义类型A");
  await filtered;
  const data = requests.filter((url) => url.pathname.endsWith("/dashboard/sales"));
  assert.equal(data.at(-1).searchParams.get("product_type"), "自定义类型A");
  data.forEach(assertNoScope);
  assertNoScope(new URL(page.url()));
  await page.reload();
  await page.locator(".metric-card").first().waitFor();
  assert.equal(requests.filter((url) => url.pathname.endsWith("/dashboard/sales")).at(-1).searchParams.get("product_type"), "自定义类型A");
}));

test("clue ordinary filter displays real product types including historical names", async () => withPage(async ({ page, requests, handle }) => {
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/clue-overview/filters")) { await route.fulfill({ json: payload({ assigned_stores: [], assigned_provinces: [], assigned_cities: [], product_types: realTypes, default_product_type: "all", lead_statuses: [], round_statuses: [], verification_statuses: [] }, "clue-overview", "ct1") }); return true; }
    if (url.pathname.endsWith("/clues/overview")) { await route.fulfill({ json: payload({ total_count: 0, status_counts: {}, follow_up_rate: 0, verification_rate: 0 }, "clue-overview", "ct1") }); return true; }
    return false;
  });
  await page.goto(`${baseUrl}/clues?productScope=旧范围`);
  await choose(page, "商品类型", "历史类型B");
  await page.waitForTimeout(100);
  const data = requests.filter((url) => url.pathname.endsWith("/clues/overview"));
  assert.equal(data.at(-1).searchParams.get("product_type"), "历史类型B");
  data.forEach(assertNoScope);
  assertNoScope(new URL(page.url()));
}));

test("monthly ranking defaults to completed Shanghai month and preserves selection through paging refresh and drilldown", async () => withPage(async ({ page, requests, handle }) => {
  let denied = false;
  handle(async (route, url) => {
    if (url.pathname.endsWith("/publications/settlement/filters")) { await route.fulfill({ json: payload(typedMeta, "settlement", "mt1") }); return true; }
    if (url.pathname.endsWith("/monthly-settlement")) { await route.fulfill({ json: payload({ store: { storeId: "s1", storeName: "门店一" }, month: "2026-08", metrics: {}, computedCumulative: {}, lines: [] }, "settlement", "mt1") }); return true; }
    if (url.pathname.endsWith("/store-settlements") || url.pathname.endsWith("/order-fee-details")) { await route.fulfill({ json: payload({ list: [], total: 0 }) }); return true; }
    if (url.pathname.endsWith("/dashboard/store-ranking")) {
      await route.fulfill(denied ? { status: 403, json: { detail: { message: "denied" } } } : { json: payload({ ...settlementRows, scopeMode: "AUTHORIZED", total: 40, page: Number(url.searchParams.get("page")), periodKey: url.searchParams.get("periodKey") }, "settlement", "mt1") }); return true;
    }
    return false;
  });
  await page.clock.install({ time: new Date("2026-10-01T00:00:00+08:00") });
  await page.addInitScript(() => localStorage.setItem("ranking", JSON.stringify({ periodKey: "2026-10" })));
  await page.goto(`${baseUrl}/ranking?productScope=旧范围`);
  await page.locator("tbody").getByText("完整账期门店").waitFor();
  let reads = requests.filter((url) => url.pathname.endsWith("/dashboard/store-ranking"));
  assert.equal(reads[0].searchParams.get("periodKey"), "2026-09");
  await choose(page, "商品类型", "自定义类型A");
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await page.waitForTimeout(100);
  reads = requests.filter((url) => url.pathname.endsWith("/dashboard/store-ranking"));
  assert.equal(reads.at(-1).searchParams.get("page"), "2");
  assert.equal(reads.at(-1).searchParams.get("periodKey"), "2026-09");
  assert.equal(reads.at(-1).searchParams.get("productType"), "自定义类型A");
  reads.forEach(assertNoScope);
  await choose(page, "账期", "2026-08");
  await page.reload();
  await page.locator("tbody").getByText("完整账期门店").waitFor();
  await page.locator('tbody tr[role="link"]').first().click();
  await page.waitForURL("**/settlement?**");
  assert.equal(new URL(page.url()).searchParams.get("month"), "2026-08");
  assert.equal(new URL(page.url()).searchParams.get("productType"), "自定义类型A");
  assertNoScope(new URL(page.url()));
  await page.goto(`${baseUrl}/ranking?periodKey=2026-08&productType=自定义类型A`);
  await page.locator("tbody").getByText("完整账期门店").waitFor();
  denied = true;
  await page.getByRole("button", { name: "读取最新结果", exact: true }).click();
  await page.getByText("当前账号没有查看该榜单的权限。", { exact: false }).waitFor();
  assert.equal(await page.locator("tbody").getByText("完整账期门店").count(), 0);
  assert.equal(await page.locator(".metric-card").count(), 0);
}));

const feeDetail = (month, productType, page) => ({ context: { month, storeId: null, statementId: null, statementLineId: null, feeDirection: "PROMOTION", productScope: "旧范围", productType, feeRates: [], ruleVersions: [] }, list: [{ feeResultId: "detail1", orderId: "订单分佣测试", couponId: "c1", skuId: "sku1", productName: "历史费用商品", productScope: "隐藏旧范围", productType, originalBusinessMonth: month, originalBaseCent: 0, originalFeeCent: 0, adjustmentBaseCent: 0, adjustmentFeeCent: 0, adjustedNetBaseCent: 0, adjustedNetFeeCent: 0, sourceAmountCent: 0, refundedAmountCent: 0, feeRate: "0.08", ruleVersion: "v1", adjustments: [] }], total: 60, page, pageSize: 50 });

test("fee details share month and type across list paging export refresh and clear failed period", async () => withPage(async ({ page, requests, handle }) => {
  let failed = false;
  handle(async (route, url) => {
    if (url.pathname.endsWith("/meta/filters")) { await route.fulfill({ json: payload(typedMeta) }); return true; }
    if (url.pathname.endsWith("/order-fee-details/export")) { await route.fulfill({ contentType: "text/csv", headers: { "Content-Disposition": "attachment; filename=orders.csv" }, body: "orderId\n订单分佣测试" }); return true; }
    if (url.pathname.endsWith("/order-fee-details")) { await route.fulfill(failed ? periodUnavailable : { json: payload(feeDetail(url.searchParams.get("month"), url.searchParams.get("productType"), Number(url.searchParams.get("page")))) }); return true; }
    return false;
  });
  await page.clock.install({ time: new Date("2026-10-12T09:00:00+08:00") });
  await page.goto(`${baseUrl}/details?product_scope=旧范围`);
  await page.locator("tbody").getByText("订单分佣测试", { exact: true }).waitFor();
  assert.equal(requests.find((url) => url.pathname.endsWith("/order-fee-details")).searchParams.get("month"), "2026-09");
  assert.equal(await page.getByText("隐藏旧范围", { exact: false }).count(), 0);
  await choose(page, "商品类型", "历史类型B");
  await choose(page, "账期", "2026-08");
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await page.waitForTimeout(100);
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出", exact: true }).click();
  await downloaded;
  const exported = requests.find((url) => url.pathname.endsWith("/order-fee-details/export"));
  assert.equal(exported.searchParams.get("month"), "2026-08");
  assert.equal(exported.searchParams.get("productType"), "历史类型B");
  assertNoScope(exported);
  await page.reload();
  await page.locator("tbody").getByText("订单分佣测试", { exact: true }).waitFor();
  failed = true;
  await choose(page, "账期", "2026-09");
  await page.getByText(periodNotice, { exact: false }).first().waitFor();
  assert.equal(await page.locator("tbody").getByText("订单分佣测试", { exact: true }).count(), 0);
  assert.equal(await page.getByRole("button", { name: "导出", exact: true }).isDisabled(), true);
  requests.filter((url) => url.pathname.endsWith("/order-fee-details")).forEach(assertNoScope);
}));

test("admin configuration saves type only, reloads normalized value and exposes metadata failure", async () => withPage(async ({ page, handle }) => {
  let productType = "自定义类型A";
  const writes = [];
  let metadataFailed = false;
  handle(async (route, url) => {
    if (url.pathname.endsWith("/meta/filters")) { await route.fulfill(metadataFailed ? { status: 503, json: { detail: { message: "unavailable" } } } : { json: payload(typedMeta) }); return true; }
    if (url.pathname.endsWith("/admin/sku-products/sku1")) {
      writes.push(route.request().postDataJSON()); productType = "精诚养车";
      await route.fulfill({ json: payload({ skuId: "sku1", productType }) }); return true;
    }
    if (url.pathname.endsWith("/admin/sku-products")) { await route.fulfill({ json: payload({ list: [{ skuId: "sku1", skuName: "配置测试商品", productScope: "隐藏后台范围", productType, configurationStatus: "CONFIGURED", manualModifiedAt: null }], total: 1, page: 1, pageSize: 50, statusCounts: { unconfigured: 0, partial: 0, configured: 1 } }) }); return true; }
    return false;
  });
  await page.goto(`${baseUrl}/admin/product-types?view=configured&productScope=旧范围`);
  await page.getByRole("button", { name: "设置", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("商品类型", { exact: true }).fill("任意输入类型");
  await dialog.getByRole("button", { name: "确认设置", exact: true }).click();
  await page.locator("tbody").getByText("精诚养车", { exact: true }).waitFor();
  assert.deepEqual(writes, [{ productType: "任意输入类型", expectedManualModifiedAt: null }]);
  assert.equal(await page.getByText("隐藏后台范围", { exact: false }).count(), 0);
  assertNoScope(new URL(page.url()));
  metadataFailed = true;
  await page.reload();
  await page.getByRole("alert").filter({ hasText: "商品类型选项暂不可用" }).waitFor();
  assert.equal(await page.getByText("当前展示演示数据", { exact: false }).count(), 0);
}));

test("finance order applied month controls navigation export and refresh while permission failure clears rows", async () => withPage(async ({ page, requests, handle }) => {
  let denied = false;
  handle(async (route, url) => {
    if (url.pathname.endsWith("/admin/finance/order-details/export")) { await route.fulfill({ contentType: "text/csv", headers: { "Content-Disposition": "attachment; filename=finance.csv" }, body: "orderId\n财务测试订单" }); return true; }
    if (url.pathname.endsWith("/admin/finance/order-details")) { await route.fulfill(denied ? { status: 403, json: { detail: { message: "denied" } } } : { json: payload({ list: [{ statementMonth: url.searchParams.get("month"), orderId: "财务测试订单", productType: "历史类型B" }], total: 1, page: 1, pageSize: 50, definitions: {} }) }); return true; }
    return false;
  });
  await page.clock.install({ time: new Date("2026-10-12T09:00:00+08:00") });
  await page.goto(`${baseUrl}/finance/orders/promotion`);
  await page.locator("tbody").getByText("财务测试订单", { exact: true }).waitFor();
  assert.equal(requests.find((url) => url.pathname.endsWith("/admin/finance/order-details")).searchParams.get("month"), "2026-09");
  await page.getByLabel("筛选账期", { exact: true }).fill("2026-08");
  assert.match(await page.getByRole("link", { name: "管理服务费明细", exact: true }).getAttribute("href"), /month=2026-09/);
  await page.getByRole("button", { name: "应用筛选", exact: true }).click();
  await page.locator("tbody").getByText("2026-08", { exact: true }).waitFor();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出全部命中结果", exact: true }).click();
  await downloaded;
  assert.equal(requests.find((url) => url.pathname.endsWith("/admin/finance/order-details/export")).searchParams.get("month"), "2026-08");
  await page.reload();
  await page.locator("tbody").getByText("2026-08", { exact: true }).waitFor();
  denied = true;
  await page.getByLabel("筛选账期", { exact: true }).fill("2026-09");
  await page.getByRole("button", { name: "应用筛选", exact: true }).click();
  await page.getByText("当前筛选结果读取失败。", { exact: true }).waitFor();
  assert.equal(await page.locator("tbody").getByText("财务测试订单", { exact: true }).count(), 0);
}));

test("independent Douyin ranking and export retain byd productScope", async () => withPage(async ({ page, requests, handle }) => {
  handle(async (route, url) => {
    if (url.pathname.endsWith("/douyin-ranking/export")) { await route.fulfill({ contentType: "application/octet-stream", headers: { "Content-Disposition": "attachment; filename=ranking.xlsx" }, body: "test" }); return true; }
    if (url.pathname.endsWith("/douyin-ranking")) { await route.fulfill({ json: payload(ranking, "douyin-ranking", "protect1") }); return true; }
    return false;
  });
  await page.goto(`${baseUrl}/metrics/douyin-ranking?productScope=byd`);
  await page.locator("tbody").getByText("测试集团", { exact: true }).waitFor();
  await page.getByRole("button", { name: "导出排行", exact: true }).click();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 Excel", exact: true }).click();
  await downloaded;
  requests.filter((url) => url.pathname.includes("/douyin-ranking")).forEach((url) => {
    assert.equal(url.searchParams.get("productScope"), "byd");
    assert.equal(url.searchParams.has("productType"), false);
  });
}));


for (const [code, text] of [["PUBLICATION_NOT_READY", "分析结果尚未发布"], ["PUBLICATION_PERIOD_NOT_READY", "所选账期尚未完成"], ["READ_FAILED", "榜单暂不可用"]]) {
  test(`initial settlement ${code} never becomes a real zero result`, async () => withPage(async ({ page, requests, handle }) => {
    const writes = [];
    page.on("request", (request) => { if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) writes.push(request.url()); });
    handle(async (route, url) => {
      if (url.pathname.endsWith("/publications/settlement/filters")) { await route.fulfill({ json: payload(typedMeta, "settlement", "state1") }); return true; }
      if (url.pathname.endsWith("/dashboard/store-ranking")) { await route.fulfill({ status: 503, json: { detail: { code, message: "unavailable" } } }); return true; }
      return false;
    });
    await page.goto(`${baseUrl}/ranking?month=2026-09`);
    await page.getByText(text, { exact: false }).first().waitFor();
    assert.equal(await page.locator(".metric-card").count(), 0);
    assert.deepEqual(writes, []);
    assert.equal(requests.filter((url) => url.pathname.endsWith("/dashboard/store-ranking")).length, 1);
  }));
}
