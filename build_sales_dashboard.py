import csv
import html as html_lib
import json
from datetime import date, datetime
from pathlib import Path

from src.dy_data.config import config_value, path_value


BASE_CSV = path_value("base_table", env_name="BASE_TABLE")
OUTPUT_DIR = path_value("dashboard_dir")
OUTPUT_HTML = OUTPUT_DIR / "精诚养车服务产品销售数据看板.html"
INDEX_HTML = OUTPUT_DIR / "index.html"
INDEX_HTML_HTML = OUTPUT_DIR / "index.html.html"
LEGACY_DASHBOARD_HTML = OUTPUT_DIR / "商品销售核销看板.html"
DEFAULT_START_DATE = str(config_value("dashboard", "default_start_date", default="2026-01-01"))


def parse_amount(value: str) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except Exception:
        return 0.0


def clean(value: str) -> str:
    return str(value or "").strip()


def parse_dt(value: str) -> datetime | None:
    value = clean(value)
    if not value:
        return None
    value = value.replace("/", "-")
    for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(value[:width], fmt)
        except ValueError:
            pass
    return None


def days_between(start: str, end: str) -> int | None:
    start_dt = parse_dt(start)
    end_dt = parse_dt(end)
    if not start_dt or not end_dt or end_dt < start_dt:
        return None
    return (end_dt - start_dt).days


def cycle_bucket(days: int | None) -> int | None:
    if days is None:
        return None
    if days <= 7:
        return 0
    if days <= 15:
        return 1
    if days <= 30:
        return 2
    if days <= 90:
        return 3
    return 4


def is_canceled(order_status: str) -> bool:
    return order_status == "支付取消"


def is_pending(order_status: str, coupon_status: str) -> bool:
    return order_status in {"待使用", "已支付待核销"} or coupon_status == "待使用"


def is_verified(coupon_status: str) -> bool:
    return "已履约" in coupon_status


def is_refunded(coupon_status: str) -> bool:
    return "已退款" in coupon_status


def empty_group(day: str, product_type: str) -> dict:
    return {
        "date": day,
        "productType": product_type,
        "totalCount": 0,
        "validCount": 0,
        "pendingCount": 0,
        "verifiedCount": 0,
        "refundedCount": 0,
        "verifiedAmount": 0.0,
        "cycleCounted": 0,
        "cycleDaysSum": 0,
        "buckets": [0, 0, 0, 0, 0],
    }


def build_summary() -> dict:
    order_map = {}
    source_rows = 0
    with BASE_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            source_rows += 1
            order_id = clean(row.get("订单ID"))
            if not order_id:
                continue
            order_map[order_id] = {
                "orderId": order_id,
                "productType": clean(row.get("商品类型")) or "未分类",
                "orderStatus": clean(row.get("订单状态")),
                "couponStatus": clean(row.get("券状态")),
                "orderDate": clean(row.get("下单时间"))[:10],
                "orderTime": clean(row.get("下单时间")),
                "updateTime": clean(row.get("更新时间")),
                "paidAmount": parse_amount(row.get("实付金额")),
            }

    groups = {}
    for row in order_map.values():
        day = row["orderDate"]
        if not day:
            continue
        product_type = row["productType"]
        key = (day, product_type)
        group = groups.setdefault(key, empty_group(day, product_type))
        group["totalCount"] += 1
        canceled = is_canceled(row["orderStatus"])
        pending = is_pending(row["orderStatus"], row["couponStatus"])
        verified = is_verified(row["couponStatus"])
        refunded = is_refunded(row["couponStatus"])
        if not canceled:
            group["validCount"] += 1
        if pending:
            group["pendingCount"] += 1
        if verified:
            group["verifiedCount"] += 1
            group["verifiedAmount"] += row["paidAmount"]
            days = days_between(row["orderTime"], row["updateTime"])
            bucket = cycle_bucket(days)
            if bucket is not None:
                group["buckets"][bucket] += 1
                group["cycleCounted"] += 1
                group["cycleDaysSum"] += days
        if refunded:
            group["refundedCount"] += 1

    group_rows = sorted(groups.values(), key=lambda item: (item["date"], item["productType"]))
    dates = [item["date"] for item in group_rows]
    return {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "defaultStartDate": DEFAULT_START_DATE,
        "defaultEndDate": date.today().isoformat(),
        "minDate": min(dates) if dates else "",
        "maxDate": max(dates) if dates else "",
        "sourceRows": source_rows,
        "uniqueOrders": len(order_map),
        "groups": group_rows,
    }


