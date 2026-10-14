import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const baseUrl = process.env.RANKING_TEST_BASE_URL ?? "http://127.0.0.1:5189";
const user = {
  username: "ranking-test", user_id: "ranking-test", display_name: "Ranking QA",
  role: "highest_admin", is_highest_admin: true, status: "active",
  is_initialized: true, store_ids: [], store_scope_mode: "all", page_keys: ["A03"],
};
const metrics = {
  storeCount: 3, orderCount: 10, orderAverage: 10 / 3,
  followNumerator: 3, followDenominator: 10, follow24hRate: .3,
  followRate: .5, followAnyNumerator: 4, followAnyDenominator: 8,
  followActionRate: .25, followActionNumerator: 3, followActionDenominator: 12,
  verificationNumerator: 2, verificationDenominator: 4, verificationRate: .5,
};

for (const width of [1440, 390]) {
  test(`ranking shows independent denominators and accessible help at ${width}px`, async () => {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width, height: 1000 }, hasTouch: width === 390 });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    let empty = false;
    const payload = (data) => ({ data, meta: { source: "business", generatedAt: "2026-09-11T06:00:00Z" } });
    try {
      await page.route("**/api/v1/**", (route) => route.fulfill({ json: payload({}) }));
      await page.route("**/api/v1/auth/me", (route) => route.fulfill({ json: payload(user) }));
      await page.route("**/api/v1/dashboard/douyin-ranking?*", (route) => {
        const data = empty ? { ...metrics, followRate: null, followAnyNumerator: 0, followAnyDenominator: 0, followActionRate: 0, followActionNumerator: 0 } : metrics;
        return route.fulfill({ json: payload({
          dataMode: "business", snapshotId: "ranking-test", qualityJson: {},
          periodStart: "2026-09-07", periodEnd: "2026-09-10", level: "group",
          total: 1, page: 1, pageSize: 50, totals: data,
          rows: [{ ...data, key: "test-group", name: "测试集团", rank: 1 }],
          latestObservedAt: "2026-09-11T06:00:00Z", metricDefinitions: {},
        }) });
      });
      await page.goto(`${baseUrl}/metrics/douyin-ranking?periodStart=2026-09-07&periodEnd=2026-09-10`);
      await page.getByRole("heading", { name: "抖音经营打榜看板", exact: true }).waitFor();
      assert.match(page.url(), /metrics\/douyin-ranking/);
      assert.ok(await page.title());
      const card = page.locator(".metric-card").filter({ hasText: "线索24小时有效跟进率" });
      await card.getByText("50%（4/8）", { exact: false }).waitFor();
      assert.match(await card.innerText(), /25%（3\/12）/);
      assert.match(await card.innerText(), /有效 3 \/ 分配 10/);
      assert.doesNotMatch(await card.innerText(), /暂无样本|无法匹配/);
      const row = width === 1440 ? page.locator("tbody tr").first() : page.locator(".data-table-mobile-card").first();
      assert.match(await row.innerText(), /30%（3\/10）/);
      assert.match(await row.innerText(), /50%（4\/8）/);
      assert.match(await row.innerText(), /25%（3\/12）/);
      const auxiliaryLines = row.locator(".ranking-follow-auxiliary small");
      const firstLine = await auxiliaryLines.nth(0).boundingBox();
      const secondLine = await auxiliaryLines.nth(1).boundingBox();
      assert.ok(secondLine.y >= firstLine.y + firstLine.height, "auxiliary metrics must stay on separate lines");
      const help = card.getByRole("button", { name: "跟进率口径说明", exact: true });
      await help.focus();
      const tooltip = page.locator('[role="tooltip"]:popover-open');
      await tooltip.waitFor();
      assert.match(await tooltip.innerText(), /退款或关闭.*否则分子、分母均不计入/);
      assert.ok(await help.getAttribute("aria-describedby"));
      await page.keyboard.press("Escape");
      assert.equal(await tooltip.count(), 0);
      if (width === 390) await help.tap();
      else await help.hover();
      await tooltip.waitFor();
      const bounds = await tooltip.boundingBox();
      assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width);
      await page.keyboard.press("Escape");
      const actionHelp = row.getByRole("button", { name: "跟进动作率口径说明", exact: true });
      await actionHelp.click();
      await tooltip.waitFor();
      assert.match(await tooltip.innerText(), /包含未接通和战败/);
      assert.match(await tooltip.innerText(), /系统自动核销不算人工动作/);
      await page.screenshot({ path: join(tmpdir(), `ranking-follow-${width}.png`), fullPage: true });
      await page.keyboard.press("Escape");
      empty = true;
      await page.getByRole("button", { name: "刷新数据", exact: true }).click();
      await card.getByText("暂无样本（0/0）", { exact: false }).waitFor();
      assert.match(await card.innerText(), /0%（0\/12）/);
      assert.equal(await page.locator("vite-error-overlay").count(), 0);
      assert.deepEqual(errors, []);
    } finally {
      await context.close();
      await browser.close();
    }
  });
}
