import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_NODE_PACKAGE || "playwright");
const baseUrl = process.env.CLUE_ROUTING_TEST_BASE_URL || "http://127.0.0.1:5198";
const evidenceDir = process.env.CLUE_ROUTING_EVIDENCE_DIR || join(tmpdir(), "dydata-115-admin-ui");
const policy = { appointment_hours: 72, further_follow_up_hours: 168, unreachable_hours: 168, pending_action: "next", appointment_action: "next", further_follow_up_action: "next", unreachable_action: "close" };
const envelope = (data) => ({ data, meta: { source: "postgres", generated_at: "2026-11-18T06:00:00Z" } });

function makeProduct(index) {
  const id = String(index).padStart(6, "0");
  return { product_id: id, product_name: `${index <= 50 ? "精诚养车" : "比亚迪本品"}保养套餐 ${id}`, product_scope: index <= 50 ? "jingcheng" : "byd", routing_enabled: false, rule_version_id: null, first_follow_up_sla_hours: 24, follow_up_policy: { ...policy }, store_ids: index === 2 ? [] : ["001000"], list_version: index === 2 ? null : 1, can_manage: true };
}

async function withApp(options, run) {
  const browser = await chromium.launch({ headless: true, channel: process.env.CLUE_ROUTING_BROWSER_CHANNEL || "msedge" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  const state = { products: Array.from({ length: options.count ?? 55 }, (_, index) => makeProduct(index + 1)), requests: [], errors: [], failOnce: options.failOnce, transportOnce: options.transportOnce, grants: ["owner"], sharedGrants: options.maintainer ? ["owner"] : [], headquartersOpen: true, resumeAttempts: 0, shared: { rule_version_id: "BASE1", first_follow_up_sla_hours: 24, follow_up_policy: { ...policy }, can_manage: true }, idempotency: new Map() };
  page.on("pageerror", (error) => state.errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) state.errors.push(message.text());
  });
  const matching = (filters) => state.products.filter((row) => (filters?.product_scope === "all" || !filters?.product_scope || row.product_scope === filters.product_scope) && (!filters?.q || `${row.product_id} ${row.product_name}`.includes(filters.q)));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    const body = request.method() === "GET" ? undefined : request.postDataJSON();
    state.requests.push({ path, method: request.method(), body, headers: request.headers() });
    if (path === "/auth/me") return route.fulfill({ json: envelope({ user_id: options.admin ? "admin" : "owner", username: "synthetic-test-user", display_name: options.admin ? "测试管理员" : "测试商品负责人", role: options.admin ? "admin" : "store", store_scope_mode: options.admin ? "all" : "none", store_ids: [], page_keys: options.admin ? ["D01", "D05", "D06", "D07", "D08"] : ["D05"], can_manage_global_settings: Boolean(options.admin), status: "active", is_initialized: true }) });
    if (path === "/admin/clue-routing/products" && request.method() === "GET") {
      if (options.forbidden) return route.fulfill({ status: 403, json: { detail: "无商品管理权限" } });
      const rows = options.maintainer ? [] : matching(Object.fromEntries(url.searchParams));
      const pageNumber = Number(url.searchParams.get("page"));
      const pageSize = Number(url.searchParams.get("page_size"));
      return route.fulfill({ json: envelope({ rows: structuredClone(rows.slice((pageNumber - 1) * pageSize, pageNumber * pageSize)), total: rows.length, page: pageNumber, page_size: pageSize, can_manage_grants: Boolean(options.admin), ...(options.legacySharedCapability ? {} : { can_manage_shared_rule: Boolean(options.admin || state.sharedGrants.includes("owner")) }) }) });
    }
    if (path === "/admin/clue-routing/products/batch") {
      const key = request.headers()["idempotency-key"];
      if (!body.preview && key && state.idempotency.has(key)) return route.fulfill({ json: envelope(state.idempotency.get(key)) });
      const ids = body.all_matching ? matching(body.filters).map((row) => row.product_id) : body.product_ids;
      const results = ids.map((id) => {
        const row = state.products.find((item) => item.product_id === id);
        if (!row) return { product_id: id, status: "failed", error: { code: "PRODUCT_FORBIDDEN", message: "该商品不存在或无管理权限。" }, before: {}, after: {} };
        const before = structuredClone(row);
        const after = structuredClone(row);
        const stores = body.store_ids ?? body.lists?.find((item) => item.product_id === id)?.store_ids;
        if (body.action === "publish_list" && (!stores?.length || stores.includes("bad-store"))) return { product_id: id, status: "failed", error: { code: stores?.length ? "UNKNOWN_STORE_IDS" : "STORE_IDS_REQUIRED", message: "请核对该商品适用门店名单。" }, before, after: before };
        if (body.action === "enable" && (!row.list_version || !row.store_ids.length)) return { product_id: id, status: "failed", error: { code: "PUBLISHED_LIST_REQUIRED", message: "请先发布并确认该商品的有效门店名单。" }, before, after: before };
        if (body.action === "enable" && !body.preview && body.expected_list_versions?.[id] !== row.list_version) return { product_id: id, status: "failed", error: { code: "LIST_VERSION_CHANGED", message: "名单版本已变化，请重新预览并确认最新名单。" }, before, after: before };
        if (!body.preview && state.failOnce === id) {
          state.failOnce = null;
          return { product_id: id, status: "failed", error: { code: "CONFLICT", message: "配置已变化，请重新预览。" }, before, after: before };
        }
        if (body.action === "publish_list") { after.store_ids = stores; if (!body.preview) after.list_version = (row.list_version || 0) + 1; }
        if (body.action === "request_auto_list") {
          const adopt = row.douyin_store_scope?.status === "valid" &&
            (body.preview || body.expected_douyin_scope_checks?.[id] === row.douyin_store_scope.checked_at);
          after.store_list_source = adopt ? "douyin" : "auto_pending";
          if (adopt) {
            after.store_ids = ["009101"];
            if (!body.preview) after.list_version = "DOUYIN-LIST-1";
          }
        }
        if (body.action === "restore_manual_list") {
          after.store_list_source = "manual";
          after.list_version = 1;
          after.store_ids = ["001000"];
        }
        if (body.action === "publish_rule") {
          if (body.rules.first_follow_up_sla_hours !== undefined) after.first_follow_up_sla_hours = body.rules.first_follow_up_sla_hours;
          const { first_follow_up_sla_hours, ...newPolicy } = body.rules;
          after.follow_up_policy = { ...after.follow_up_policy, ...newPolicy };
          if (!body.preview) after.rule_version_id = `RULE-${id}-${Date.now()}`;
        }
        if (body.action === "enable") { after.routing_enabled = true; if (!body.preview && !after.rule_version_id) after.rule_version_id = `RULE-${id}-first`; }
        if (body.action === "disable") after.routing_enabled = false;
        if (!body.preview) Object.assign(row, after);
        return { product_id: id, status: body.preview ? "preview" : "success", before, after };
      });
      const data = { results, total: results.length, succeeded: results.filter((row) => row.status !== "failed").length, failed: results.filter((row) => row.status === "failed").length };
      if (!body.preview && key) state.idempotency.set(key, data);
      if (!body.preview && state.transportOnce) { state.transportOnce = false; return route.abort("connectionfailed"); }
      return route.fulfill({ json: envelope(data) });
    }
    if (/\/products\/[^/]+\/douyin-store-scope$/.test(path)) {
      const productId = path.split("/").at(-2);
      const product = state.products.find((row) => row.product_id === productId);
      return route.fulfill({ json: envelope({ product_id: productId, douyin_store_scope: product?.douyin_store_scope ?? null, store_ids: ["009101"] }) });
    }
    if (/\/products\/[^/]+\/grants$/.test(path)) {
      if (!options.admin) return route.fulfill({ status: 403, json: { detail: "无授权管理权限" } });
      if (body) state.grants = body.user_ids;
      return route.fulfill({ json: envelope({ product_id: path.split("/").at(-2), user_ids: state.grants, users: [{ user_id: "owner", username: "owner", display_name: "商品负责人甲" }, { user_id: "manager2", username: "manager2", display_name: "商品负责人乙" }] }) });
    }
    if (path === "/admin/clue-routing/shared-rule/grants") {
      if (!options.admin) return route.fulfill({ status: 403, json: { detail: "无共享基座授权管理权限" } });
      if (body) state.sharedGrants = body.user_ids;
      return route.fulfill({ json: envelope({ user_ids: state.sharedGrants, users: [{ user_id: "owner", username: "owner", display_name: "商品负责人甲" }, { user_id: "manager2", username: "manager2", display_name: "项目组成员乙" }] }) });
    }
    if (path === "/admin/clue-routing/shared-rule") {
      if (!options.admin && !state.sharedGrants.includes("owner")) return route.fulfill({ status: 403, json: { detail: "无共享规则权限" } });
      if (!body) return route.fulfill({ json: envelope(structuredClone(state.shared)) });
      const before = structuredClone(state.shared);
      const { first_follow_up_sla_hours, ...changes } = body.rules;
      const after = { ...before, first_follow_up_sla_hours, follow_up_policy: { ...before.follow_up_policy, ...changes }, rule_version_id: body.preview ? before.rule_version_id : "BASE2" };
      if (!body.preview) state.shared = after;
      return route.fulfill({ json: envelope({ before, after, status: body.preview ? "preview" : "success" }) });
    }
    if (path === "/admin/clue-allocation/headquarters-pool") {
      const rows = state.headquartersOpen ? [{ headquarters_pool_entry_id: "hq-test", lead_key: "synthetic-lead", canonical_clue_id: "synthetic-clue", order_id: "synthetic-order", status: "active", reason: "missing_anchor", reason_code: "missing_anchor", normalized_order_status: "fulfilling", order_status: "fulfilling", entered_at: "2026-11-18T05:00:00Z", routing_product_id: "000001", pending_round_no: 1, can_resume: true }] : [];
      return route.fulfill({ json: envelope({ rows, pagination: { page: 1, page_size: 50, total: rows.length, total_pages: rows.length }, summary: { current_inventory: rows.length, filtered_total: rows.length }, filter_options: { entry_statuses: ["active", "closed"], reason_codes: ["missing_anchor"], normalized_order_statuses: ["fulfilling"], city_codes: [] } }) });
    }
    if (path.endsWith("/headquarters-pool/hq-test/resume")) {
      state.resumeAttempts += 1;
      if (state.resumeAttempts === 1) return route.fulfill({ status: 409, json: { detail: "订单状态已变化，请刷新后重新确认。" } });
      state.headquartersOpen = false;
      return route.fulfill({ json: envelope({ status: "assigned", selected_store_id: "001002", assignment_round_id: "round-new", reason: null }) });
    }
    if (path === "/admin/clue-allocation/decisions") return route.fulfill({ json: envelope({ rows: [{ strategy_type: "original_store_direct", decision_status: "assigned", selected_store_id: "001001", reason: "selected" }, { strategy_type: "product_routing_finalization", decision_status: "closed", reason: "product_routing_no_candidate" }], pagination: { page: 1, page_size: 50, total: 2, total_pages: 1 } }) });
    if (path === "/admin/clue-allocation/cycles") return route.fulfill({ json: envelope({ rows: [{ allocation_cycle_id: "cycle-closed", cycle_type: "trial", status: "completed", execution_mode: "trial", actual_impact: { assigned: 1, headquarters: 0, closed: 2, skipped: 0, failed: 0 } }], pagination: { page: 1, page_size: 50, total: 1, total_pages: 1 } }) });
    if (path === "/admin/clue-allocation/store-scores" || path === "/admin/clue-allocation/audit-logs") return route.fulfill({ json: envelope({ rows: [], run: null, pagination: { page: 1, page_size: 50, total: 0, total_pages: 0 } }) });
    return route.fulfill({ status: 404, json: { detail: "unexpected test endpoint" } });
  });
  try {
    await mkdir(evidenceDir, { recursive: true });
    await run(page, state);
    assert.deepEqual(state.errors, []);
    assert.equal(await page.locator("vite-error-overlay").count(), 0);
  } finally { await browser.close(); }
}

