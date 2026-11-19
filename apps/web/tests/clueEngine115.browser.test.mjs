import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_NODE_PACKAGE || "playwright");
const baseUrl = process.env.CLUE_TEST_BASE_URL ?? "http://127.0.0.1:5197";
const evidenceDir = process.env.DYDATA115_EVIDENCE_DIR ?? join(tmpdir(), "dydata-115-store-ui");
const user = { username: "engine-qa", user_id: "engine-qa", display_name: "门店验证", role: "admin", status: "active", is_initialized: true,
  store_ids: [], store_scope_mode: "all", page_keys: ["A01", "A02", "A03"], can_manage_global_settings: false };
const filters = { assigned_stores: [], assigned_provinces: [], assigned_cities: [], product_types: ["保养"], default_product_type: "all", lead_statuses: [], round_statuses: [], verification_statuses: [] };
const overview = { total_clues: 10, active_clues: 4, follow_rate: .6, follow_success_rate: .2, verified_count: 3, self_store_verify_rate: .3, pending_reassign_count: 1,
  follow_24h_rate: .3, follow_any_rate: .6, verification_rate: .2, self_store_verification_count: 7,
  follow_24h_numerator: 3, follow_any_numerator: 6, follow_denominator: 10, verification_numerator: 2, verification_denominator: 10 };
const round = (overrides = {}) => ({ assignment_round_id: "task-1", order_id: "synthetic-115", round_no: 1, lead_status: "active", order_current_status: "active",
  current_assignment_round_id: "task-1", current_round_no: 1, current_round_status: "active_unfollowed", current_assigned_store_id: "store-new", current_assigned_store_name: "新承接门店",
  is_current_round: true, round_effective_status: "active", can_operate_current_round: true, can_delete_follow_up_records: false, routing_mode: "flow",
  round_status: "active_unfollowed", store_display_status: "待跟进", assigned_at: "2026-11-17T01:00:00Z", expires_at: "2026-11-18T01:00:00Z", remaining_reassign_seconds: 1000,
  assigned_store_id: "store-new", assigned_store_name: "新承接门店", phone_masked: "138****0115", product_name: "合成保养商品", product_type: "保养", author_nickname: null,
  followed_at: null, follow_result: "pending", appointment_at: null, reassign_reason: null, reassigned_at: null, verified_store_id: null, verified_store_name: null, verified_at: null, is_self_store_verified: false, ...overrides });
const detail = (rounds, records = []) => ({ order_id: "synthetic-115", order_created_at: "2026-11-16T02:00:00Z", canonical_clue_id: "lead-115", lead_status: rounds.at(-1).lead_status,
  phone_masked: "138****0115", product_id: "product-115", product_name: "合成保养商品", product_type: "保养", author_nickname: null, assigned_city: "深圳", assigned_province: "广东", rounds, follow_up_records: records });
const record = (overrides = {}) => ({ follow_up_record_id: "follow-old", order_id: "synthetic-115", assignment_round_id: "task-old", round_no: 0,
  assigned_store_id: "store-old", assigned_store_name: "原承接门店", follow_result: "further_follow_up", note: "之前沟通记录", operator_user_id: "old-user", operator_username: "原门店", created_at: "2026-11-17T00:10:00Z", ...overrides });
const payload = (data, published = false) => ({ data, meta: { source: "postgres", generated_at: "2026-11-18T06:00:00Z", ...(published ? { publication: { id: "clue-115", module: "clue-overview", status: "available", publishedAt: "2026-11-18T06:00:00Z", dataAsOf: "2026-11-18T05:00:00Z" } } : {}) } });

async function withPage(width, run, account = user) {
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL });
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 1000 }, timezoneId: "America/New_York" });
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  let handler = () => false;
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/auth/me")) return route.fulfill({ json: payload(account) });
    if (await handler(route, url)) return;
    return route.fulfill({ json: payload(url.pathname.endsWith("/filters") ? filters : { stores: [], options: [] }) });
  });
  try { await run({ page, handle: (next) => { handler = next; } }); assert.equal(await page.locator("vite-error-overlay").count(), 0); assert.deepEqual(errors, []); }
  finally { await context.close(); await browser.close(); }
}

