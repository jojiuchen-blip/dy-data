import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from src.dy_data.config import path_value, product_types


OUT_DIR = path_value("may_settlement_dashboard_dir")
SOURCE_FILES = [
    OUT_DIR / "五月分账基础表.csv",
]
OUT_HTML = OUT_DIR / "五月门店分账看板.html"

PRODUCT_TYPES = product_types()


def clean(value):
    return str(value or "").strip()


def to_float(value):
    try:
        return float(clean(value).replace(",", ""))
    except Exception:
        return 0.0


def parse_month(value):
    text = clean(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return "未知月份"


def read_rows():
    rows = []
    for path in SOURCE_FILES:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                row["核销月份"] = parse_month(row.get("核销时间"))
                row["订单实收金额"] = round(to_float(row.get("订单实收金额")), 2)
                row["分佣金额"] = round(to_float(row.get("分佣金额")), 2)
                rows.append(row)
    return rows


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


def compact_products(product_map):
    result = []
    for product in PRODUCT_TYPES:
        item = product_map.get(product)
        result.append({
            "商品类型": product,
            "单数": len(item["orders"]) if item else 0,
            "订单实收金额": round(item["amount"], 2) if item else 0,
            "分佣金额": round(item["commission"], 2) if item else 0,
        })
    return result


def summarize_month(rows):
    stores = {}
    sale_orders_seen = set()
    for row in rows:
        sale_store = clean(row.get("销售门店"))
        verify_store = clean(row.get("核销门店"))
        order_id = clean(row.get("订单ID"))
        product = clean(row.get("商品类型"))
        amount = to_float(row.get("订单实收金额"))
        commission = to_float(row.get("分佣金额"))
        relation = clean(row.get("销售核销关系"))

        if sale_store:
            stores.setdefault(sale_store, blank_store(sale_store))
            sale_key = (sale_store, order_id)
            if sale_key not in sale_orders_seen:
                stores[sale_store]["sold_orders"].add(order_id)
                stores[sale_store]["sold_amount"] += amount
                sale_orders_seen.add(sale_key)

        if relation != "跨店核销":
            continue

        stores.setdefault(sale_store, blank_store(sale_store))
        stores.setdefault(verify_store, blank_store(verify_store))

        stores[sale_store]["receive_orders"].add(order_id)
        stores[sale_store]["receive_amount"] += amount
        stores[sale_store]["receive_commission"] += commission
        stores[sale_store]["product_receive"][product]["orders"].add(order_id)
        stores[sale_store]["product_receive"][product]["amount"] += amount
        stores[sale_store]["product_receive"][product]["commission"] += commission

        stores[verify_store]["pay_orders"].add(order_id)
        stores[verify_store]["pay_amount"] += amount
        stores[verify_store]["pay_commission"] += commission
        stores[verify_store]["product_pay"][product]["orders"].add(order_id)
        stores[verify_store]["product_pay"][product]["amount"] += amount
        stores[verify_store]["product_pay"][product]["commission"] += commission

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
            "product_receive": compact_products(item["product_receive"]),
            "product_pay": compact_products(item["product_pay"]),
        })
    store_rows.sort(key=lambda row: abs(row["net_commission"]), reverse=True)

    cross_rows = [row for row in rows if clean(row.get("销售核销关系")) == "跨店核销"]
    return {
        "totals": {
            "settlement_records": len(rows),
            "cross_store_records": len(cross_rows),
            "same_store_records": len(rows) - len(cross_rows),
            "cross_store_amount": round(sum(to_float(row.get("订单实收金额")) for row in cross_rows), 2),
            "cross_store_commission": round(sum(to_float(row.get("分佣金额")) for row in cross_rows), 2),
        },
        "stores": store_rows,
        "details": {
            "receive": [detail_row(row, "应收分佣金额") for row in cross_rows],
            "pay": [detail_row(row, "应扣分佣金额") for row in cross_rows],
        },
    }