const productRoute = `${baseUrl}/admin/clue-routing/products`;
async function openProducts(page) {
  await page.goto(productRoute);
  await page.getByRole("heading", { name: "商品线索流转", exact: true }).waitFor();
  await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).waitFor();
  assert.equal(page.url(), productRoute);
  assert.match(await page.title(), /抖音/);
}
function writes(state) { return state.requests.filter((request) => request.path.endsWith("/products/batch") && request.body?.preview === false); }

test("administrator inspects and adopts a saved BYD scope with routing still off", { timeout: 120000 }, async () => {
  await withApp({ admin: true, count: 2 }, async (page, state) => {
    const checkedAt = "2026-11-25T00:00:00+00:00";
    Object.assign(state.products[1], { product_scope: "byd", product_name: "比亚迪本品保养套餐",
      store_list_source: "manual", douyin_store_scope: { status: "valid", checked_at: checkedAt, last_success_at: checkedAt, store_count: 1 } });
    await openProducts(page);
    await page.getByRole("button", { name: "查看 1 家门店", exact: true }).click();
    const detail = page.getByRole("dialog", { name: "抖音适用门店名单" });
    await detail.getByText("1 家门店，展开编码").click();
    await detail.getByText("009101", { exact: true }).waitFor();
    await detail.getByRole("button", { name: "关闭", exact: true }).last().click();
    await page.getByRole("checkbox", { name: "选择商品 000002", exact: true }).check();
    await page.getByRole("button", { name: "接入抖音自动名单", exact: true }).click();
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认接入抖音自动名单（1 个）", exact: true }).click();
    await page.getByRole("heading", { name: "接入抖音自动名单 · 逐商品结果", exact: true }).waitFor();
    assert.deepEqual(writes(state)[0].body.expected_douyin_scope_checks, { "000002": checkedAt });
    assert.equal(state.products[1].store_list_source, "douyin");
    assert.equal(state.products[1].routing_enabled, false);
  });
});