for (const width of [1440, 390]) {
  test(`appointment required, zoned, append-only and reloads across rounds at ${width}px`, async () => withPage(width, async ({ page, handle }) => {
    const active = round();
    const old = round({ assignment_round_id: "task-old", round_no: 0, is_current_round: false, round_effective_status: "inactive", can_operate_current_round: false,
      round_status: "expired_pending_reassign", store_display_status: "超期失效", assigned_store_id: "store-old", assigned_store_name: "原承接门店" });
    const records = [record()];
    const submissions = [];
    handle(async (route, url) => {
      if (url.pathname.endsWith("/assignment-rounds")) { await route.fulfill({ json: payload({ rows: [active, old], pagination: { page: 1, page_size: 20, total: 2, total_pages: 1 } }) }); return true; }
      if (url.pathname.endsWith("/follow-up")) {
        const body = route.request().postDataJSON();
        submissions.push(body);
        const saved = record({ ...body, follow_up_record_id: `follow-${submissions.length}`, assigned_store_id: active.assigned_store_id, assigned_store_name: active.assigned_store_name, round_no: 1, created_at: "2026-11-18T06:00:00Z" });
        records.push(saved);
        Object.assign(active, { follow_result: body.follow_result, appointment_at: body.appointment_at ?? null, followed_at: saved.created_at, round_status: "active_followed", store_display_status: "已跟进" });
        active.expires_at = body.appointment_at ? new Date(Date.parse(body.appointment_at) + 72 * 60 * 60 * 1000).toISOString() : "2026-11-25T06:00:00Z";
        await route.fulfill({ json: payload(saved) }); return true;
      }
      if (url.pathname.endsWith("/orders/synthetic-115")) { await route.fulfill({ json: payload(detail([old, active], records)) }); return true; }
      return false;
    });
    await page.goto(`${baseUrl}/clues/details`);
    await page.getByRole("heading", { name: "线索跟进列表", exact: true }).waitFor();
    assert.match(page.url(), /clues\/details/);
    assert.ok(await page.title());
    const list = page.locator(width === 1440 ? ".clue-table-view" : ".clue-card-list");
    await list.getByRole("button", { name: "查看详情", exact: true }).first().click();
    const modal = page.getByRole("dialog");
    await modal.getByText("之前沟通记录", { exact: true }).waitFor();
    await modal.getByRole("radio", { name: "已预约", exact: true }).check();
    const appointment = modal.getByLabel("预约到店时间（北京时间，必填）", { exact: true });
    await modal.getByRole("button", { name: "保存本次跟进", exact: true }).click();
    assert.equal(submissions.length, 0);
    assert.equal(await appointment.evaluate((input) => input.validity.valueMissing), true);
    await appointment.fill("2026-11-25T10:30");
    await modal.getByRole("button", { name: "保存本次跟进", exact: true }).click();
    await modal.getByText("预约到店：2026-11-25 10:30", { exact: true }).waitFor();
    assert.equal(submissions[0].appointment_at, "2026-11-25T10:30:00+08:00");
    assert.equal(submissions[0].note, null);
    await modal.getByLabel("预约到店时间（北京时间，必填）", { exact: true }).fill("2026-11-26T14:15");
    await modal.getByRole("button", { name: "保存本次跟进", exact: true }).click();
    await modal.getByText("预约到店：2026-11-26 14:15", { exact: true }).waitFor();
    assert.equal(await modal.getByText("预约到店：2026-11-25 10:30", { exact: true }).count(), 1);
    assert.equal(await modal.getByRole("button", { name: "删除跟进历史" }).count(), 0, "new tasks remain immutable for admins");
    await mkdir(evidenceDir, { recursive: true });
    if (width === 390) await modal.getByRole("button", { name: "保存本次跟进", exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(evidenceDir, `appointment-${width}.png`), fullPage: false });
    await modal.getByRole("radio", { name: "待进一步跟进", exact: true }).check();
    await modal.getByRole("button", { name: "保存本次跟进", exact: true }).click();
    await modal.getByText("未填写备注", { exact: true }).last().waitFor();
    assert.equal(Object.hasOwn(submissions.at(-1), "appointment_at"), false);
    await page.getByRole("button", { name: "关闭线索详情", exact: true }).click();
    await list.getByRole("button", { name: "查看详情", exact: true }).nth(1).click();
    await modal.getByText("本轮已结束，仅可查看跟进历史。", { exact: true }).waitFor();
    assert.equal(await modal.getByRole("button", { name: "保存本次跟进", exact: true }).count(), 0);
    assert.equal(await modal.getByText("预约到店：2026-11-25 10:30", { exact: true }).count(), 1, "cross-round history stays visible");
  }));

  test(`overview scopes match definitions and old publication fields remain unknown at ${width}px`, async () => withPage(width, async ({ page, handle }) => {
    const requests = [];
    let mode = "current";
    const published = (data) => {
      const result = payload(data, true);
      result.meta.publication.taskMetricsContract = mode === "warming" ? null : "clue-task-v3";
      result.meta.publication.status = mode === "warming" ? "refreshing" : "available";
      return result;
    };
    handle(async (route, url) => {
      if (url.pathname.endsWith("/publications/clue-overview/filters")) { await route.fulfill({ json: published(filters) }); return true; }
      if (url.pathname.endsWith("/clues/overview")) {
        requests.push(url);
        const data = mode === "legacy" ? Object.fromEntries(Object.entries(overview).filter(([key]) => !["follow_24h_rate", "follow_any_rate", "verification_rate", "self_store_verification_count"].includes(key))) : mode === "warming" ? { ...overview, follow_24h_rate: null, follow_any_rate: null, verification_rate: null, self_store_verification_count: null, follow_24h_numerator: null, follow_any_numerator: null, follow_denominator: null, verification_numerator: null, verification_denominator: null } : overview;
        await route.fulfill({ json: published(data) }); return true;
      }
      return false;
    });
    await page.goto(`${baseUrl}/clues`);
    const cards = page.locator(".clue-metric-grid");
    await cards.getByText("自店核销量", { exact: true }).waitFor();
    const metric = (label) => cards.locator(".metric-card").filter({ has: page.locator(".metric-card__label").getByText(label, { exact: true }) }).locator(".metric-card__value");
    assert.equal(await metric("24小时跟进率").innerText(), "30%");
    assert.equal(await metric("累计跟进率（辅助）").innerText(), "60%");
    assert.equal(await metric("自店核销量").innerText(), "7");
    if (width === 390) await page.getByRole("button", { name: /^筛选/ }).click();
    await page.getByLabel("商品范围", { exact: true }).click();
    const changed = page.waitForResponse((response) => response.url().includes("product_scope=byd"));
    await page.getByRole("option", { name: "比亚迪本品", exact: true }).click();
    await changed;
    assert.equal(requests.at(-1).searchParams.get("publication_id"), "clue-115");
    assert.equal(requests.at(-1).searchParams.get("product_type"), "all");
    if (width === 1440) {
      const start = await page.getByLabel("统计日期起", { exact: true }).boundingBox();
      const end = await page.getByLabel("统计日期止", { exact: true }).boundingBox();
      assert.ok(start.x + start.width <= end.x + 1 || start.y + start.height <= end.y + 1, "date controls cannot overlap");
    }
    await mkdir(evidenceDir, { recursive: true });
    await page.screenshot({ path: join(evidenceDir, `clue-overview-${width}.png`), fullPage: true });
    mode = "legacy";
    await page.reload();
    await cards.getByText("暂不可用", { exact: true }).first().waitFor();
    assert.equal(await metric("自店核销量").innerText(), "暂不可用");
    assert.equal(await metric("24小时跟进率").innerText(), "暂不可用");
    mode = "warming";
    await page.reload();
    await cards.getByText("暂不可用", { exact: true }).first().waitFor();
    assert.equal(await metric("24小时跟进率").innerText(), "暂不可用");
    assert.equal(await metric("自店核销量").innerText(), "暂不可用");
    assert.doesNotMatch(await cards.innerText(), /0 \/ 0/);
  }));
}

