import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import as_float, config_value, path_value, product_types, sku_type_map


ORDER_CSV = path_value("base_table", env_name="BASE_TABLE")
BACKEND_CSV = path_value("backend_aweme_csv", env_name="BACKEND_AWEME_CSV")
VERIFY_JSON = path_value("may_verify_dir") / "may2026_verify_records_by_poi.json"
OUT_DIR = path_value("may_settlement_dashboard_dir")
BASE_CSV = OUT_DIR / "五月分账基础表.csv"
EXCEPTION_CSV = OUT_DIR / "五月分账异常名单.csv"
SUMMARY_JSON = OUT_DIR / "五月分账汇总.json"
DASHBOARD_HTML = OUT_DIR / "五月门店分账看板.html"

MONTH_START = datetime(2026, 5, 1)
MONTH_END = datetime(2026, 6, 1)
COMMISSION_RATE = as_float(config_value("settlement", "commission_rate", default=0.10), 0.10)
EXCLUDED_OWNER_NAMES = set(config_value("settlement", "excluded_owner_names", default=["比亚迪汽车销售有限公司"]))

SKU_TO_PRODUCT_TYPE = sku_type_map()
PRODUCT_TYPES = product_types()


def clean(value) -> str:
    return str(value or "").strip()


def to_float(value) -> float:
    text = clean(value).replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_dt(value):
    text = clean(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def safe_json(value, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def format_ts(value) -> str:
    if value in ("", None, 0, "0"):
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return clean(value)


def account_rank(row):
    status_score = 0 if clean(row.get("抖音号绑定状态")) == "认证成功" else 1
    type_score = 0 if clean(row.get("账号类型")) == "子机构门店号" else 1
    return status_score, type_score


def load_backend_maps():
    by_nick = {}
    by_store = {}
    by_poi = {}
    with BACKEND_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            nick = clean(row.get("抖音昵称"))
            store = clean(row.get("所属账户名称"))
            poi = clean(row.get("所属账户关联poi_id"))
            for key, mapping in ((nick, by_nick), (store, by_store)):
                if key and (key not in mapping or account_rank(row) < account_rank(mapping[key])):
                    mapping[key] = row
            if poi and poi != "0" and (poi not in by_poi or account_rank(row) < account_rank(by_poi[poi])):
                by_poi[poi] = row
    return by_nick, by_store, by_poi


def make_exception(reason, order_row=None, verify_row=None, detail=""):
    order_row = order_row or {}
    verify_row = verify_row or {}
    info = safe_json(order_row.get("order_sale_info"), {}) if order_row else {}
    sku = verify_row.get("sku") or {}
    return {
        "异常类型": reason,
        "订单ID": clean(order_row.get("订单ID")),
        "券ID": clean(verify_row.get("certificate_id")) or detail,
        "下单时间": clean(order_row.get("下单时间")),
        "订单状态": clean(order_row.get("订单状态")),
        "商品类型": clean(order_row.get("商品类型")),
        "SKU_ID": clean(order_row.get("SKU_ID")) or clean(sku.get("sku_id")),
        "订单归属人昵称": clean(info.get("transfer_nickName")),
        "核销门店ID": clean(verify_row.get("verify_poi_id")),
        "核销门店": clean(verify_row.get("verify_poi_name")),
        "说明": detail,
    }


def load_orders(by_nick, by_store):
    order_by_cert = {}
    sale_orders = {}
    stats = Counter()

    with ORDER_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            order_time = parse_dt(row.get("下单时间"))
            if not order_time or not (MONTH_START <= order_time < MONTH_END):
                continue
            stats["may_order_rows"] += 1

            info = safe_json(row.get("order_sale_info"), {})
            if clean(info.get("sale_role")) != "商家":
                stats["skip_non_merchant"] += 1
                continue
            if clean(row.get("订单状态")) == "支付取消":
                stats["skip_payment_cancel"] += 1
                continue

            owner = clean(info.get("transfer_nickName"))
            if owner in EXCLUDED_OWNER_NAMES:
                stats["skip_excluded_owner"] += 1
                continue

            owner_hit = by_nick.get(owner) or by_store.get(owner)
            if not owner_hit:
                stats["skip_owner_not_matched"] += 1
                continue

            sale_store_id = clean(owner_hit.get("所属账户关联poi_id"))
            sale_store_name = clean(owner_hit.get("所属账户名称"))
            if not sale_store_id or sale_store_id == "0" or not sale_store_name:
                stats["skip_sales_store_missing"] += 1
                continue

            certs = safe_json(row.get("certificate"), [])
            valid_certs = [
                cert for cert in certs
                if clean(cert.get("certificate_id")) and int(cert.get("refund_amount") or 0) <= 0
            ]
            if not valid_certs:
                stats["skip_no_valid_cert_or_refund"] += 1
                continue

            sku_id = clean(row.get("SKU_ID"))
            product_type = SKU_TO_PRODUCT_TYPE.get(sku_id)
            if product_type not in PRODUCT_TYPES:
                stats["skip_product_type_not_configured"] += 1
                continue

            order_id = clean(row.get("订单ID"))
            order_amount = to_float(row.get("到账金额")) or to_float(row.get("实付金额"))
            per_cert_amount = order_amount / max(len(valid_certs), 1)
            sale_orders[order_id] = {
                "订单ID": order_id,
                "销售门店ID": sale_store_id,
                "销售门店": sale_store_name,
                "商品类型": product_type,
                "订单实收金额": order_amount,
            }
            for cert in valid_certs:
                cert_id = clean(cert.get("certificate_id"))
                order_by_cert[cert_id] = {
                    "订单ID": order_id,
                    "券ID": cert_id,
                    "下单时间": clean(row.get("下单时间")),
                    "订单状态": clean(row.get("订单状态")),
                    "商品类型": product_type,
                    "SKU_ID": sku_id,
                    "SKU名称": clean(row.get("SKU名称")),
                    "订单实收金额": per_cert_amount,
                    "订单归属人昵称": owner,
                    "销售门店ID": sale_store_id,
                    "销售门店": sale_store_name,
                    "销售认证主体": clean(owner_hit.get("认证主体")),
                }
            stats["eligible_order_rows"] += 1
    return order_by_cert, sale_orders, stats


def load_valid_verify_records(by_poi):
    raw_rows = json.loads(VERIFY_JSON.read_text(encoding="utf-8"))
    stats = Counter({
        "verify_records_raw": len(raw_rows),
        "verify_unique_certificate_raw": len({clean(r.get("certificate_id")) for r in raw_rows if clean(r.get("certificate_id"))}),
    })
    latest_by_cert = {}
    exceptions = []

    for row in raw_rows:
        cert_id = clean(row.get("certificate_id"))
        if not cert_id:
            continue
        status = clean(row.get("status"))
        cancel_time = clean(row.get("cancel_time"))
        if status != "1" or cancel_time not in ("", "0"):
            stats["skip_verify_invalid_status"] += 1
            exceptions.append(make_exception("核销状态非有效", verify_row=row, detail=f"status={status}, cancel_time={cancel_time}"))
            continue

        poi_id = clean(row.get("verify_poi_id"))
        poi_hit = by_poi.get(poi_id)
        if not poi_hit:
            stats["skip_verify_poi_not_matched"] += 1
            continue

        current = latest_by_cert.get(cert_id)
        if current is None or int(row.get("verify_time") or 0) >= int(current.get("verify_time") or 0):
            latest_by_cert[cert_id] = row

    stats["verify_duplicate_certificate_removed"] = stats["verify_records_raw"] - stats["verify_unique_certificate_raw"]
    stats["verify_valid_unique_certificate"] = len(latest_by_cert)

    records = []
    for row in latest_by_cert.values():
        poi_id = clean(row.get("verify_poi_id"))
        poi_hit = by_poi.get(poi_id) or {}
        sku = row.get("sku") or {}
        records.append({
            "券ID": clean(row.get("certificate_id")),
            "核销ID": clean(row.get("verify_id")),
            "核销时间": format_ts(row.get("verify_time")),
            "核销门店ID": poi_id,
            "核销门店": clean(poi_hit.get("所属账户名称")) or clean(row.get("verify_poi_name")),
            "核销认证主体": clean(poi_hit.get("认证主体")),
            "核销状态": clean(row.get("status")),
            "核销类型": clean(row.get("verify_type")),
            "核销SKU_ID": clean(sku.get("sku_id")),
            "核销商品名称": clean(sku.get("title")),
        })
    return records, exceptions, stats


def build_settlement_rows(order_by_cert, verify_rows, exceptions, stats):
    rows = []
    for verify in verify_rows:
        order = order_by_cert.get(verify["券ID"])
        if not order:
            stats["verify_cert_not_matched_order"] += 1
            exceptions.append(make_exception("核销券未匹配订单", verify_row={"certificate_id": verify["券ID"], "verify_poi_id": verify["核销门店ID"], "verify_poi_name": verify["核销门店"]}, detail=verify["券ID"]))
            continue
        relation = "本店自销自核" if order["销售门店ID"] == verify["核销门店ID"] else "跨店核销"
        row = dict(order)
        row.update(verify)
        row["销售核销关系"] = relation
        row["分佣比例"] = COMMISSION_RATE
        row["分佣金额"] = round(row["订单实收金额"] * COMMISSION_RATE, 2)
        rows.append(row)
    stats["settlement_records"] = len(rows)
    stats["cross_store_records"] = sum(1 for row in rows if row["销售核销关系"] == "跨店核销")
    stats["same_store_records"] = sum(1 for row in rows if row["销售核销关系"] == "本店自销自核")
    return rows


def compact_product(product_map):
    result = []
    for product in PRODUCT_TYPES:
        item = product_map.get(product)
        result.append({
            "商品类型": product,
            "单数": len(item["orders"]) if item else 0,
            "订单实收金额": round(item["amount"], 2) if item else 0.0,
            "分佣金额": round(item["commission"], 2) if item else 0.0,
        })
    return result


def blank_store(store):
    return {
        "store": store,
        "sold_orders": set(),
        "sold_amount": 0.0,
        "receive_orders": set(),
        "receive_amount": 0.0,
        "receive_commission": 0.0,
        "pay_orders": set(),
        "pay_amount": 0.0,
        "pay_commission": 0.0,
        "product_receive": defaultdict(lambda: {"orders": set(), "amount": 0.0, "commission": 0.0}),
        "product_pay": defaultdict(lambda: {"orders": set(), "amount": 0.0, "commission": 0.0}),
    }


def summarize(rows, sale_orders, exceptions, stats):
    stores = {}
    for order in sale_orders.values():
        store = order["销售门店"]
        stores.setdefault(store, blank_store(store))
        stores[store]["sold_orders"].add(order["订单ID"])
        stores[store]["sold_amount"] += order["订单实收金额"]

    for row in rows:
        if row["销售核销关系"] != "跨店核销":
            continue
        sale_store = row["销售门店"]
        verify_store = row["核销门店"]
        stores.setdefault(sale_store, blank_store(sale_store))
        stores.setdefault(verify_store, blank_store(verify_store))

        stores[sale_store]["receive_orders"].add(row["订单ID"])
        stores[sale_store]["receive_amount"] += row["订单实收金额"]
        stores[sale_store]["receive_commission"] += row["分佣金额"]
        stores[sale_store]["product_receive"][row["商品类型"]]["orders"].add(row["订单ID"])
        stores[sale_store]["product_receive"][row["商品类型"]]["amount"] += row["订单实收金额"]
        stores[sale_store]["product_receive"][row["商品类型"]]["commission"] += row["分佣金额"]

        stores[verify_store]["pay_orders"].add(row["订单ID"])
        stores[verify_store]["pay_amount"] += row["订单实收金额"]
        stores[verify_store]["pay_commission"] += row["分佣金额"]
        stores[verify_store]["product_pay"][row["商品类型"]]["orders"].add(row["订单ID"])
        stores[verify_store]["product_pay"][row["商品类型"]]["amount"] += row["订单实收金额"]
        stores[verify_store]["product_pay"][row["商品类型"]]["commission"] += row["分佣金额"]

    store_rows = []
    for store, item in stores.items():
        store_rows.append({
            "store": store,
            "sold_orders": len(item["sold_orders"]),
            "sold_amount": round(item["sold_amount"], 2),
            "receive_orders": len(item["receive_orders"]),
            "receive_amount": round(item["receive_amount"], 2),
            "receive_commission": round(item["receive_commission"], 2),
            "pay_orders": len(item["pay_orders"]),
            "pay_amount": round(item["pay_amount"], 2),
            "pay_commission": round(item["pay_commission"], 2),
            "net_commission": round(item["receive_commission"] - item["pay_commission"], 2),
            "product_receive": compact_product(item["product_receive"]),
            "product_pay": compact_product(item["product_pay"]),
        })
    store_rows.sort(key=lambda row: abs(row["net_commission"]), reverse=True)
    totals = {
        "settlement_records": stats["settlement_records"],
        "cross_store_records": stats["cross_store_records"],
        "same_store_records": stats["same_store_records"],
        "cross_store_amount": round(sum(row["订单实收金额"] for row in rows if row["销售核销关系"] == "跨店核销"), 2),
        "cross_store_commission": round(sum(row["分佣金额"] for row in rows if row["销售核销关系"] == "跨店核销"), 2),
        "exception_count": len(exceptions),
    }
    return {
        "totals": totals,
        "stats": dict(stats),
        "stores": store_rows,
    }


def detail_row(row, commission_label):
    return {
        "订单ID": row["订单ID"],
        "券ID": row["券ID"],
        "下单时间": row["下单时间"],
        "核销时间": row["核销时间"],
        "商品类型": row["商品类型"],
        "SKU名称": row["SKU名称"],
        "订单实收金额": round(row["订单实收金额"], 2),
        "销售门店": row["销售门店"],
        "核销门店": row["核销门店"],
        "分佣比例": "10%",
        "分佣金额": round(row["分佣金额"], 2),
        commission_label: round(row["分佣金额"], 2),
    }


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def render_dashboard(summary, settlement_rows):
    data = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "month": "2026-05",
        "summary": summary,
        "details": {
            "receive": [detail_row(row, "应收分佣金额") for row in settlement_rows if row["销售核销关系"] == "跨店核销"],
            "pay": [detail_row(row, "应扣分佣金额") for row in settlement_rows if row["销售核销关系"] == "跨店核销"],
        },
    }
    payload = json.dumps(data, ensure_ascii=False)
    products = json.dumps(PRODUCT_TYPES, ensure_ascii=False)
    DASHBOARD_HTML.write_text(f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>五月门店分账看板</title>
<style>
:root{{--bg:#f4f7f5;--card:#fff;--ink:#14231d;--muted:#66736d;--line:#d9e3de;--green:#12664f;--red:#b54a3f;}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(135deg,#eef4ef,#f8f1e5);color:var(--ink);font-family:"Microsoft YaHei","Segoe UI",sans-serif}}
.wrap{{max-width:1440px;margin:0 auto;padding:28px}} .hero{{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:20px}}
h1{{margin:0;font-size:32px}} .sub{{color:var(--muted);margin-top:8px}} .filters{{display:flex;gap:12px;flex-wrap:wrap;background:rgba(255,255,255,.75);border:1px solid var(--line);padding:14px;border-radius:18px}}
select,input{{height:38px;border:1px solid var(--line);border-radius:10px;padding:0 12px;background:#fff;min-width:230px}}
.cards{{display:grid;grid-template-columns:repeat(7,1fr);gap:12px;margin:18px 0}} .card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 8px 22px rgba(20,35,29,.06)}}
.label{{color:var(--muted);font-size:13px}} .value{{font-size:25px;font-weight:800;margin-top:8px}} .pos{{color:var(--green);font-weight:800}} .neg{{color:var(--red);font-weight:800}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .panel{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 8px 22px rgba(20,35,29,.06)}}
h2{{margin:0 0 14px;font-size:20px}} table{{width:100%;border-collapse:collapse;font-size:13px}} th{{text-align:left;border-bottom:2px solid var(--line);padding:10px 8px;font-weight:800;background:#f7faf8;position:sticky;top:0}} td{{border-bottom:1px solid #eef2f0;padding:9px 8px;vertical-align:top}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .details{{margin-top:16px;display:grid;grid-template-columns:1fr;gap:16px}} .table-scroll{{max-height:440px;overflow:auto;border:1px solid var(--line);border-radius:12px}} .pill{{display:inline-block;padding:3px 8px;border-radius:999px;background:#e9f3ee;color:var(--green);font-weight:700}}
@media(max-width:1100px){{.cards{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div><h1>五月门店分账看板</h1><div class="sub">只统计已匹配到抖音号明细的门店；销售归属为“比亚迪汽车销售有限公司”的订单已排除。生成时间：<span id="generatedAt"></span></div></div>
    <div class="filters"><select id="storeFilter"></select><select id="productFilter"></select><input id="searchBox" placeholder="搜索门店 / 订单ID / 券ID"></div>
  </div>
  <div class="cards" id="cards"></div>
  <div class="grid"><section class="panel"><h2>本店卖出，他店核销</h2><div id="receiveTable"></div></section><section class="panel"><h2>他店卖出，本店核销</h2><div id="payTable"></div></section></div>
  <div class="details"><section class="panel"><h2>门店净分佣排行</h2><div class="table-scroll"><table id="storeRank"></table></div></section><section class="panel"><h2>本店卖他店核销明细</h2><div class="table-scroll"><table id="receiveDetail"></table></div></section><section class="panel"><h2>他店卖本店核销明细</h2><div class="table-scroll"><table id="payDetail"></table></div></section></div>
</div>
<script>
const DATA={payload};
const PRODUCTS={products};
const storeFilter=document.getElementById('storeFilter'), productFilter=document.getElementById('productFilter'), searchBox=document.getElementById('searchBox');
document.getElementById('generatedAt').textContent=DATA.generatedAt;
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));
const money=v=>Number(v||0).toLocaleString('zh-CN',{{minimumFractionDigits:2,maximumFractionDigits:2}});
const intn=v=>Number(v||0).toLocaleString('zh-CN');
storeFilter.innerHTML='<option value="">全部门店</option>'+DATA.summary.stores.map(s=>`<option>${{esc(s.store)}}</option>`).join('');
productFilter.innerHTML='<option value="">全部商品类型</option>'+PRODUCTS.map(p=>`<option>${{p}}</option>`).join('');
function currentStore(){{return storeFilter.value}} function currentProduct(){{return productFilter.value}}
function selectedStoreSummary(){{
  const store=currentStore();
  if(store) return DATA.summary.stores.find(s=>s.store===store)||{{}};
  return {{
    sold_orders:DATA.summary.stores.reduce((a,s)=>a+s.sold_orders,0),
    sold_amount:DATA.summary.stores.reduce((a,s)=>a+s.sold_amount,0),
    receive_orders:DATA.summary.stores.reduce((a,s)=>a+s.receive_orders,0),
    receive_amount:DATA.summary.stores.reduce((a,s)=>a+s.receive_amount,0),
    receive_commission:DATA.summary.stores.reduce((a,s)=>a+s.receive_commission,0),
    pay_orders:DATA.summary.stores.reduce((a,s)=>a+s.pay_orders,0),
    pay_amount:DATA.summary.stores.reduce((a,s)=>a+s.pay_amount,0),
    pay_commission:DATA.summary.stores.reduce((a,s)=>a+s.pay_commission,0),
    net_commission:DATA.summary.stores.reduce((a,s)=>a+s.net_commission,0)
  }};
}}
function aggregateProduct(mode,product){{
  const rows=DATA.details[mode].filter(r=>(!currentStore()||(mode==='receive'?r['销售门店']===currentStore():r['核销门店']===currentStore()))&&r['商品类型']===product);
  return {{商品类型:product,单数:new Set(rows.map(r=>r['订单ID'])).size,订单实收金额:rows.reduce((a,r)=>a+Number(r['订单实收金额']||0),0),分佣金额:rows.reduce((a,r)=>a+Number(r['分佣金额']||0),0)}};
}}
function productTable(rows,label){{return `<table><thead><tr><th>商品类型</th><th class="num">单数</th><th class="num">订单实收金额</th><th class="num">分佣比例</th><th class="num">${{label}}</th></tr></thead><tbody>`+rows.filter(r=>!currentProduct()||r['商品类型']===currentProduct()).map(r=>`<tr><td><span class="pill">${{r['商品类型']}}</span></td><td class="num">${{intn(r['单数'])}}</td><td class="num">¥${{money(r['订单实收金额'])}}</td><td class="num">10%</td><td class="num">¥${{money(r['分佣金额'])}}</td></tr>`).join('')+`</tbody></table>`}}
function renderCards(){{const s=selectedStoreSummary(); const cards=[['有效销售单数',intn(s.sold_orders)],['有效销售实收','¥'+money(s.sold_amount)],['本店卖他店核销',intn(s.receive_orders)],['应收分佣','¥'+money(s.receive_commission),'pos'],['他店卖本店核销',intn(s.pay_orders)],['应扣分佣','¥'+money(s.pay_commission),'neg'],['净分佣','¥'+money(s.net_commission),Number(s.net_commission)>=0?'pos':'neg']]; document.getElementById('cards').innerHTML=cards.map(c=>`<div class="card"><div class="label">${{c[0]}}</div><div class="value ${{c[2]||''}}">${{c[1]}}</div></div>`).join('')}}
function renderProductTables(){{const store=currentStore(); let s=DATA.summary.stores.find(x=>x.store===store); if(!s) s={{product_receive:PRODUCTS.map(p=>aggregateProduct('receive',p)),product_pay:PRODUCTS.map(p=>aggregateProduct('pay',p))}}; document.getElementById('receiveTable').innerHTML=productTable(s.product_receive,'应收分佣'); document.getElementById('payTable').innerHTML=productTable(s.product_pay,'应扣分佣')}}
function renderRank(){{const rows=DATA.summary.stores.filter(s=>!currentStore()||s.store===currentStore()).slice(0,200); document.getElementById('storeRank').innerHTML=`<thead><tr><th>门店</th><th class="num">有效销售单数</th><th class="num">应收分佣</th><th class="num">应扣分佣</th><th class="num">净分佣</th></tr></thead><tbody>`+rows.map(s=>`<tr><td>${{esc(s.store)}}</td><td class="num">${{intn(s.sold_orders)}}</td><td class="num pos">¥${{money(s.receive_commission)}}</td><td class="num neg">¥${{money(s.pay_commission)}}</td><td class="num ${{s.net_commission>=0?'pos':'neg'}}">¥${{money(s.net_commission)}}</td></tr>`).join('')+`</tbody>`}}
function keep(row,mode){{const q=searchBox.value.trim(); if(currentProduct()&&row['商品类型']!==currentProduct())return false; if(currentStore()&&(mode==='receive'?row['销售门店']!==currentStore():row['核销门店']!==currentStore()))return false; return !q||JSON.stringify(row).includes(q)}}
function renderDetailTable(id,rows,label){{const cols=['订单ID','券ID','下单时间','核销时间','商品类型','SKU名称','订单实收金额','销售门店','核销门店','分佣比例',label]; document.getElementById(id).innerHTML=`<thead><tr>${{cols.map(c=>`<th>${{c}}</th>`).join('')}}</tr></thead><tbody>`+rows.map(r=>`<tr>${{cols.map(c=>`<td class="${{['订单实收金额',label].includes(c)?'num':''}}">${{['订单实收金额',label].includes(c)?'¥'+money(r[c]):esc(r[c])}}</td>`).join('')}}</tr>`).join('')+`</tbody>`}}
function renderDetails(){{renderDetailTable('receiveDetail',DATA.details.receive.filter(r=>keep(r,'receive')).slice(0,500),'应收分佣金额'); renderDetailTable('payDetail',DATA.details.pay.filter(r=>keep(r,'pay')).slice(0,500),'应扣分佣金额')}}
function render(){{renderCards();renderProductTables();renderRank();renderDetails()}}
storeFilter.onchange=render; productFilter.onchange=render; searchBox.oninput=render; render();
</script>
</body>
</html>""", encoding="utf-8")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_nick, by_store, by_poi = load_backend_maps()
    order_by_cert, sale_orders, order_stats = load_orders(by_nick, by_store)
    verify_rows, exceptions, verify_stats = load_valid_verify_records(by_poi)
    stats = Counter()
    stats.update(order_stats)
    stats.update(verify_stats)
    settlement_rows = build_settlement_rows(order_by_cert, verify_rows, exceptions, stats)
    summary = summarize(settlement_rows, sale_orders, exceptions, stats)

    base_fields = [
        "订单ID", "券ID", "下单时间", "核销时间", "订单状态", "商品类型", "SKU_ID", "SKU名称",
        "订单实收金额", "订单归属人昵称", "销售门店ID", "销售门店", "销售认证主体",
        "核销门店ID", "核销门店", "核销认证主体", "核销ID", "核销状态", "核销类型",
        "销售核销关系", "分佣比例", "分佣金额",
    ]
    exception_fields = ["异常类型", "订单ID", "券ID", "下单时间", "订单状态", "商品类型", "SKU_ID", "订单归属人昵称", "核销门店ID", "核销门店", "说明"]
    write_csv(BASE_CSV, settlement_rows, base_fields)
    write_csv(EXCEPTION_CSV, exceptions, exception_fields)
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    render_dashboard(summary, settlement_rows)

    print(json.dumps({
        "base_csv": str(BASE_CSV),
        "exception_csv": str(EXCEPTION_CSV),
        "summary_json": str(SUMMARY_JSON),
        "dashboard_html": str(DASHBOARD_HTML),
        **summary["totals"],
        "stats": summary["stats"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