test("administrator previews and restores the manual store list", { timeout: 120000 }, async () => {
  await withApp({ admin: true }, async (page, state) => {
    Object.assign(state.products[0], { store_list_source: "douyin", list_version: 2, store_ids: ["001002"], routing_enabled: true });
    await openProducts(page);
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).check();
    await page.getByRole("button", { name: "切回手动名单", exact: true }).click();
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认切回手动名单（1 个）", exact: true }).waitFor();
    assert.equal(writes(state).length, 0);
    await page.getByRole("button", { name: "确认切回手动名单（1 个）", exact: true }).click();
    await page.getByRole("heading", { name: "切回手动名单 · 逐商品结果", exact: true }).waitFor();
    assert.equal(writes(state)[0].body.action, "restore_manual_list");
    assert.equal(state.products[0].store_list_source, "manual");
    assert.equal(state.products[0].routing_enabled, true);
    assert.deepEqual(state.products[0].store_ids, ["001000"]);
    await page.screenshot({ path: join(evidenceDir, "restore-manual-desktop.png"), fullPage: false });
  });
});

test("product owner can publish only selected fields across pages and retry only failed products", { timeout: 120000 }, async () => {
  await withApp({ failOnce: "000051" }, async (page, state) => {
    await openProducts(page);
    assert.equal(await page.getByRole("link", { name: "线索分配规则", exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "精诚养车共享基座" }).count(), 0);
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).check();
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await page.getByRole("checkbox", { name: "选择商品 000051", exact: true }).check();
    await page.getByRole("button", { name: "按字段批量改规则" }).click();
    await page.getByRole("checkbox", { name: "修改首次跟进期限（小时）", exact: true }).check();
    await page.getByRole("spinbutton", { name: "首次跟进期限（小时）", exact: true }).fill("48");
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("heading", { name: "发布商品规则 · 确认预览" }).waitFor();
    assert.equal(writes(state).length, 0, "preview must not publish");
    assert.equal(state.products[0].first_follow_up_sla_hours, 24);
    await page.screenshot({ path: join(evidenceDir, "rule-preview-desktop.png"), fullPage: false });
    await page.getByRole("button", { name: "确认发布商品规则（2 个）", exact: true }).click();
    await page.getByRole("heading", { name: "发布商品规则 · 逐商品结果" }).waitFor();
    assert.deepEqual(writes(state)[0].body.product_ids, ["000001", "000051"]);
    assert.deepEqual(writes(state)[0].body.rules, { first_follow_up_sla_hours: 48 });
    assert.equal(state.products[0].first_follow_up_sla_hours, 48);
    assert.equal(state.products[50].first_follow_up_sla_hours, 24);
    await page.getByRole("button", { name: "仅重试失败商品（1）" }).click();
    await page.getByRole("button", { name: "确认发布商品规则（1 个）", exact: true }).click();
    await page.getByRole("heading", { name: "发布商品规则 · 逐商品结果" }).waitFor();
    assert.deepEqual(writes(state)[1].body.product_ids, ["000051"]);
    assert.notEqual(writes(state)[0].headers["idempotency-key"], writes(state)[1].headers["idempotency-key"]);
    assert.equal(state.products[50].first_follow_up_sla_hours, 48);
    assert.equal(state.products[0].routing_enabled, false);
    assert.deepEqual(state.products[0].follow_up_policy, policy);
    assert.ok(state.requests.filter((request) => request.path === "/admin/clue-routing/products" && request.method === "GET").length >= 4);
    assert.equal(state.requests.some((request) => /clue-allocation\/(rules|cycles|audit)/.test(request.path)), false);
  });
});

