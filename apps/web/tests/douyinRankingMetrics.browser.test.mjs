import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_NODE_PACKAGE || "playwright");
const baseUrl = process.env.RANKING_TEST_BASE_URL ?? "http://127.0.0.1:5189";
const evidenceDir = process.env.DYDATA115_EVIDENCE_DIR ?? join(tmpdir(), "dydata-115-store-ui");
const user = {
  username: "ranking-test", user_id: "ranking-test", display_name: "Ranking QA",
  role: "admin", is_highest_admin: true, status: "active", can_manage_global_settings: true,
  is_initialized: true, store_ids: [], store_scope_mode: "all", page_keys: ["A03"],
};
const metrics = {
  storeCount: 3, orderCount: 10, orderAverage: 10 / 3,
  followNumerator: 3, followDenominator: 10, follow24hRate: .3,
  followRate: .1, followAnyRate: .5, followAnyNumerator: 5, followAnyDenominator: 10,
  verificationNumerator: 2, verificationDenominator: 10, verificationRate: .2,
  selfStoreVerificationCount: 7,
};

for (const width of [1440, 390]) {
  test(`ranking shares task metrics, scope and self-store count at ${width}px`, async () => {
    const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL });
    const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width === 390 });
    const page = await context.newPage();
    page.setDefaultTimeout(10_000);
    const errors = [];
    const requests = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    let mode = "current";
    const payload = (data, published = false) => ({ data, meta: { source: "postgres", generatedAt: "2026-11-18T06:00:00Z",
      ...(published ? { publication: { id: "ranking-test", module: "douyin-ranking", status: mode === "warming" ? "refreshing" : "available", taskMetricsContract: mode === "warming" ? null : "clue-task-v1", publishedAt: "2026-11-18T06:00:00Z", dataAsOf: "2026-11-18T05:00:00Z" } } : {}) } });
    try {
      await page.route("**/api/v1/**", (route) => {
        const url = new URL(route.request().url());
        if (url.pathname.endsWith("/auth/me")) return route.fulfill({ json: payload(user) });
        if (!url.pathname.endsWith("/dashboard/douyin-ranking")) return route.fulfill({ json: payload({}) });
        requests.push(url);
        let data = { ...metrics };
        if (mode === "empty") data = { ...data, follow24hRate: null, followAnyRate: null, followNumerator: 0, followDenominator: 0, followAnyNumerator: 0, followAnyDenominator: 0, selfStoreVerificationCount: 0 };
        if (mode === "legacy") { delete data.followAnyRate; delete data.selfStoreVerificationCount; data.followRate = .5; }
        if (mode === "warming") data = { ...data, follow24hRate: null, followAnyRate: null, verificationRate: null, selfStoreVerificationCount: null };
        return route.fulfill({ json: payload({
          dataMode: "business", snapshotId: "ranking-test", qualityJson: {},
          periodStart: "2026-11-17", periodEnd: "2026-11-18", level: "group",
          total: 1, page: 1, pageSize: 50, totals: data,
          rows: [{ ...data, key: "test-group", name: "测试集团", rank: 1 }],
          latestObservedAt: "2026-11-18T05:00:00Z", metricDefinitions: {},
        }, true) });
      });
      await page.goto(`${baseUrl}/metrics/douyin-ranking?periodStart=2026-11-17&periodEnd=2026-11-18`);
      await page.getByRole("heading", { name: "抖音经营打榜看板", exact: true }).waitFor();
      assert.match(page.url(), /metrics\/douyin-ranking/);
      assert.ok(await page.title());
      const card = page.locator(".metric-card").filter({ hasText: "24小时跟进率" });
      await card.getByText("50%（5/10）", { exact: false }).waitFor();
      assert.match(await card.innerText(), /有效 3 \/ 接收 10/);
      const selfCard = page.locator(".metric-card").filter({ hasText: "自店核销量" });
      assert.equal(await selfCard.locator(".metric-card__value").innerText(), "7");
      const row = width === 1440 ? page.locator("tbody tr").first() : page.locator(".data-table-mobile-card").first();
      assert.match(await row.innerText(), /30%（3\/10）/);
      assert.match(await row.innerText(), /累计跟进率（辅助）.*50%（5\/10）/s);
      assert.match(await row.innerText(), /20%（2\/10）/);
      const help = card.getByRole("button", { name: "24小时跟进率口径说明", exact: true });
      await help.focus();
      const tooltip = page.locator('[role="tooltip"]:popover-open');
      await tooltip.waitFor();
      assert.match(await tooltip.innerText(), /固定24小时.*全额退款.*提前核销仍保留分母/);
      assert.ok(await help.getAttribute("aria-describedby"));
      await page.keyboard.press("Escape");
      await page.getByLabel("商品范围", { exact: true }).click();
      const filtered = page.waitForResponse((response) => response.url().includes("product_scope=all") || response.url().includes("productScope=all"));
      await page.getByRole("option", { name: "全部商品", exact: true }).click();
      await filtered;
      assert.equal(requests.at(-1).searchParams.get("publication_id"), "ranking-test");
      await mkdir(evidenceDir, { recursive: true });
      await page.screenshot({ path: join(evidenceDir, `ranking-${width}.png`), fullPage: true });
      mode = "empty";
      await page.getByRole("button", { name: "刷新数据", exact: true }).click();
      await card.getByText("暂无样本（0/0）", { exact: false }).waitFor();
      assert.equal(await selfCard.locator(".metric-card__value").innerText(), "0");
      mode = "legacy";
      await page.getByRole("button", { name: "刷新数据", exact: true }).click();
      await card.getByText("50%（5/10）", { exact: false }).waitFor();
      await selfCard.getByText("暂不可用", { exact: true }).waitFor();
      mode = "warming";
      await page.getByRole("button", { name: "刷新数据", exact: true }).click();
      await card.locator(".metric-card__value").getByText("暂不可用", { exact: true }).waitFor();
      assert.doesNotMatch(await card.innerText(), /50%|暂无样本/);
      assert.equal(await page.locator("vite-error-overlay").count(), 0);
      assert.deepEqual(errors, []);
    } finally {
      await context.close();
      await browser.close();
    }
  });
}