test("old store sees ended task as read-only with per-round verification attribution", async () => withPage(1440, async ({ page, handle }) => {
  const fact = { verify_id: "verify-115", verified_at: "2026-11-18T01:30:00Z", verified_store_id: "store-old", verified_store_name: "原承接门店",
    assignment_round_id: "task-old", effective_assignment_round_id: null, credited_assignment_round_id: "task-old", is_cross_store: false, is_after_close: true,
    had_valid_follow_before_verify: true, counts_for_store_verification_rate: true, is_back_credit: true };
  const old = round({ assignment_round_id: "task-old", round_no: 0, is_current_round: false, round_effective_status: "inactive", can_operate_current_round: false,
    assigned_store_id: "store-old", assigned_store_name: "原承接门店", lead_status: "converted", order_current_status: "converted", store_display_status: "已核销", round_status: "closed",
    verification_summary: "关单后核销", verification_facts: [fact], verified_at: fact.verified_at, verified_store_id: fact.verified_store_id, verified_store_name: fact.verified_store_name });
  const current = round({ can_operate_current_round: false, round_effective_status: "inactive", lead_status: "converted", order_current_status: "converted", store_display_status: "已核销", round_status: "closed",
    verification_summary: "跨店核销、关单后核销", verification_facts: [{ ...fact, assignment_round_id: "task-1", is_cross_store: true, counts_for_store_verification_rate: false }] });
  handle(async (route, url) => {
    if (url.pathname.endsWith("/assignment-rounds")) { await route.fulfill({ json: payload({ rows: [old], pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 } }) }); return true; }
    if (url.pathname.endsWith("/orders/synthetic-115")) { await route.fulfill({ json: payload(detail([old, current], [record()])) }); return true; }
    return false;
  });
  await page.goto(`${baseUrl}/clues/details`);
  await page.locator(".clue-table-view").getByText("关单后核销", { exact: true }).first().waitFor();
  await page.locator(".clue-table-view").getByRole("button", { name: "查看详情", exact: true }).click();
  const modal = page.getByRole("dialog");
  await modal.getByText("本轮已结束，仅可查看跟进历史。", { exact: true }).waitFor();
  const verification = modal.getByRole("region", { name: "第0轮核销明细", exact: true });
  await verification.getByText("2026-11-18 09:30", { exact: true }).waitFor();
  assert.match(await verification.innerText(), /原承接门店.*核销前有效跟进\s*是.*计入本轮门店核销率\s*是.*补计轮次\s*第0轮/s);
  assert.match(await modal.getByRole("region", { name: "第1轮核销明细", exact: true }).innerText(), /跨店核销、关单后核销.*计入本轮门店核销率\s*否/s);
  assert.equal(await modal.getByRole("button", { name: "保存本次跟进" }).count(), 0);
  assert.equal(await modal.getByRole("button", { name: "删除跟进历史" }).count(), 0);
  await mkdir(evidenceDir, { recursive: true });
  await page.screenshot({ path: join(evidenceDir, "verification-readonly-1440.png"), fullPage: true });
}, { ...user, role: "store", store_scope_mode: "specified", store_ids: ["store-old"] }));

test("a missing selected task never falls through to another current task", async () => withPage(1440, async ({ page, handle }) => {
  const obsolete = round({ assignment_round_id: "obsolete", can_operate_current_round: false, is_current_round: false, round_effective_status: "inactive" });
  handle(async (route, url) => {
    if (url.pathname.endsWith("/assignment-rounds")) { await route.fulfill({ json: payload({ rows: [obsolete], pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 } }) }); return true; }
    if (url.pathname.endsWith("/orders/synthetic-115")) { await route.fulfill({ json: payload(detail([round()])) }); return true; }
    return false;
  });
  await page.goto(`${baseUrl}/clues/details`);
  await page.locator(".clue-table-view").getByRole("button", { name: "查看详情", exact: true }).click();
  const modal = page.getByRole("dialog");
  await modal.getByText("本轮详情暂不可用，请关闭后重新打开。", { exact: true }).waitFor();
  assert.equal(await modal.getByRole("button", { name: "保存本次跟进", exact: true }).count(), 0);
}));