test("all-filtered list preview freezes authorized IDs and publication keeps routing disabled", { timeout: 120000 }, async () => {
  await withApp({}, async (page, state) => {
    await openProducts(page);
    await page.getByRole("button", { name: "全选所有筛选结果", exact: true }).click();
    await page.getByRole("button", { name: "导入 / 发布门店名单" }).click();
    await page.getByRole("textbox", { name: "门店编码名单", exact: true }).fill("001001\n001002\n001001");
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认发布适用门店名单（55 个）", exact: true }).waitFor();
    const preview = state.requests.filter((request) => request.path.endsWith("/products/batch")).at(-1);
    assert.equal(preview.body.all_matching, true);
    state.products.push(makeProduct(56));
    await page.getByRole("button", { name: "确认发布适用门店名单（55 个）", exact: true }).click();
    await page.getByRole("heading", { name: "发布适用门店名单 · 逐商品结果" }).waitFor();
    assert.equal(writes(state)[0].body.all_matching, false);
    assert.equal(writes(state)[0].body.product_ids.length, 55);
    assert.deepEqual(state.products[0].store_ids, ["001001", "001002"]);
    assert.deepEqual(state.products[55].store_ids, ["001000"]);
    assert.ok(state.products.every((row) => !row.routing_enabled));
  });
});