def zero_metrics() -> dict:
    return {
        "totalCount": 0,
        "validCount": 0,
        "pendingCount": 0,
        "verifiedCount": 0,
        "refundedCount": 0,
        "verifiedAmount": 0.0,
        "cycleCounted": 0,
        "cycleDaysSum": 0,
        "buckets": [0, 0, 0, 0, 0],
    }


def add_metrics(target: dict, source: dict) -> dict:
    for key in (
        "totalCount",
        "validCount",
        "pendingCount",
        "verifiedCount",
        "refundedCount",
        "verifiedAmount",
        "cycleCounted",
        "cycleDaysSum",
    ):
        target[key] += source.get(key, 0)
    for index, value in enumerate(source.get("buckets", [])):
        target["buckets"][index] += value
    return target


def finalize_metrics(metrics: dict) -> dict:
    metrics["verifiedRate"] = metrics["verifiedCount"] / metrics["validCount"] if metrics["validCount"] else 0
    metrics["refundRate"] = metrics["refundedCount"] / metrics["validCount"] if metrics["validCount"] else 0
    metrics["avgCycleDays"] = metrics["cycleDaysSum"] / metrics["cycleCounted"] if metrics["cycleCounted"] else 0
    return metrics


def summarize_groups(groups: list[dict]) -> dict:
    metrics = zero_metrics()
    for group in groups:
        add_metrics(metrics, group)
    return finalize_metrics(metrics)


def summarize_products(groups: list[dict]) -> list[dict]:
    by_product = {}
    for group in groups:
        by_product.setdefault(group["productType"], zero_metrics())
        add_metrics(by_product[group["productType"]], group)
    rows = [{"name": name, **finalize_metrics(metrics)} for name, metrics in by_product.items()]
    return sorted(rows, key=lambda item: item["verifiedAmount"], reverse=True)


def fmt_int(value: float) -> str:
    return f"{value:,.0f}"


def fmt_money(value: float) -> str:
    return f"¥{value:,.0f}"


