from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "src").exists())
sys.path.insert(0, str(REPO_ROOT))

from src.dy_data.config import path_value, workspace_root
from src.dy_data.db_import import import_backend_aweme_rows


DEFAULT_START_URL = "https://life.douyin.com/"
DEFAULT_EXPORT_PATTERN = r"导出|下载|Export|Download"
DEFAULT_CONFIRM_PATTERN = r"确定|确认|导出|下载|立即导出|开始导出|创建任务"


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_args() -> argparse.Namespace:
    field_probe_dir = path_value("field_probe_dir")
    default_profile_dir = workspace_root() / "browser_state" / "edge_backend_aweme"
    default_download_dir = workspace_root() / "browser_downloads" / "backend_aweme"
    saved_url_path = field_probe_dir / "backend_aweme_page_url.txt"

    saved_url = ""
    if saved_url_path.exists():
        saved_url = saved_url_path.read_text(encoding="utf-8").strip()

    parser = argparse.ArgumentParser(
        description="Use Microsoft Edge browser automation to export Douyin Laike backend aweme detail workbook."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("DOUYIN_LAIKE_AWEME_URL", saved_url or DEFAULT_START_URL),
        help="Target Douyin Laike page URL. Defaults to saved URL, then life.douyin.com.",
    )
    parser.add_argument(
        "--profile-dir",
        default=os.getenv("DOUYIN_EDGE_AUTOMATION_PROFILE", str(default_profile_dir)),
        help="Persistent Edge automation profile directory. Login state is kept here.",
    )
    parser.add_argument(
        "--download-dir",
        default=os.getenv("DOUYIN_EDGE_DOWNLOAD_DIR", str(default_download_dir)),
        help="Temporary browser download directory.",
    )
    parser.add_argument(
        "--output-xlsx",
        default=os.getenv("BACKEND_AWEME_EXPORT_XLSX", str(field_probe_dir / "抖音号明细-自动导出.xlsx")),
        help="Final exported workbook path.",
    )
    parser.add_argument(
        "--export-selector",
        default=os.getenv("DOUYIN_AWEME_EXPORT_SELECTOR", ""),
        help="Optional Playwright selector for the export button.",
    )
    parser.add_argument(
        "--export-pattern",
        default=os.getenv("DOUYIN_AWEME_EXPORT_PATTERN", DEFAULT_EXPORT_PATTERN),
        help="Regex used to find an export/download button when selector is not provided.",
    )
    parser.add_argument(
        "--confirm-pattern",
        default=os.getenv("DOUYIN_AWEME_CONFIRM_PATTERN", DEFAULT_CONFIRM_PATTERN),
        help="Regex used to confirm export in dialogs or menus.",
    )
    parser.add_argument(
        "--manual-wait-seconds",
        type=int,
        default=int(os.getenv("DOUYIN_AWEME_MANUAL_WAIT_SECONDS", "0")),
        help="Seconds to wait after opening the page so a user can login/navigate manually.",
    )
    parser.add_argument(
        "--download-timeout-seconds",
        type=int,
        default=int(os.getenv("DOUYIN_AWEME_DOWNLOAD_TIMEOUT_SECONDS", "60")),
        help="Maximum seconds to wait for a download after clicking export.",
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Only open Edge and save the final current URL after manual wait; do not click export.",
    )
    parser.add_argument(
        "--no-parse",
        action="store_true",
        help="Do not unzip the downloaded workbook or run the existing XML parser.",
    )
    parser.add_argument(
        "--import-db",
        action="store_true",
        default=env_flag("DY_DATA_IMPORT_BACKEND_AWEME_TO_DB"),
        help="Import parsed backend aweme rows into the database configured by DY_DATA_DATABASE_URL.",
    )
    parser.add_argument(
        "--delete-local-after-db",
        action="store_true",
        default=env_flag("DY_DATA_DELETE_BACKEND_AWEME_FILES_AFTER_DB"),
        help="Delete downloaded workbook, parsed CSV, and extracted XML after a successful database import.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Edge headless. Not recommended for first setup or sites with login checks.",
    )
    return parser.parse_args()