test("uncertain transport retry preserves the confirmed body and idempotency key", { timeout: 120000 }, async () => {
  await withApp({ transportOnce: true }, async (page, state) => {
    await openProducts(page);
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).check();
    await page.getByRole("button", { name: "导入 / 发布门店名单" }).click();
    await page.getByRole("textbox", { name: "门店编码名单", exact: true }).fill("001001");
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认发布适用门店名单（1 个）", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "请重试本次提交" }).waitFor();
    assert.equal(state.products[0].list_version, 2, "server committed before connection failure");
    await page.getByRole("button", { name: "重试本次提交", exact: true }).click();
    await page.getByRole("heading", { name: "发布适用门店名单 · 逐商品结果" }).waitFor();
    assert.equal(writes(state).length, 2);
    assert.deepEqual(writes(state)[0].body, writes(state)[1].body);
    assert.equal(writes(state)[0].headers["idempotency-key"], writes(state)[1].headers["idempotency-key"]);
    assert.equal(state.products[0].list_version, 2, "transport retry must not create another publication");
  });
});

test("all-filtered preview supports more than five thousand products while rendering paginated results", { timeout: 120000 }, async () => {
  await withApp({ count: 5001 }, async (page, state) => {
    await openProducts(page);
    await page.getByRole("button", { name: "全选所有筛选结果", exact: true }).click();
    await page.getByRole("button", { name: "导入 / 发布门店名单" }).click();
    await page.getByRole("textbox", { name: "门店编码名单", exact: true }).fill("001001");
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认发布适用门店名单（5001 个）", exact: true }).waitFor();
    assert.equal(await page.getByRole("dialog").getByRole("row").count(), 21);
    await page.getByRole("button", { name: "确认发布适用门店名单（5001 个）", exact: true }).click();
    await page.getByRole("heading", { name: "发布适用门店名单 · 逐商品结果" }).waitFor();
    assert.equal(writes(state)[0].body.product_ids.length, 5001);
    assert.ok(state.products.every((row) => row.store_ids[0] === "001001" && !row.routing_enabled));
  });
});