def fmt_rate(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_product_table(products: list[dict]) -> str:
    headers = ["商品类型", "已核销金额", "下单量", "待核销量", "核销量", "退货量", "核销率", "退货率"]
    rows = []
    for item in products:
        rows.append(
            "<tr>"
            f"<td>{html_lib.escape(item['name'])}</td>"
            f"<td>{fmt_money(item['verifiedAmount'])}</td>"
            f"<td>{fmt_int(item['validCount'])}</td>"
            f"<td>{fmt_int(item['pendingCount'])}</td>"
            f"<td>{fmt_int(item['verifiedCount'])}</td>"
            f"<td>{fmt_int(item['refundedCount'])}</td>"
            f"<td><span class=\"rate-cell\">{fmt_rate(item['verifiedRate'])}</span></td>"
            f"<td><span class=\"refund-rate-cell\">{fmt_rate(item['refundRate'])}</span></td>"
            "</tr>"
        )
    return (
        "<thead><tr>"
        + "".join(f"<th>{header}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody>"
    )


def build_cycle_cards(products: list[dict]) -> str:
    labels = ["0-7天", "8-15天", "16-30天", "31-90天", "90天外"]
    cards = []
    for item in sorted(products, key=lambda product: product["verifiedCount"], reverse=True):
        name = html_lib.escape(item["name"])
        total = max(1, item["cycleCounted"])
        segments = []
        chips = []
        for index, value in enumerate(item["buckets"]):
            pct = value / total * 100 if item["cycleCounted"] else 0
            segments.append(f'<div class="seg s{index + 1}" style="width:{pct}%"></div>')
            chips.append(
                '<div class="cycle-chip">'
                f'<span class="cycle-label"><i class="cycle-dot seg s{index + 1}"></i>{labels[index]}</span>'
                f'<b><span class="cycle-count">{fmt_int(value)}</span> '
                f'<span class="cycle-pct">{pct:.1f}%</span></b>'
                "</div>"
            )
        cards.append(
            '<div class="cycle-product">'
            "<div>"
            f'<div class="cycle-name">{name}</div>'
            f'<div class="cycle-avg">平均 {item["avgCycleDays"]:.1f} 天</div>'
            f'<div class="cycle-total">核销量：{fmt_int(item["verifiedCount"])}</div>'
            "</div>"
            "<div>"
            f'<div class="stack">{"".join(segments)}</div>'
            f'<div class="cycle-breakdown">{"".join(chips)}</div>'
            "</div>"
            "</div>"
        )
    return "".join(cards)


def main() -> None:
    summary = build_summary()
    default_groups = [
        group
        for group in summary["groups"]
        if summary["defaultStartDate"] <= group["date"] <= summary["defaultEndDate"]
    ]
    default_metrics = summarize_groups(default_groups)
    default_products = summarize_products(default_groups)
    initial_product_table = build_product_table(default_products)
    initial_cycle_cards = build_cycle_cards(default_products)
    payload = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>精诚养车服务产品销售数据看板</title>
  <style>
    :root {{
      --ink: #18232c;
      --muted: #697782;
      --line: #d9e1e7;
      --soft: #f4f7f8;
      --panel: #ffffff;
      --bg: #edf2f4;
      --green: #13735b;
      --teal: #16898c;
      --blue: #2d6cdf;
      --red: #c2473f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: linear-gradient(180deg, #f9fbfc 0%, var(--bg) 44%, #e8eef2 100%);
      color: var(--ink);
      font-family: "Microsoft YaHei", "Noto Sans SC", "PingFang SC", sans-serif;
      font-size: 14px;
    }}
    .page {{ max-width: 1480px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 18px; margin-bottom: 18px; }}
    h1 {{ margin: 0; font-size: 26px; line-height: 1.2; font-weight: 760; }}
    h2 {{ margin: 0 0 12px; font-size: 16px; }}
    .sub {{ color: var(--muted); margin-top: 6px; }}
    .filters {{
      display: grid;
      grid-template-columns: 1fr 1fr 1.25fr auto auto;
      gap: 12px;
      background: rgba(255,255,255,.88);
      border: 1px solid var(--line);
      padding: 14px;
      border-radius: 8px;
      margin-bottom: 18px;
      position: sticky;
      top: 0;
      z-index: 5;
      backdrop-filter: blur(8px);
    }}
    label {{ display: grid; gap: 6px; color: var(--muted); font-size: 12px; }}
    input, select, button {{
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      padding: 0 10px;
      font: inherit;
    }}
    button {{ cursor: pointer; background: var(--ink); color: #fff; border-color: var(--ink); min-width: 84px; }}
    button.secondary {{ background: #fff; color: var(--ink); }}
    .kpis {{ display: grid; grid-template-columns: repeat(7, minmax(120px, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .card, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 12px 28px rgba(24, 39, 51, .06);
    }}
    .kpi {{ padding: 14px; min-height: 96px; }}
    .kpi .name {{ color: var(--muted); font-size: 12px; }}
    .kpi .value {{ margin-top: 8px; font-size: 24px; font-weight: 760; white-space: nowrap; }}
    .kpi .hint {{ margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .panel {{ padding: 16px; min-width: 0; margin-bottom: 16px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid #edf1f4; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: var(--ink); font-size: 12px; font-weight: 800; }}
    .rate-cell {{ font-weight: 850; color: var(--green); }}
    .refund-rate-cell {{ font-weight: 850; color: var(--red); }}
    .scroll {{ overflow: auto; max-height: 430px; }}
    .trend-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 8px; }}
    .trend-sub {{ color: var(--muted); font-size: 12px; }}
    .trend-legend {{ display: flex; gap: 14px; color: var(--muted); font-size: 12px; }}
    .trend-legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
    .trend-dot {{ width: 10px; height: 10px; border-radius: 999px; }}
    .trend-chart {{ width: 100%; height: 280px; display: block; }}
    .cycle-board {{ display: grid; gap: 16px; }}
    .cycle-product {{ display: grid; grid-template-columns: 112px 1fr; gap: 14px; align-items: start; padding: 14px; background: var(--soft); border: 1px solid var(--line); border-radius: 8px; }}
    .cycle-name {{ font-weight: 760; }}
    .cycle-total {{ margin-top: 6px; color: var(--muted); font-size: 12px; line-height: 1.55; }}
    .cycle-avg {{ display: inline-block; margin-top: 8px; padding: 4px 8px; background: #fff; border: 1px solid #dfe8ec; border-radius: 999px; color: var(--green); font-weight: 760; font-size: 12px; }}
    .stack {{ display: flex; width: 100%; height: 30px; overflow: hidden; border-radius: 7px; background: #edf2f5; }}
    .seg {{ height: 100%; min-width: 1px; cursor: default; }}
    .seg.s1 {{ background: #13735b; }}
    .seg.s2 {{ background: #36a383; }}
    .seg.s3 {{ background: #5fa8d3; }}
    .seg.s4 {{ background: #d19b38; }}
    .seg.s5 {{ background: #c2473f; }}
    .cycle-breakdown {{ display: grid; grid-template-columns: repeat(5, minmax(116px, 1fr)); gap: 8px; margin-top: 10px; }}
    .cycle-chip {{ display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 18px; padding: 7px 10px; background: #fff; border: 1px solid #e1e8ec; border-radius: 8px; font-size: 12px; }}
    .cycle-chip b {{ display: inline-flex; align-items: baseline; gap: 14px; font-size: 13px; }}
    .cycle-count {{ color: var(--ink); }}
    .cycle-pct {{ color: var(--teal); font-weight: 850; }}
    .cycle-label {{ display: flex; align-items: center; gap: 6px; color: var(--muted); }}
    .cycle-dot {{ width: 9px; height: 9px; border-radius: 2px; flex: 0 0 auto; }}
    .cycle-empty {{ color: var(--muted); font-size: 13px; }}
    @media (max-width: 1100px) {{
      .kpis {{ grid-template-columns: repeat(2, 1fr); }}
      .filters {{ grid-template-columns: 1fr 1fr; position: static; }}
      .cycle-breakdown {{ grid-template-columns: repeat(2, minmax(130px, 1fr)); }}
    }}
    @media (max-width: 640px) {{
      .page {{ padding: 14px; }}
      header {{ display: block; }}
      .filters {{ grid-template-columns: 1fr; }}
      .kpis {{ grid-template-columns: 1fr; }}
      .cycle-product {{ grid-template-columns: 1fr; }}
      .cycle-breakdown {{ grid-template-columns: 1fr; }}
      th, td {{ padding: 8px 6px; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <header>
      <div>
        <h1>精诚养车服务产品销售数据看板</h1>
        <div class="sub" id="scopeText">当前范围：{fmt_int(default_metrics["totalCount"])} 个去重订单</div>
      </div>
      <div class="sub">基础表：总表_含券状态<br>生成时间：{summary["generatedAt"]}</div>
    </header>

    <section class="filters">
      <label>开始日期<input id="startDate" type="date"></label>
      <label>结束日期<input id="endDate" type="date"></label>
      <label>商品类型<select id="productType"><option value="">全部商品类型</option></select></label>
      <label>&nbsp;<button id="resetBtn">重置</button></label>
      <label>&nbsp;<button id="refreshBtn" class="secondary">刷新数据</button></label>
    </section>

    <section class="kpis">
      <div class="card kpi"><div class="name">已核销金额</div><div class="value" id="verifiedAmount">{fmt_money(default_metrics["verifiedAmount"])}</div><div class="hint">已履约订单实付金额</div></div>
      <div class="card kpi"><div class="name">下单量</div><div class="value" id="orderCount">{fmt_int(default_metrics["validCount"])}</div><div class="hint">不含支付取消</div></div>
      <div class="card kpi"><div class="name">待核销量</div><div class="value" id="pendingCount">{fmt_int(default_metrics["pendingCount"])}</div><div class="hint">订单状态为待使用</div></div>
      <div class="card kpi"><div class="name">核销量</div><div class="value" id="verifiedCount">{fmt_int(default_metrics["verifiedCount"])}</div><div class="hint">券状态包含已履约</div></div>
      <div class="card kpi"><div class="name">核销率</div><div class="value" id="verifiedRate">{fmt_rate(default_metrics["verifiedRate"])}</div><div class="hint">核销量 / 下单量</div></div>
      <div class="card kpi"><div class="name">退货量</div><div class="value" id="refundCount">{fmt_int(default_metrics["refundedCount"])}</div><div class="hint">券状态包含已退款</div></div>
      <div class="card kpi"><div class="name">退货率</div><div class="value" id="refundRate">{fmt_rate(default_metrics["refundRate"])}</div><div class="hint">退货量 / 下单量</div></div>
    </section>

    <section class="panel">
      <div class="trend-head">
        <div>
          <h2>月度下单与核销趋势</h2>
          <div class="trend-sub">按下单月份统计；下单量不含支付取消</div>
        </div>
        <div class="trend-legend">
          <span><i class="trend-dot" style="background:var(--blue)"></i>下单量</span>
          <span><i class="trend-dot" style="background:var(--green)"></i>核销量</span>
          <span><i class="trend-dot" style="background:var(--red)"></i>退货量</span>
        </div>
      </div>
      <svg id="trendChart" class="trend-chart" viewBox="0 0 1200 280" preserveAspectRatio="none"></svg>
    </section>

    <section class="panel">
      <h2>商品表现</h2>
      <div class="scroll"><table id="productTable">{initial_product_table}</table></div>
    </section>

    <section class="panel">
      <h2>核销周期分布</h2>
      <div id="cycleStacks" class="cycle-board">{initial_cycle_cards}</div>
    </section>
  </div>

  <script>
    const SUMMARY = {payload};
    const GROUPS = SUMMARY.groups || [];
    const fmtInt = new Intl.NumberFormat('zh-CN', {{ maximumFractionDigits: 0 }});
    const fmtMoney = new Intl.NumberFormat('zh-CN', {{ style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }});
    const byId = id => document.getElementById(id);

    function zeroMetrics() {{
      return {{
        totalCount: 0, validCount: 0, pendingCount: 0, verifiedCount: 0, refundedCount: 0,
        verifiedAmount: 0, cycleCounted: 0, cycleDaysSum: 0, buckets: [0, 0, 0, 0, 0]
      }};
    }}
    function addMetrics(target, source) {{
      target.totalCount += source.totalCount || 0;
      target.validCount += source.validCount || 0;
      target.pendingCount += source.pendingCount || 0;
      target.verifiedCount += source.verifiedCount || 0;
      target.refundedCount += source.refundedCount || 0;
      target.verifiedAmount += source.verifiedAmount || 0;
      target.cycleCounted += source.cycleCounted || 0;
      target.cycleDaysSum += source.cycleDaysSum || 0;
      for (let i = 0; i < 5; i++) target.buckets[i] += (source.buckets || [])[i] || 0;
      return target;
    }}
    function finalizeMetrics(m) {{
      m.verifiedRate = m.validCount ? m.verifiedCount / m.validCount : 0;
      m.refundRate = m.validCount ? m.refundedCount / m.validCount : 0;
      m.avgCycleDays = m.cycleCounted ? m.cycleDaysSum / m.cycleCounted : 0;
      return m;
    }}
    function filteredGroups() {{
      const start = byId('startDate').value;
      const end = byId('endDate').value;
      const product = byId('productType').value;
      return GROUPS.filter(g => {{
        if (start && g.date < start) return false;
        if (end && g.date > end) return false;
        if (product && g.productType !== product) return false;
        return true;
      }});
    }}
    function metrics(groups) {{
      return finalizeMetrics(groups.reduce((acc, group) => addMetrics(acc, group), zeroMetrics()));
    }}
    function table(el, headers, rows) {{
      el.innerHTML = '<thead><tr>' + headers.map(h => `<th>${{h}}</th>`).join('') + '</tr></thead><tbody>' +
        rows.map(row => '<tr>' + row.map(cell => `<td>${{cell}}</td>`).join('') + '</tr>').join('') + '</tbody>';
    }}
    function renderKpis(m) {{
      byId('verifiedAmount').textContent = fmtMoney.format(m.verifiedAmount);
      byId('orderCount').textContent = fmtInt.format(m.validCount);
      byId('pendingCount').textContent = fmtInt.format(m.pendingCount);
      byId('verifiedCount').textContent = fmtInt.format(m.verifiedCount);
      byId('verifiedRate').textContent = (m.verifiedRate * 100).toFixed(1) + '%';
      byId('refundCount').textContent = fmtInt.format(m.refundedCount);
      byId('refundRate').textContent = (m.refundRate * 100).toFixed(1) + '%';
    }}
    function productData(groups) {{
      const map = new Map();
      for (const group of groups) {{
        if (!map.has(group.productType)) map.set(group.productType, zeroMetrics());
        addMetrics(map.get(group.productType), group);
      }}
      return [...map.entries()].map(([name, data]) => ({{ name, ...finalizeMetrics(data) }}))
        .sort((a, b) => b.verifiedAmount - a.verifiedAmount);
    }}
    function renderProduct(groups) {{
      const data = productData(groups);
      table(byId('productTable'),
        ['商品类型', '已核销金额', '下单量', '待核销量', '核销量', '退货量', '核销率', '退货率'],
        data.map(d => [
          d.name, fmtMoney.format(d.verifiedAmount), fmtInt.format(d.validCount),
          fmtInt.format(d.pendingCount), fmtInt.format(d.verifiedCount), fmtInt.format(d.refundedCount),
          `<span class="rate-cell">${{(d.verifiedRate * 100).toFixed(1)}}%</span>`,
          `<span class="refund-rate-cell">${{(d.refundRate * 100).toFixed(1)}}%</span>`
        ])
      );
    }}
    function trendData(groups) {{
      const map = new Map();
      for (const group of groups) {{
        const month = group.date.slice(0, 7);
        if (!map.has(month)) map.set(month, {{ month, orders: 0, verified: 0, refunded: 0 }});
        const item = map.get(month);
        item.orders += group.validCount || 0;
        item.verified += group.verifiedCount || 0;
        item.refunded += group.refundedCount || 0;
      }}
      return [...map.values()].sort((a, b) => a.month.localeCompare(b.month));
    }}
    function renderTrend(groups) {{
      const data = trendData(groups);
      const svg = byId('trendChart');
      if (!data.length) {{
        svg.innerHTML = '<text x="600" y="145" text-anchor="middle" fill="#697782">暂无趋势数据</text>';
        return;
      }}
      const W = 1200, H = 280, L = 58, R = 26, T = 22, B = 48;
      const plotW = W - L - R, plotH = H - T - B;
      const maxY = Math.max(1, ...data.map(d => Math.max(d.orders, d.verified, d.refunded)));
      const niceMax = Math.ceil(maxY / 1000) * 1000 || maxY;
      const x = i => L + (data.length === 1 ? plotW / 2 : i * plotW / (data.length - 1));
      const y = v => T + plotH - (v / niceMax) * plotH;
      const points = key => data.map((d, i) => `${{x(i).toFixed(1)}},${{y(d[key]).toFixed(1)}}`).join(' ');
      const area = key => `${{L}},${{T + plotH}} ${{points(key)}} ${{L + plotW}},${{T + plotH}}`;
      const ticks = [0, .25, .5, .75, 1].map(t => Math.round(niceMax * t));
      const labels = data.map((d, i) => {{
        const show = data.length <= 14 || i === 0 || i === data.length - 1 || i % 2 === 0;
        return show ? `<text x="${{x(i)}}" y="${{H - 18}}" text-anchor="middle" fill="#697782" font-size="12">${{d.month}}</text>` : '';
      }}).join('');
      const dot = (key, color) => data.map((d, i) => `<circle cx="${{x(i)}}" cy="${{y(d[key])}}" r="4" fill="${{color}}"><title>${{d.month}}：${{fmtInt.format(d[key])}}</title></circle>`).join('');
      svg.innerHTML = `
        <defs>
          <linearGradient id="trendOrderFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#2d6cdf" stop-opacity=".15"/><stop offset="100%" stop-color="#2d6cdf" stop-opacity="0"/></linearGradient>
          <linearGradient id="trendVerifiedFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#13735b" stop-opacity=".18"/><stop offset="100%" stop-color="#13735b" stop-opacity="0"/></linearGradient>
        </defs>
        ${{ticks.map(v => `<line x1="${{L}}" x2="${{W - R}}" y1="${{y(v)}}" y2="${{y(v)}}" stroke="#e6edf1"/><text x="${{L - 10}}" y="${{y(v) + 4}}" text-anchor="end" fill="#697782" font-size="12">${{fmtInt.format(v)}}</text>`).join('')}}
        <polyline points="${{area('orders')}}" fill="url(#trendOrderFill)" stroke="none"></polyline>
        <polyline points="${{area('verified')}}" fill="url(#trendVerifiedFill)" stroke="none"></polyline>
        <polyline points="${{points('orders')}}" fill="none" stroke="#2d6cdf" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
        <polyline points="${{points('verified')}}" fill="none" stroke="#13735b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
        <polyline points="${{points('refunded')}}" fill="none" stroke="#c2473f" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
        ${{dot('orders', '#2d6cdf')}}
        ${{dot('verified', '#13735b')}}
        ${{dot('refunded', '#c2473f')}}
        ${{labels}}
      `;
    }}
    function renderCycle(groups) {{
      const labels = ['0-7天', '8-15天', '16-30天', '31-90天', '90天外'];
      const data = productData(groups).sort((a, b) => b.verifiedCount - a.verifiedCount);
      byId('cycleStacks').innerHTML = data.map(d => {{
        const total = Math.max(1, d.cycleCounted);
        const chips = d.buckets.map((v, i) => {{
          const pct = d.cycleCounted ? v / total * 100 : 0;
          return `
            <div class="cycle-chip" title="${{d.name}} ${{labels[i]}}：${{fmtInt.format(v)}}单，占比${{pct.toFixed(1)}}%">
              <span class="cycle-label"><i class="cycle-dot seg s${{i+1}}"></i>${{labels[i]}}</span>
              <b><span class="cycle-count">${{fmtInt.format(v)}}</span> <span class="cycle-pct">${{pct.toFixed(1)}}%</span></b>
            </div>`;
        }}).join('');
        return `
          <div class="cycle-product">
            <div>
              <div class="cycle-name">${{d.name}}</div>
              <div class="cycle-avg">平均 ${{d.avgCycleDays.toFixed(1)}} 天</div>
              <div class="cycle-total">核销量：${{fmtInt.format(d.verifiedCount)}}</div>
            </div>
            <div>
              <div class="stack">
                ${{d.buckets.map((v, i) => {{
                  const pct = d.cycleCounted ? v / total * 100 : 0;
                  return `<div class="seg s${{i+1}}" style="width:${{pct}}%"></div>`;
                }}).join('')}}
              </div>
              <div class="cycle-breakdown">${{chips || '<span class="cycle-empty">暂无核销周期数据</span>'}}</div>
            </div>
          </div>`;
      }}).join('');
    }}
    function render() {{
      const groups = filteredGroups();
      const m = metrics(groups);
      renderKpis(m);
      renderTrend(groups);
      renderProduct(groups);
      renderCycle(groups);
      byId('scopeText').textContent = `当前范围：${{fmtInt.format(m.totalCount)}} 个去重订单`;
    }}
    function init() {{
      const types = [...new Set(GROUPS.map(g => g.productType).filter(Boolean))].sort();
      byId('productType').innerHTML = '<option value="">全部商品类型</option>' + types.map(t => `<option value="${{t}}">${{t}}</option>`).join('');
      byId('startDate').value = SUMMARY.defaultStartDate || SUMMARY.minDate || '';
      byId('endDate').value = SUMMARY.defaultEndDate || SUMMARY.maxDate || '';
      ['startDate', 'endDate', 'productType'].forEach(id => byId(id).addEventListener('change', render));
      byId('resetBtn').addEventListener('click', () => {{
        byId('startDate').value = SUMMARY.defaultStartDate || SUMMARY.minDate || '';
        byId('endDate').value = SUMMARY.defaultEndDate || SUMMARY.maxDate || '';
        byId('productType').value = '';
        render();
      }});
      byId('refreshBtn').addEventListener('click', () => {{
        const url = new URL(window.location.href);
        url.searchParams.set('v', Date.now().toString());
        window.location.replace(url.toString());
      }});
      window.addEventListener('resize', render);
      render();
    }}
    init();
  </script>
</body>
</html>
"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for output_path in (OUTPUT_HTML, INDEX_HTML, INDEX_HTML_HTML, LEGACY_DASHBOARD_HTML):
        output_path.write_text(html, encoding="utf-8")
    print(OUTPUT_HTML)


if __name__ == "__main__":
    main()