def require_playwright() -> Any:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Missing dependency: playwright. Install it with `python -m pip install playwright`."
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_debug_artifacts(page: Any, reason: str) -> Path:
    debug_dir = path_value("field_probe_dir") / "browser_export_debug"
    ensure_directory(debug_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = debug_dir / f"backend_aweme_export_{stamp}.png"
    json_path = debug_dir / f"backend_aweme_export_{stamp}.json"

    elements: list[dict[str, str]] = []
    for locator in page.locator("button, [role=button], a").all()[:200]:
        try:
            text = (locator.inner_text(timeout=300) or "").strip()
            aria = (locator.get_attribute("aria-label", timeout=300) or "").strip()
            title = (locator.get_attribute("title", timeout=300) or "").strip()
            if text or aria or title:
                elements.append({"text": text, "aria_label": aria, "title": title})
        except Exception:
            continue

    page.screenshot(path=str(screenshot_path), full_page=True)
    json_path.write_text(
        json.dumps(
            {
                "reason": reason,
                "url": page.url,
                "screenshot": str(screenshot_path),
                "interactive_elements": elements,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return json_path


def click_locator_for_download(
    page: Any,
    locator: Any,
    playwright_timeout_error: Any,
    timeout_ms: int,
) -> Any | None:
    count = min(locator.count(), 20)
    for index in range(count):
        target = locator.nth(index)
        try:
            if not target.is_visible(timeout=500):
                continue
            with page.expect_download(timeout=timeout_ms) as download_info:
                target.click(timeout=5000)
            return download_info.value
        except playwright_timeout_error:
            return None
        except Exception:
            continue
    return None


def click_visible(locator: Any) -> bool:
    count = min(locator.count(), 20)
    for index in range(count):
        target = locator.nth(index)
        try:
            if target.is_visible(timeout=500):
                target.click(timeout=5000)
                return True
        except Exception:
            continue
    return False


def try_download(page: Any, args: argparse.Namespace, playwright_timeout_error: Any) -> Any:
    timeout_ms = args.download_timeout_seconds * 1000

    if args.export_selector:
        download = click_locator_for_download(
            page,
            page.locator(args.export_selector),
            playwright_timeout_error,
            timeout_ms,
        )
        if download:
            return download
        raise RuntimeError(f"No download after clicking selector: {args.export_selector}")

    export_re = re.compile(args.export_pattern, re.I)
    confirm_re = re.compile(args.confirm_pattern, re.I)
    export_locators = [
        page.get_by_role("button", name=export_re),
        page.get_by_text(export_re),
        page.locator("button, [role=button], a").filter(has_text=export_re),
    ]

    for locator in export_locators:
        download = click_locator_for_download(page, locator, playwright_timeout_error, timeout_ms)
        if download:
            return download

        if click_visible(locator):
            time.sleep(1)
            confirm_locators = [
                page.get_by_role("button", name=confirm_re),
                page.get_by_text(confirm_re),
                page.locator("button, [role=button], a").filter(has_text=confirm_re),
            ]
            for confirm_locator in confirm_locators:
                download = click_locator_for_download(
                    page,
                    confirm_locator,
                    playwright_timeout_error,
                    timeout_ms,
                )
                if download:
                    return download

    debug_path = save_debug_artifacts(page, "export_button_or_download_not_found")
    raise RuntimeError(f"Could not trigger a download. Debug artifact: {debug_path}")


def save_download(download: Any, download_dir: Path, output_xlsx: Path) -> Path:
    ensure_directory(download_dir)
    ensure_directory(output_xlsx.parent)
    suggested_name = download.suggested_filename or "backend_aweme_export.xlsx"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = download_dir / f"{timestamp}_{suggested_name}"
    download.save_as(str(raw_path))
    shutil.copy2(raw_path, output_xlsx)
    return raw_path


def prepare_xlsx_sheet_xml(xlsx_path: Path) -> Path:
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Downloaded workbook not found: {xlsx_path}")
    inspect_dir = path_value("tmp_xlsx_sheet_xml").parents[2]
    root = workspace_root().resolve()
    resolved_inspect = inspect_dir.resolve()
    if root not in [resolved_inspect, *resolved_inspect.parents]:
        raise RuntimeError(f"Refusing to clear unexpected inspect directory: {inspect_dir}")
    if inspect_dir.exists():
        shutil.rmtree(inspect_dir)
    ensure_directory(inspect_dir)
    with zipfile.ZipFile(xlsx_path) as archive:
        archive.extractall(inspect_dir)
    sheet_xml = path_value("tmp_xlsx_sheet_xml")
    if not sheet_xml.exists():
        raise FileNotFoundError(f"sheet1.xml not found after extracting workbook: {sheet_xml}")
    return sheet_xml


def run_existing_parser(sheet_xml: Path) -> None:
    parser_path = REPO_ROOT / "scripts" / "exploration" / "parse_backend_aweme_sheet_xml.py"
    env = os.environ.copy()
    env["BACKEND_AWEME_SHEET_XML"] = str(sheet_xml)
    subprocess.run([sys.executable, str(parser_path)], cwd=str(REPO_ROOT), env=env, check=True)


def read_csv_records(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def delete_if_exists(path: Path) -> None:
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def main() -> None:
    args = parse_args()
    if args.import_db and args.no_parse:
        raise SystemExit("--import-db requires parsing; remove --no-parse.")

    sync_playwright, playwright_timeout_error = require_playwright()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    profile_dir = Path(args.profile_dir)
    download_dir = Path(args.download_dir)
    output_xlsx = Path(args.output_xlsx)
    ensure_directory(profile_dir)
    ensure_directory(download_dir)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="msedge",
            headless=args.headless,
            accept_downloads=True,
            downloads_path=str(download_dir),
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except playwright_timeout_error:
                pass

            if args.manual_wait_seconds > 0:
                print(
                    f"Edge is open. Login/navigate if needed; waiting {args.manual_wait_seconds} seconds..."
                )
                time.sleep(args.manual_wait_seconds)
                current_url_path = path_value("field_probe_dir") / "backend_aweme_page_url.txt"
                current_url_path.write_text(page.url, encoding="utf-8")
                print(f"Saved current page URL: {current_url_path}")

            if args.setup_only:
                print(json.dumps({"setup_only": True, "current_url": page.url}, ensure_ascii=False, indent=2))
                return

            download = try_download(page, args, playwright_timeout_error)
            raw_path = save_download(download, download_dir, output_xlsx)
            result: dict[str, Any] = {
                "run_id": run_id,
                "downloaded_raw": str(raw_path),
                "output_xlsx": str(output_xlsx),
                "page_url": page.url,
            }

            if not args.no_parse:
                sheet_xml = prepare_xlsx_sheet_xml(output_xlsx)
                run_existing_parser(sheet_xml)
                output_csv = path_value("backend_aweme_csv")
                result["sheet_xml"] = str(sheet_xml)
                result["output_csv"] = str(output_csv)

                if args.import_db:
                    rows = read_csv_records(output_csv)
                    db_result = import_backend_aweme_rows(
                        rows,
                        source_run_id=f"backend_aweme_{run_id}",
                        source_page_url=page.url,
                        source_file_name=raw_path.name,
                    )
                    result["db_import"] = db_result

                    if args.delete_local_after_db:
                        delete_if_exists(raw_path)
                        delete_if_exists(output_xlsx)
                        delete_if_exists(output_csv)
                        delete_if_exists(path_value("tmp_xlsx_sheet_xml").parents[2])
                        result["deleted_local_files_after_db"] = True

            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            context.close()


if __name__ == "__main__":
    main()