test("per-product CSV import keeps leading zeros and reports unauthorized IDs individually", { timeout: 120000 }, async () => {
  await withApp({}, async (page, state) => {
    await openProducts(page);
    await page.getByRole("button", { name: "导入 / 发布门店名单" }).click();
    await page.getByRole("tab", { name: "按商品导入不同名单" }).click();
    await page.getByLabel("导入 CSV 或文本文件", { exact: true }).setInputFiles({ name: "synthetic.csv", mimeType: "text/csv", buffer: Buffer.from("product_id,store_id\n000001,001001\n000001,001002\n999999,001003\n") });
    await page.getByText("已识别 2 个商品", { exact: false }).waitFor();
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认发布适用门店名单（1 个）", exact: true }).click();
    await page.getByRole("heading", { name: "发布适用门店名单 · 逐商品结果" }).waitFor();
    assert.deepEqual(writes(state)[0].body.product_ids, ["000001"]);
    assert.deepEqual(writes(state)[0].body.lists, [{ product_id: "000001", store_ids: ["001001", "001002"] }]);
    await page.getByText("该商品不存在或无管理权限。", { exact: true }).first().waitFor();
  });
});

test("enable pins the reviewed list version and stale versions require another preview", { timeout: 120000 }, async () => {
  await withApp({}, async (page, state) => {
    await openProducts(page);
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).check();
    await page.getByRole("button", { name: "正式开启 / 重新开启", exact: true }).click();
    await page.getByRole("textbox", { name: "业务负责人授权依据（必填）", exact: true }).fill("合成业务授权依据");
    await page.getByRole("checkbox", { name: "已核对发布的有效名单，并获得业务负责人正式开启授权", exact: true }).check();
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认正式开启 / 重新开启流转（1 个）", exact: true }).waitFor();
    state.products[0].list_version = 2;
    await page.getByRole("button", { name: "确认正式开启 / 重新开启流转（1 个）", exact: true }).click();
    await page.getByRole("heading", { name: "正式开启 / 重新开启流转 · 逐商品结果" }).waitFor();
    assert.deepEqual(writes(state)[0].body.expected_list_versions, { "000001": 1 });
    assert.equal(state.products[0].routing_enabled, false);
    await page.getByText("名单版本已变化，请重新预览并确认最新名单。", { exact: true }).first().waitFor();
    await page.getByRole("button", { name: "仅重试失败商品（1）", exact: true }).click();
    await page.getByRole("button", { name: "确认正式开启 / 重新开启流转（1 个）", exact: true }).click();
    await page.getByRole("heading", { name: "正式开启 / 重新开启流转 · 逐商品结果" }).waitFor();
    assert.deepEqual(writes(state)[1].body.expected_list_versions, { "000001": 2 });
    assert.equal(state.products[0].routing_enabled, true);
  });
});

test("enable requires explicit business authorization and a published list; disable and re-enable are independent", { timeout: 120000 }, async () => {
  await withApp({}, async (page, state) => {
    await openProducts(page);
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).check();
    await page.getByRole("checkbox", { name: "选择商品 000002", exact: true }).check();
    await page.getByRole("button", { name: "正式开启 / 重新开启", exact: true }).click();
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "请填写业务负责人授权依据" }).waitFor();
    assert.equal(state.requests.some((request) => request.path.endsWith("/products/batch")), false);
    await page.getByRole("textbox", { name: "业务负责人授权依据（必填）" }).fill("业务负责人已确认 2026-11-18 测试名单并授权本次开启");
    await page.getByRole("checkbox", { name: "已核对发布的有效名单，并获得业务负责人正式开启授权" }).check();
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认正式开启 / 重新开启流转（1 个）", exact: true }).click();
    await page.getByRole("heading", { name: "正式开启 / 重新开启流转 · 逐商品结果" }).waitFor();
    assert.equal(state.products[0].routing_enabled, true);
    assert.equal(state.products[1].routing_enabled, false);
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).check();
    await page.getByRole("button", { name: "关闭流转", exact: true }).click();
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认关闭商品流转（1 个）", exact: true }).click();
    await page.getByRole("heading", { name: "关闭商品流转 · 逐商品结果" }).waitFor();
    assert.equal(state.products[0].routing_enabled, false);
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).check();
    await page.getByRole("button", { name: "正式开启 / 重新开启", exact: true }).click();
    await page.getByRole("textbox", { name: "业务负责人授权依据（必填）" }).fill("重新开启的独立授权依据");
    await page.getByRole("checkbox", { name: "已核对发布的有效名单，并获得业务负责人正式开启授权" }).check();
    await page.getByRole("button", { name: "校验并预览变更", exact: true }).click();
    await page.getByRole("button", { name: "确认正式开启 / 重新开启流转（1 个）", exact: true }).click();
    await page.getByRole("heading", { name: "正式开启 / 重新开启流转 · 逐商品结果" }).waitFor();
    assert.equal(state.products[0].routing_enabled, true);
    assert.deepEqual(writes(state).map((row) => row.body.action), ["enable", "disable", "enable"]);
  });
});

