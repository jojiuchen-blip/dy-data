import type { ClueRoutingBatchWrite, ClueRoutingProductListWrite, ClueRoutingResult } from "../api/clueRouting";

export function parseClueRoutingStoreIds(text: string): string[] {
  return Array.from(new Set(text.replace(/^\uFEFF/, "").split(/[\s,，;；、|]+/)
    .map((value) => value.trim()).filter((value) => value && !["store_id", "store_ids", "门店编码"].includes(value.toLowerCase()))));
}

function csvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let value = "";
  let quoted = false;
  const source = text.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === '"') {
      if (quoted && source[index + 1] === '"') { value += '"'; index += 1; }
      else quoted = !quoted;
    } else if (!quoted && (char === "," || char === "\t" || char === "，")) {
      row.push(value.trim()); value = "";
    } else if (!quoted && char === "\n") {
      row.push(value.trim());
      if (row.some(Boolean)) rows.push(row);
      row = []; value = "";
    } else value += char;
  }
  if (quoted) throw new Error("CSV_QUOTE");
  row.push(value.trim());
  if (row.some(Boolean)) rows.push(row);
  return rows;
}

export function parseClueRoutingProductLists(text: string): { lists: ClueRoutingProductListWrite[]; error: string } {
  let rows: string[][];
  try { rows = csvRows(text); }
  catch { return { lists: [], error: "名单文件的引号未闭合，请检查后重新导入。" }; }
  if (!rows.length) return { lists: [], error: "请填写或导入每个商品的门店名单。" };
  const normalizedHeader = rows[0].map((value) => value.toLowerCase().replace(/\s/g, ""));
  const productHeaders = ["product_id", "productid", "商品id", "商品编号"];
  const storeHeaders = ["store_id", "store_ids", "storeid", "门店编码"];
  const productColumn = normalizedHeader.findIndex((value) => productHeaders.includes(value));
  const storeColumn = normalizedHeader.findIndex((value) => storeHeaders.includes(value));
  const hasHeader = productColumn >= 0 || storeColumn >= 0;
  if (hasHeader && (productColumn < 0 || storeColumn < 0)) {
    return { lists: [], error: "文件表头须包含 product_id、store_id（商品 ID、门店编码）。" };
  }
  const products = new Map<string, Set<string>>();
  for (const [index, row] of rows.entries()) {
    if (index === 0 && hasHeader) continue;
    const productId = row[hasHeader ? productColumn : 0]?.trim() ?? "";
    const stores = hasHeader ? [row[storeColumn] ?? ""] : row.slice(1);
    const ids = parseClueRoutingStoreIds(stores.join(" "));
    if (!productId || !ids.length || /\s/.test(productId)) {
      return { lists: [], error: `第 ${index + 1} 行须填写一个商品 ID 和至少一个门店编码。` };
    }
    const productStores = products.get(productId) ?? new Set<string>();
    ids.forEach((id) => productStores.add(id));
    products.set(productId, productStores);
  }
  if (!products.size) return { lists: [], error: "文件只有表头，请补充商品和门店。" };
  return { lists: Array.from(products, ([product_id, storeIds]) => ({ product_id, store_ids: [...storeIds] })), error: "" };
}

/** Freeze confirmed product IDs, including after an all-filtered preview. */
export function clueRoutingBodyForResults(body: ClueRoutingBatchWrite, results: ClueRoutingResult[], status: "preview" | "failed") {
  const productIds = [...new Set(results.filter((row) => row.status === status).map((row) => row.product_id))];
  const productIdSet = new Set(productIds);
  return {
    ...body,
    product_ids: productIds,
    all_matching: false,
    ...(body.lists ? { lists: body.lists.filter((row) => productIdSet.has(row.product_id)) } : {}),
  };
}
