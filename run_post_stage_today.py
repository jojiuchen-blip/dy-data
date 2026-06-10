import json
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_dashboard_workflow as workflow


def main() -> None:
    today = date.today()
    run_dir = workflow.RUN_ROOT / today.strftime("%Y%m%d")
    env = os.environ.copy()

    workflow.run_checked(
        [str(workflow.PYTHON), str(workflow.ROOT / "build_sales_dashboard.py")],
        env,
    )
    shutil.copy2(workflow.INDEX_DASHBOARD_HTML, workflow.DASHBOARD_HTML)
    shutil.copy2(workflow.DASHBOARD_HTML, workflow.LEGACY_DASHBOARD_HTML)

    screenshot_path = workflow.SCREENSHOT_DIR / f"精诚养车服务产品销售数据看板_{today:%Y%m%d}.png"
    screenshot_ok = workflow.screenshot_dashboard(screenshot_path)

    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}

    webhook = os.getenv("DOUYIN_PUSH_WEBHOOK", "").strip()
    webhook_type = os.getenv("DOUYIN_PUSH_WEBHOOK_TYPE", "wecom").strip().lower()
    sent = False
    if webhook and screenshot_ok and webhook_type == "wecom":
        workflow.post_wecom_image(webhook, screenshot_path)
        sent = True
    elif webhook and screenshot_ok:
        workflow.post_webhook_text(webhook, "精诚养车服务产品销售数据看板已更新", webhook_type)
        sent = True

    result = {
        "start_date": (
            today - timedelta(days=int(os.getenv("DOUYIN_DAILY_LOOKBACK_DAYS", "45")))
        ).isoformat(),
        "end_date": today.isoformat(),
        "summary": summary,
        "screenshot": str(screenshot_path) if screenshot_ok else None,
        "webhook_sent": sent,
        "post_stage_only": True,
    }
    (run_dir / "daily_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "screenshot_ok": screenshot_ok,
                "webhook_sent": sent,
                "screenshot": str(screenshot_path),
                "merged_unique_orders": summary.get("merged_unique_orders"),
                "new_order_ids": summary.get("new_order_ids"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