test("administrator grants a product manager and publishes shared base without changing existing product versions", { timeout: 120000 }, async () => {
  await withApp({ admin: true }, async (page, state) => {
    await openProducts(page);
    await page.getByRole("button", { name: "管理授权", exact: true }).first().click();
    await page.getByRole("checkbox", { name: "商品负责人乙（manager2）", exact: true }).check();
    await page.getByRole("button", { name: "保存商品授权", exact: true }).click();
    await page.getByText("商品负责人授权已保存。", { exact: true }).waitFor();
    assert.deepEqual(state.grants, ["owner", "manager2"]);
    assert.ok(state.requests.filter((row) => row.path.endsWith("/grants") && row.method === "GET").length >= 2);
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await page.getByRole("button", { name: "精诚养车共享基座", exact: true }).click();
    await page.getByRole("spinbutton", { name: "首次跟进期限（小时）", exact: true }).fill("48");
    await page.getByRole("button", { name: "校验并预览共享基座", exact: true }).click();
    await page.getByRole("button", { name: "确认发布共享基座", exact: true }).waitFor();
    assert.equal(state.shared.rule_version_id, "BASE1");
    await page.getByRole("button", { name: "确认发布共享基座", exact: true }).click();
    await page.getByText("共享基座已发布。", { exact: false }).waitFor();
    assert.equal(state.shared.first_follow_up_sla_hours, 48);
    assert.equal(state.products[0].rule_version_id, null);
    assert.equal(state.products[0].routing_enabled, false);
  });
});

test("shared-base maintainer can publish without product grants and loses entry after revocation", { timeout: 120000 }, async () => {
  await withApp({ maintainer: true }, async (page, state) => {
    await page.goto(productRoute);
    await page.getByRole("button", { name: "精诚养车共享基座", exact: true }).waitFor();
    assert.equal(await page.getByRole("checkbox", { name: /^选择商品 / }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "共享基座维护人", exact: true }).count(), 0);
    assert.equal(await page.getByRole("button", { name: "管理授权", exact: true }).count(), 0);
    await page.getByRole("button", { name: "精诚养车共享基座", exact: true }).click();
    await page.getByRole("spinbutton", { name: "首次跟进期限（小时）", exact: true }).fill("72");
    await page.getByRole("button", { name: "校验并预览共享基座", exact: true }).click();
    await page.getByRole("button", { name: "确认发布共享基座", exact: true }).click();
    await page.getByText("共享基座已发布。", { exact: false }).waitFor();
    assert.equal(state.shared.first_follow_up_sla_hours, 72);
    assert.equal(state.products[0].first_follow_up_sla_hours, 24);
    assert.equal(state.requests.some((request) => request.path.endsWith("/grants")), false);
    await page.screenshot({ path: join(evidenceDir, "shared-base-maintainer.png") });
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    state.sharedGrants = [];
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page.getByText("当前没有可管理的匹配商品；商品负责人可联系全国范围管理员授予商品权限。", { exact: true }).first().waitFor();
    assert.equal(await page.getByRole("button", { name: "精诚养车共享基座", exact: true }).count(), 0);
  });
});

