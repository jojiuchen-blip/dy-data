import base64
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from src.dy_data.config import path_value, script_root, tencent_value


ROOT = script_root()
PYTHON = path_value("python_exe", env_name="DY_DATA_PYTHON_EXE")
BASE_TABLE = path_value("base_table", env_name="BASE_TABLE")
RUN_ROOT = path_value("run_root")
DASHBOARD_DIR = path_value("dashboard_dir")
DASHBOARD_HTML = DASHBOARD_DIR / "精诚养车服务产品销售数据看板.html"
INDEX_DASHBOARD_HTML = DASHBOARD_DIR / "index.html"
LEGACY_DASHBOARD_HTML = DASHBOARD_DIR / "商品销售核销看板.html"
SCREENSHOT_DIR = path_value("screenshot_dir")


def month_range(start: date, end: date) -> list[str]:
    months = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        months.append(f"{cursor.year}-{cursor.month:02d}")
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def run_checked(args: list[str], env: dict[str, str], cwd: Path = ROOT) -> None:
    subprocess.run(args, cwd=str(cwd), env=env, check=True)


def edge_path() -> Path | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    return next((path for path in candidates if path.exists()), None)


def file_url(path: Path) -> str:
    return "file:///" + quote(str(path.resolve()).replace("\\", "/"), safe="/:")


def screenshot_dashboard(output_path: Path) -> bool:
    browser = edge_path()
    if not browser:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--window-size=1480,1550",
            "--virtual-time-budget=5000",
            f"--screenshot={output_path}",
            f"{file_url(DASHBOARD_HTML)}?v={int(time.time())}",
        ],
        check=True,
    )
    return output_path.exists()


def post_webhook_text(url: str, text: str, webhook_type: str) -> None:
    if webhook_type == "wecom":
        payload = {"msgtype": "markdown", "markdown": {"content": text}}
    elif webhook_type == "dingtalk":
        payload = {"msgtype": "markdown", "markdown": {"title": "抖音看板更新", "text": text}}
    else:
        payload = {"text": text}
    requests.post(url, json=payload, timeout=20).raise_for_status()


def post_wecom_image(url: str, image_path: Path) -> None:
    data = image_path.read_bytes()
    payload = {
        "msgtype": "image",
        "image": {
            "base64": base64.b64encode(data).decode("ascii"),
            "md5": hashlib.md5(data).hexdigest(),
        },
    }
    requests.post(url, json=payload, timeout=20).raise_for_status()


def main() -> None:
    today = date.today()
    lookback_days = int(os.getenv("DOUYIN_DAILY_LOOKBACK_DAYS", "45"))
    start = today - timedelta(days=lookback_days)
    end = today
    run_dir = RUN_ROOT / today.strftime("%Y%m%d")
    run_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "BASE_TABLE": str(BASE_TABLE),
            "SUPPLEMENT_RUN_DIR": str(run_dir),
            "SUPPLEMENT_MONTHS": ",".join(month_range(start, end)),
            "SUPPLEMENT_START_DATE": start.isoformat(),
            "SUPPLEMENT_END_DATE": end.isoformat(),
            "SUPPLEMENT_FORCE_DAYS_FROM": start.isoformat(),
            "DOUYIN_REQUEST_SLEEP_SECONDS": os.getenv("DOUYIN_REQUEST_SLEEP_SECONDS", "1"),
        }
    )

    run_checked([str(PYTHON), str(ROOT / "supplement_affected_months.py")], env)
    run_checked([str(PYTHON), str(ROOT / "build_sales_dashboard.py")], env)
    shutil.copy2(INDEX_DASHBOARD_HTML, DASHBOARD_HTML)
    shutil.copy2(DASHBOARD_HTML, LEGACY_DASHBOARD_HTML)
    if all(
        str(value or "").strip()
        for value in (
            tencent_value("TENCENT_SECRET_ID", "secret_id", default=""),
            tencent_value("TENCENT_SECRET_KEY", "secret_key", default=""),
            tencent_value("TENCENT_COS_REGION", "region", default=""),
            tencent_value("TENCENT_COS_BUCKET", "bucket", default=""),
        )
    ):
        run_checked([str(PYTHON), str(ROOT / "upload_dashboard_to_tencent_cos.py")], env)

    screenshot_path = SCREENSHOT_DIR / f"精诚养车服务产品销售数据看板_{today:%Y%m%d}.png"
    screenshot_ok = screenshot_dashboard(screenshot_path)

    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    message = "\n".join(
        [
            "【精诚养车-抖音数据看板】",
            "精诚养车服务产品销售数据看板已更新",
            f"> 扫描日期：{start.isoformat()} 至 {end.isoformat()}",
            f"> 基础表订单数：{summary.get('merged_unique_orders', '未知')}",
            f"> 新增订单数：{summary.get('new_order_ids', '未知')}",
            f"> 失败日期：{len(summary.get('failed_days', []))}",
            f"> 截图：{screenshot_path if screenshot_ok else '截图失败'}",
        ]
    )

    webhook = os.getenv("DOUYIN_PUSH_WEBHOOK", "").strip()
    webhook_type = os.getenv("DOUYIN_PUSH_WEBHOOK_TYPE", "wecom").strip().lower()
    if webhook:
        if screenshot_ok and webhook_type == "wecom":
            post_wecom_image(webhook, screenshot_path)
        elif screenshot_ok:
            post_webhook_text(webhook, message, webhook_type)

    (run_dir / "daily_result.json").write_text(
        json.dumps(
            {
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "summary": summary,
                "screenshot": str(screenshot_path) if screenshot_ok else None,
                "webhook_sent": bool(webhook),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
