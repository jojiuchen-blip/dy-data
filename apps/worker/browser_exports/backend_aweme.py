from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

from sqlalchemy.orm import Session

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.worker.browser_exports.backend_aweme_parser import parse_backend_aweme_workbook
from apps.worker.collectors.types import PhaseStats
from apps.worker.repositories import upsert_aweme_account, upsert_aweme_binding


DEFAULT_EXPORT_URL = "https://life.douyin.com/"


class BrowserExportError(RuntimeError):
    pass


def run_backend_aweme_export(
    session: Session,
    *,
    source_run_id: str,
    workbook_path: str | Path | None = None,
    cdp_url: str | None = None,
    export_url: str | None = None,
    run_dir: str | Path | None = None,
) -> PhaseStats:
    resolved_workbook = Path(workbook_path) if workbook_path else export_workbook_via_browser(
        cdp_url=cdp_url,
        export_url=export_url,
        run_dir=run_dir,
    )
    records = parse_backend_aweme_workbook(resolved_workbook)
    return upsert_backend_aweme_records(session, records, source_run_id=source_run_id)


def upsert_backend_aweme_records(
    session: Session,
    records: list[dict[str, Any]],
    *,
    source_run_id: str,
) -> PhaseStats:
    stats = PhaseStats(name="backend_aweme_export", fetched=len(records))
    for record in records:
        douyin_id = record.get("douyin_id")
        account_id = record.get("account_id")
        poi_id = record.get("poi_id")
        if not (douyin_id or account_id):
            stats.skipped += 1
            continue

        binding_key = _binding_key(account_id, douyin_id, poi_id)
        upsert_aweme_binding(
            session,
            binding_key,
            douyin_id=douyin_id,
            douyin_nickname=record.get("douyin_nickname"),
            account_id=account_id,
            account_name=record.get("account_name"),
            poi_id=poi_id,
            binding_status=record.get("binding_status"),
            raw_payload=record.get("raw_payload") or record,
            source_run_id=source_run_id,
        )
        stats.upserted += 1

        if account_id:
            upsert_aweme_account(
                session,
                account_id,
                nickname=record.get("douyin_nickname"),
                binding_status=record.get("binding_status"),
            )
            stats.upserted += 1
    return stats


def export_workbook_via_browser(
    *,
    cdp_url: str | None = None,
    export_url: str | None = None,
    run_dir: str | Path | None = None,
) -> Path:
    resolved_cdp_url = (cdp_url if cdp_url is not None else os.getenv("BROWSER_CDP_URL", "")).strip()
    if not resolved_cdp_url:
        raise BrowserExportError("BROWSER_CDP_URL is required when workbook_path is not provided.")

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserExportError("Install playwright before running browser exports.") from exc

    target_dir = Path(run_dir or os.getenv("BROWSER_EXPORT_RUN_DIR", ".")).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_url = export_url or os.getenv("BACKEND_AWEME_EXPORT_URL", DEFAULT_EXPORT_URL)
    export_selector = os.getenv("BACKEND_AWEME_EXPORT_SELECTOR", "")
    export_text = os.getenv("BACKEND_AWEME_EXPORT_TEXT", "导出")
    timeout_ms = int(os.getenv("BACKEND_AWEME_EXPORT_TIMEOUT_MS", "120000"))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(resolve_playwright_cdp_url(resolved_cdp_url))
            context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=True)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page_content = page.content()
            if is_login_required(page.url, page_content):
                raise BrowserExportError("Douyin backend login required. Log in through the protected noVNC browser first.")

            with page.expect_download(timeout=timeout_ms) as download_info:
                if export_selector:
                    page.locator(export_selector).click(timeout=timeout_ms)
                else:
                    page.get_by_text(export_text, exact=False).click(timeout=timeout_ms)
            download = download_info.value
            target_path = target_dir / (download.suggested_filename or "backend_aweme_export.xlsx")
            download.save_as(target_path)
            return target_path
    except PlaywrightTimeoutError as exc:
        raise BrowserExportError("Timed out waiting for backend aweme workbook download.") from exc


def resolve_playwright_cdp_url(cdp_url: str) -> str:
    parsed = urlparse(cdp_url)
    if parsed.scheme in {"ws", "wss"}:
        return cdp_url

    try:
        with urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise BrowserExportError(f"Unable to inspect browser CDP endpoint at {cdp_url}.") from exc

    websocket_url = str(payload.get("webSocketDebuggerUrl") or "")
    if not websocket_url:
        raise BrowserExportError(f"Browser CDP endpoint at {cdp_url} did not return a websocket URL.")
    return normalize_cdp_websocket_url(cdp_url, websocket_url)


def normalize_cdp_websocket_url(cdp_url: str, websocket_url: str) -> str:
    cdp_parts = urlparse(cdp_url)
    websocket_parts = urlparse(websocket_url)
    if websocket_parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return websocket_url
    if cdp_parts.hostname in {"127.0.0.1", "localhost", "::1"}:
        return websocket_url

    scheme = "wss" if cdp_parts.scheme == "https" else "ws"
    return urlunparse(
        websocket_parts._replace(
            scheme=scheme,
            netloc=cdp_parts.netloc,
        )
    )


def is_login_required(url: str, page_text: str) -> bool:
    lowered_url = url.lower()
    if "login" in lowered_url or "passport" in lowered_url:
        return True
    return "登录" in page_text and "抖音号明细" not in page_text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export backend aweme bindings through Chromium or import a workbook.")
    parser.add_argument("--source-run-id", default=os.getenv("JOB_RUN_ID", "backend_aweme_manual"))
    parser.add_argument("--workbook-path", default=os.getenv("BACKEND_AWEME_WORKBOOK", ""))
    parser.add_argument("--cdp-url", default=os.getenv("BROWSER_CDP_URL", ""))
    parser.add_argument("--export-url", default=os.getenv("BACKEND_AWEME_EXPORT_URL", DEFAULT_EXPORT_URL))
    parser.add_argument("--run-dir", default=os.getenv("BROWSER_EXPORT_RUN_DIR", "."))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("Set DY_DATABASE_URL or DATABASE_URL before running backend aweme export.")

    workbook_path = args.workbook_path or None
    with session_scope(factory) as session:
        stats = run_backend_aweme_export(
            session,
            source_run_id=args.source_run_id,
            workbook_path=workbook_path,
            cdp_url=args.cdp_url,
            export_url=args.export_url,
            run_dir=args.run_dir,
        )
        print(json.dumps(stats.as_metadata(), ensure_ascii=False))
    return 0


def _binding_key(account_id: str | None, douyin_id: str | None, poi_id: str | None) -> str:
    return ":".join(part or "-" for part in (account_id, douyin_id, poi_id))


if __name__ == "__main__":
    raise SystemExit(main())