test("global administrator grants and revokes shared-base maintainers with legacy capability fallback", { timeout: 120000 }, async () => {
  await withApp({ admin: true, legacySharedCapability: true }, async (page, state) => {
    await openProducts(page);
    assert.ok(await page.getByRole("button", { name: "精诚养车共享基座", exact: true }).isVisible());
    await page.getByRole("button", { name: "共享基座维护人", exact: true }).click();
    await page.getByRole("heading", { name: "管理共享基座维护人", exact: true }).waitFor();
    const member = page.getByRole("checkbox", { name: "项目组成员乙（manager2）", exact: true });
    await member.check();
    await page.getByRole("button", { name: "保存基座维护人", exact: true }).click();
    await page.getByText("共享基座维护人授权已保存。", { exact: true }).waitFor();
    assert.deepEqual(state.sharedGrants, ["manager2"]);
    await member.uncheck();
    await page.getByRole("button", { name: "保存基座维护人", exact: true }).click();
    await page.getByText("共享基座维护人授权已保存。", { exact: true }).waitFor();
    assert.deepEqual(state.sharedGrants, []);
    const saves = state.requests.filter((request) => request.path === "/admin/clue-routing/shared-rule/grants" && request.method === "PUT");
    assert.deepEqual(saves.map((request) => request.body), [{ user_ids: ["manager2"] }, { user_ids: [] }]);
    assert.ok(state.requests.filter((request) => request.path === "/admin/clue-routing/shared-rule/grants" && request.method === "GET").length >= 3);
  });
});

test("headquarters resume confirms, presents server refusal and refreshes after successful retry", { timeout: 120000 }, async () => {
  await withApp({ admin: true }, async (page, state) => {
    await page.goto(`${baseUrl}/admin/clue-allocation/headquarters`);
    await page.getByRole("button", { name: "确认资料并续派", exact: true }).click();
    await page.getByRole("button", { name: "确认复核并续派", exact: true }).click();
    await page.getByRole("alert").filter({ hasText: "订单状态已变化，请刷新后重新确认。" }).waitFor();
    assert.equal(state.headquartersOpen, true);
    await page.getByRole("button", { name: "确认复核并续派", exact: true }).click();
    await page.getByText("已续派至门店 001002。", { exact: true }).waitFor();
    await page.getByText("总部池暂无线索", { exact: true }).first().waitFor();
    assert.equal(state.headquartersOpen, false);
    assert.ok(state.requests.filter((row) => row.path === "/admin/clue-allocation/headquarters-pool").length >= 2);
  });
});

test("filter changes reset selection; mobile dark layout remains readable; forbidden state stays explicit", { timeout: 120000 }, async () => {
  await withApp({}, async (page, state) => {
    await openProducts(page);
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).check();
    await page.getByRole("searchbox", { name: "搜索商品", exact: true }).fill("000055");
    await page.getByRole("button", { name: "查询", exact: true }).click();
    await page.getByRole("checkbox", { name: "选择商品 000055", exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "按字段批量改规则" }).isDisabled(), true);
    await page.getByRole("button", { name: "清空筛选", exact: true }).click();
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).waitFor();
    await page.screenshot({ path: join(evidenceDir, "products-desktop.png"), fullPage: false });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => localStorage.setItem("dydata.theme.preference", "dark"));
    await page.reload();
    await page.getByRole("checkbox", { name: "选择商品 000001", exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), "dark");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
    await page.screenshot({ path: join(evidenceDir, "products-mobile-dark.png"), fullPage: false });
    assert.equal(state.requests.some((row) => row.path === "/admin/clue-routing/shared-rule"), false);
  });
  await withApp({ forbidden: true }, async (page) => {
    await page.goto(productRoute);
    await page.getByRole("alert").filter({ hasText: "当前账号没有执行此操作的权限" }).waitFor();
    assert.equal(await page.getByRole("button", { name: "导入 / 发布门店名单" }).isDisabled(), true);
  });
});

test("allocation records show closed trial counts and new product strategy labels in Chinese", { timeout: 120000 }, async () => {
  await withApp({ admin: true }, async (page) => {
    await page.goto(`${baseUrl}/admin/clue-allocation/records`);
    await page.getByText("原始就近门店直派", { exact: true }).first().waitFor();
    await page.getByText("商品流转结束", { exact: true }).first().waitFor();
    await page.getByText("商品适用范围内无合格门店，线索关闭", { exact: true }).first().waitFor();
    await page.getByText("分配 1，总部池 0，关闭 2，跳过 0，失败 0", { exact: true }).first().waitFor();
    assert.ok(await page.getByText("已关闭", { exact: true }).first().isVisible());
  });
});
