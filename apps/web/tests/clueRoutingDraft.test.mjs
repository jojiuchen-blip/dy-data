import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile } from "node:fs/promises";
import test from "node:test";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = await readFile(new URL("../src/utils/clueRoutingDraft.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { parseClueRoutingStoreIds, parseClueRoutingProductLists, clueRoutingBodyForResults } = await import(`data:text/javascript;base64,${Buffer.from(output).toString("base64")}`);

test("shared and per-product imports preserve leading zeros, quoted CSV values and deduplicate", () => {
  assert.deepEqual(parseClueRoutingStoreIds("\uFEFFstore_id\n001001,001002；001001\n001003"), ["001001", "001002", "001003"]);
  assert.deepEqual(parseClueRoutingProductLists('\uFEFFproduct_id,store_ids\r\n00001,"001001,001002"\r\n00001,001002\r\n00002,001003'), {
    lists: [{ product_id: "00001", store_ids: ["001001", "001002"] }, { product_id: "00002", store_ids: ["001003"] }], error: "",
  });
});

test("malformed imports never return a partial list", () => {
  for (const text of ['product_id,store_id\n0001,"001001', "product_id,wrong\n0001,001001", "product_id,store_id\n0001,001001\n0002,", "product_id,store_id"]) {
    const parsed = parseClueRoutingProductLists(text);
    assert.ok(parsed.error);
    assert.deepEqual(parsed.lists, []);
  }
});

test("confirmed scope and failure retry freeze only reviewed product IDs and their lists", () => {
  const body = { product_ids: [], all_matching: true, filters: { q: "养车", product_scope: "jingcheng" }, action: "publish_list", lists: [{ product_id: "0001", store_ids: ["001"] }, { product_id: "0002", store_ids: ["002"] }], preview: true };
  const results = [{ product_id: "0001", status: "preview" }, { product_id: "0002", status: "failed" }];
  const passed = clueRoutingBodyForResults(body, results, "preview");
  const failed = clueRoutingBodyForResults(body, results, "failed");
  assert.equal(passed.all_matching, false);
  assert.deepEqual(passed.product_ids, ["0001"]);
  assert.deepEqual(passed.lists, [{ product_id: "0001", store_ids: ["001"] }]);
  assert.deepEqual(failed.product_ids, ["0002"]);
  assert.deepEqual(failed.lists, [{ product_id: "0002", store_ids: ["002"] }]);
  assert.equal(body.all_matching, true);
  assert.equal(body.lists.length, 2);
});
