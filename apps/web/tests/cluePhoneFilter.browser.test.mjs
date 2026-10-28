import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const baseUrl = process.env.CLUE_TEST_BASE_URL ?? "http://127.0.0.1:5196";
const evidenceDir = process.env.CLUE_TEST_EVIDENCE_DIR ?? "tmp/clue-phone-ui";
const PHONE = "13812345678";

test("exact phone input uses private POST, validates and resets pagination", async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.CLUE_TEST_BROWSER_CHANNEL ?? "msedge" });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
    const errors = [];
    const requests = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
    const envelope = data => ({ data, meta: { source: "postgres", generated_at: "2026-10-27T00:00:00Z" } });
    await page.route("**/api/v1/**", route => {
      const request = route.request();
      const url = new URL(request.url());
      assert.ok(!request.url().includes(PHONE), "Phone must never enter a request URL");
      if (url.pathname.endsWith("/filters")) return route.fulfill({ json: envelope({ assigned_stores: [], assigned_provinces: [], assigned_cities: [], product_types: [], default_product_type: "all", lead_statuses: [], round_statuses: [], verification_statuses: [] }) });
      if (url.pathname.endsWith("/assignment-rounds/export")) {
        requests.push({ export: true, method: request.method(), body: request.postDataJSON() });
        return route.fulfill({ contentType: "text/csv", body: "order_id\nsynthetic-order\n", headers: { "Content-Disposition": "attachment; filename=synthetic.csv" } });
      }
      if (url.pathname.endsWith("/assignment-rounds")) {
        const body = request.method() === "POST" ? request.postDataJSON() : null;
        const current = body?.page ?? Number(url.searchParams.get("page") ?? 1);
        requests.push({ method: request.method(), body, page: current });
        return route.fulfill({ json: envelope({ rows: [], pagination: { page: current, page_size: 20, total: 45, total_pages: 3 } }) });
      }
      return route.fulfill({ json: envelope({ stores: [], options: [] }) });
    });
    await page.goto(`${baseUrl}/tests/dydata106.html`);
    await page.getByRole("heading", { name: "当前筛选结果" }).waitFor();
    assert.match(await page.title(), /DYDATA-106/);
    const field = page.getByRole("textbox", { name: "手机号精准查询" });
    await field.fill("5678");
    await page.getByRole("button", { name: "查询手机号", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "请输入完整的11位中国大陆手机号" }).waitFor();
    assert.ok(!requests.some(r => r.body?.filters?.phone));
    await mkdir(evidenceDir, { recursive: true });
    await page.screenshot({ path: join(evidenceDir, "phone-invalid-desktop.png"), fullPage: true });
    await field.fill(`  ${PHONE}  `);
    const query = page.waitForResponse(response => response.url().endsWith("/clues/assignment-rounds") && response.request().method() === "POST");
    await field.press("Enter");
    await query;
    assert.equal(requests.at(-1).body.filters.phone, PHONE);
    assert.equal(requests.at(-1).body.page, 1);
    await page.getByText("138****5678", { exact: false }).waitFor({ state: "attached" });
    await Promise.all([page.waitForResponse(response => response.request().postData()?.includes('"page":2')),
      page.getByRole("button", { name: "下一页", exact: true }).click()]);
    assert.equal(requests.at(-1).page, 2);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "导出", exact: true }).click();
    await download;
    assert.equal(requests.at(-1).method, "POST");
    assert.equal(requests.at(-1).body.filters.phone, PHONE);
    assert.ok(!page.url().includes(PHONE));
    assert.equal(await page.evaluate(() => Object.values(localStorage).some(value => value.includes("13812345678"))), false);
    await page.screenshot({ path: join(evidenceDir, "phone-filtered-desktop.png"), fullPage: true });
    const clear = page.waitForResponse(response => response.url().includes("/clues/assignment-rounds") && !response.url().endsWith("/export"));
    await page.getByRole("button", { name: "清空筛选", exact: true }).click();
    await clear;
    assert.equal(await field.inputValue(), "");
    assert.equal(requests.at(-1).page, 1);
    assert.ok(!requests.at(-1).body?.filters?.phone);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: /^筛选/ }).click();
    await field.fill("5678");
    await page.getByRole("button", { name: "查询手机号", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "请输入完整" }).waitFor();
    await page.screenshot({ path: join(evidenceDir, "phone-invalid-mobile.png"), fullPage: true });
    assert.deepEqual(errors, []);
    assert.equal(await page.locator("vite-error-overlay").count(), 0);
  } finally { await browser.close(); }
});