def detail_row(row, commission_label):
    return {
        "订单ID": clean(row.get("订单ID")),
        "券ID": clean(row.get("券ID")),
        "下单时间": clean(row.get("下单时间")),
        "核销时间": clean(row.get("核销时间")),
        "商品类型": clean(row.get("商品类型")),
        "SKU名称": clean(row.get("SKU名称")),
        "订单实收金额": to_float(row.get("订单实收金额")),
        "销售门店": clean(row.get("销售门店")),
        "核销门店": clean(row.get("核销门店")),
        "分佣比例": "10%",
        "分佣金额": to_float(row.get("分佣金额")),
        commission_label: to_float(row.get("分佣金额")),
    }


def build_payload(rows):
    by_month = defaultdict(list)
    for row in rows:
        by_month[row["核销月份"]].append(row)
    months = sorted(by_month.keys(), reverse=True)
    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "months": months,
        "defaultMonth": months[0] if months else "",
        "byMonth": {month: summarize_month(month_rows) for month, month_rows in by_month.items()},
    }


def render(payload):
    data = json.dumps(payload, ensure_ascii=False)
    products = json.dumps(PRODUCT_TYPES, ensure_ascii=False)
    OUT_HTML.write_text(f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>门店分账看板</title>
<style>
:root{{--card:#fff;--ink:#14231d;--muted:#66736d;--line:#d9e3de;--green:#12664f;--red:#b54a3f}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(135deg,#eef4ef,#f8f1e5);color:var(--ink);font-family:"Microsoft YaHei","Segoe UI",sans-serif}}
.wrap{{max-width:1440px;margin:0 auto;padding:28px}} .hero{{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:20px}}
h1{{margin:0;font-size:32px}} .sub{{color:var(--muted);margin-top:8px}} .filters{{display:flex;gap:12px;flex-wrap:wrap;background:rgba(255,255,255,.78);border:1px solid var(--line);padding:14px;border-radius:18px}}
select,input{{height:38px;border:1px solid var(--line);border-radius:10px;padding:0 12px;background:white;min-width:210px}}
.cards{{display:grid;grid-template-columns:repeat(7,1fr);gap:12px;margin:18px 0}} .card,.panel{{background:var(--card);border:1px solid var(--line);box-shadow:0 8px 22px rgba(20,35,29,.06)}}
.card{{border-radius:16px;padding:16px}} .label{{color:var(--muted);font-size:13px}} .value{{font-size:25px;font-weight:800;margin-top:8px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .panel{{border-radius:18px;padding:18px}} h2{{margin:0 0 14px;font-size:20px}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th{{text-align:left;border-bottom:2px solid var(--line);padding:10px 8px;font-weight:800;background:#f7faf8;position:sticky;top:0}} td{{border-bottom:1px solid #eef2f0;padding:9px 8px;vertical-align:top}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .pos{{color:var(--green);font-weight:800}} .neg{{color:var(--red);font-weight:800}}
.details{{margin-top:16px;display:grid;grid-template-columns:1fr;gap:16px}} .table-scroll{{max-height:440px;overflow:auto;border:1px solid var(--line);border-radius:12px}} .pill{{display:inline-block;padding:3px 8px;border-radius:999px;background:#e9f3ee;color:var(--green);font-weight:700}}
@media(max-width:1100px){{.cards{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div><h1>门店分账看板</h1><div class="sub">按核销月份展示；当前只包含已拉取月份的数据。生成时间：<span id="generatedAt"></span></div></div>
    <div class="filters"><select id="monthFilter"></select><select id="storeFilter"></select><select id="productFilter"></select><input id="searchBox" placeholder="搜索门店 / 订单ID / 券ID"></div>
  </div>
  <div class="cards" id="cards"></div>
  <div class="grid"><section class="panel"><h2>本店卖出，他店核销</h2><div id="receiveTable"></div></section><section class="panel"><h2>他店卖出，本店核销</h2><div id="payTable"></div></section></div>
  <div class="details"><section class="panel"><h2>门店净分佣排行</h2><div class="table-scroll"><table id="storeRank"></table></div></section><section class="panel"><h2>本店卖他店核销明细</h2><div class="table-scroll"><table id="receiveDetail"></table></div></section><section class="panel"><h2>他店卖本店核销明细</h2><div class="table-scroll"><table id="payDetail"></table></div></section></div>
</div>
<script>
const DATA={data}, PRODUCTS={products};
const monthFilter=document.getElementById('monthFilter'), storeFilter=document.getElementById('storeFilter'), productFilter=document.getElementById('productFilter'), searchBox=document.getElementById('searchBox');
document.getElementById('generatedAt').textContent=DATA.generatedAt;
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));
const money=v=>Number(v||0).toLocaleString('zh-CN',{{minimumFractionDigits:2,maximumFractionDigits:2}});
const intn=v=>Number(v||0).toLocaleString('zh-CN');
monthFilter.innerHTML=DATA.months.map(m=>`<option value="${{m}}">${{m}}</option>`).join('');
monthFilter.value=DATA.defaultMonth;
productFilter.innerHTML='<option value="">全部商品类型</option>'+PRODUCTS.map(p=>`<option>${{p}}</option>`).join('');
function monthData(){{return DATA.byMonth[monthFilter.value]||{{stores:[],details:{{receive:[],pay:[]}},totals:{{}}}}}}
function refreshStores(){{const keep=storeFilter.value; storeFilter.innerHTML='<option value="">全部门店</option>'+monthData().stores.map(s=>`<option>${{esc(s.store)}}</option>`).join(''); if([...storeFilter.options].some(o=>o.value===keep)) storeFilter.value=keep}}
function currentStore(){{return storeFilter.value}} function currentProduct(){{return productFilter.value}}
function selectedStoreSummary(){{const d=monthData(), store=currentStore(); if(store) return d.stores.find(s=>s.store===store)||{{}}; return {{sold_orders:d.stores.reduce((a,s)=>a+s.sold_orders,0),sold_amount:d.stores.reduce((a,s)=>a+s.sold_amount,0),receive_orders:d.stores.reduce((a,s)=>a+s.receive_orders,0),receive_amount:d.stores.reduce((a,s)=>a+s.receive_amount,0),receive_commission:d.stores.reduce((a,s)=>a+s.receive_commission,0),pay_orders:d.stores.reduce((a,s)=>a+s.pay_orders,0),pay_amount:d.stores.reduce((a,s)=>a+s.pay_amount,0),pay_commission:d.stores.reduce((a,s)=>a+s.pay_commission,0),net_commission:d.stores.reduce((a,s)=>a+s.net_commission,0)}}}}
function aggregateProduct(mode,product){{const rows=monthData().details[mode].filter(r=>(!currentStore()||(mode==='receive'?r['销售门店']===currentStore():r['核销门店']===currentStore()))&&r['商品类型']===product); return {{商品类型:product,单数:new Set(rows.map(r=>r['订单ID'])).size,订单实收金额:rows.reduce((a,r)=>a+Number(r['订单实收金额']||0),0),分佣金额:rows.reduce((a,r)=>a+Number(r['分佣金额']||0),0)}}}}
function productTable(rows,label){{return `<table><thead><tr><th>商品类型</th><th class="num">单数</th><th class="num">订单实收金额</th><th class="num">分佣比例</th><th class="num">${{label}}</th></tr></thead><tbody>`+rows.filter(r=>!currentProduct()||r['商品类型']===currentProduct()).map(r=>`<tr><td><span class="pill">${{r['商品类型']}}</span></td><td class="num">${{intn(r['单数'])}}</td><td class="num">¥${{money(r['订单实收金额'])}}</td><td class="num">10%</td><td class="num">¥${{money(r['分佣金额'])}}</td></tr>`).join('')+`</tbody></table>`}}
function renderCards(){{const s=selectedStoreSummary(); const cards=[['有效销售单数',intn(s.sold_orders)],['有效销售实收','¥'+money(s.sold_amount)],['本店卖他店核销',intn(s.receive_orders)],['应收分佣','¥'+money(s.receive_commission),'pos'],['他店卖本店核销',intn(s.pay_orders)],['应扣分佣','¥'+money(s.pay_commission),'neg'],['净分佣','¥'+money(s.net_commission),Number(s.net_commission)>=0?'pos':'neg']]; document.getElementById('cards').innerHTML=cards.map(c=>`<div class="card"><div class="label">${{c[0]}}</div><div class="value ${{c[2]||''}}">${{c[1]}}</div></div>`).join('')}}
function renderProductTables(){{const s=monthData().stores.find(x=>x.store===currentStore())||{{product_receive:PRODUCTS.map(p=>aggregateProduct('receive',p)),product_pay:PRODUCTS.map(p=>aggregateProduct('pay',p))}}; document.getElementById('receiveTable').innerHTML=productTable(s.product_receive,'应收分佣'); document.getElementById('payTable').innerHTML=productTable(s.product_pay,'应扣分佣')}}
function renderRank(){{const rows=monthData().stores.filter(s=>!currentStore()||s.store===currentStore()).slice(0,200); document.getElementById('storeRank').innerHTML=`<thead><tr><th>门店</th><th class="num">有效销售单数</th><th class="num">应收分佣</th><th class="num">应扣分佣</th><th class="num">净分佣</th></tr></thead><tbody>`+rows.map(s=>`<tr><td>${{esc(s.store)}}</td><td class="num">${{intn(s.sold_orders)}}</td><td class="num pos">¥${{money(s.receive_commission)}}</td><td class="num neg">¥${{money(s.pay_commission)}}</td><td class="num ${{s.net_commission>=0?'pos':'neg'}}">¥${{money(s.net_commission)}}</td></tr>`).join('')+`</tbody>`}}
function keep(row,mode){{const q=searchBox.value.trim(); if(currentProduct()&&row['商品类型']!==currentProduct())return false; if(currentStore()&&(mode==='receive'?row['销售门店']!==currentStore():row['核销门店']!==currentStore()))return false; return !q||JSON.stringify(row).includes(q)}}
function detail(id,rows,label){{const cols=['订单ID','券ID','下单时间','核销时间','商品类型','SKU名称','订单实收金额','销售门店','核销门店','分佣比例',label]; document.getElementById(id).innerHTML=`<thead><tr>${{cols.map(c=>`<th>${{c}}</th>`).join('')}}</tr></thead><tbody>`+rows.map(r=>`<tr>${{cols.map(c=>`<td class="${{['订单实收金额',label].includes(c)?'num':''}}">${{['订单实收金额',label].includes(c)?'¥'+money(r[c]):esc(r[c])}}</td>`).join('')}}</tr>`).join('')+`</tbody>`}}
function renderDetails(){{detail('receiveDetail',monthData().details.receive.filter(r=>keep(r,'receive')).slice(0,500),'应收分佣金额'); detail('payDetail',monthData().details.pay.filter(r=>keep(r,'pay')).slice(0,500),'应扣分佣金额')}}
function render(){{refreshStores(); renderCards(); renderProductTables(); renderRank(); renderDetails()}}
monthFilter.onchange=()=>{{storeFilter.value=''; render()}}; storeFilter.onchange=render; productFilter.onchange=render; searchBox.oninput=render; render();
</script>
</body>
</html>""", encoding="utf-8")


def main():
    rows = read_rows()
    payload = build_payload(rows)
    render(payload)
    print(json.dumps({
        "dashboard_html": str(OUT_HTML),
        "months": payload["months"],
        "default_month": payload["defaultMonth"],
        "rows": len(rows),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
