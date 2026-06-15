from __future__ import annotations

import argparse
import json
import os
import time
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
DEFAULT_EXPORT_SELECTOR = "div.lifep-container-header button.byted-btn"
WORKBOOK_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}


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
    export_selector = os.getenv("BACKEND_AWEME_EXPORT_SELECTOR", DEFAULT_EXPORT_SELECTOR)
    export_text = os.getenv("BACKEND_AWEME_EXPORT_TEXT", "导出")
    timeout_ms = int(os.getenv("BACKEND_AWEME_EXPORT_TIMEOUT_MS", "120000"))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(resolve_playwright_cdp_url(resolved_cdp_url))
            context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=True)
            page = context.pages[0] if context.pages else context.new_page()
            completed_download: dict[str, str] = {}

            def capture_completed_download(response: Any) -> None:
                if "/life/gate/v3/download/mget" not in response.url:
                    return
                try:
                    payload = response.json()
                except Exception:
                    return
                info = extract_completed_download_info(payload)
                if info:
                    completed_download.update(info)

            page.on("response", capture_completed_download)
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page_content = page.content()
            if is_login_required(page.url, page_content):
                raise BrowserExportError("Douyin backend login required. Log in through the protected noVNC browser first.")

            download = None
            try:
                with page.expect_download(timeout=timeout_ms) as download_info:
                    click_backend_export(
                        page,
                        export_selector=export_selector,
                        export_text=export_text,
                        timeout_ms=timeout_ms,
                    )
                download = download_info.value
            except PlaywrightTimeoutError:
                if not completed_download.get("file_url"):
                    raise
            if download is not None:
                downloaded_path = save_playwright_download_if_workbook(download, target_dir=target_dir)
                if downloaded_path is not None:
                    return downloaded_path

            info = wait_for_completed_download(page, completed_download, timeout_ms=timeout_ms)
            return save_workbook_from_file_url(
                context,
                file_url=info["file_url"],
                file_name=info.get("file_name") or "",
                target_dir=target_dir,
                timeout_ms=timeout_ms,
            )
    except PlaywrightTimeoutError as exc:
        raise BrowserExportError("Timed out waiting for backend aweme workbook download.") from exc


def click_backend_export(page: Any, *, export_selector: str, export_text: str, timeout_ms: int) -> None:
    if export_selector:
        page.locator(export_selector).click(timeout=timeout_ms)
    else:
        page.get_by_text(export_text, exact=False).click(timeout=timeout_ms)


def save_playwright_download_if_workbook(download: Any, *, target_dir: Path) -> Path | None:
    suggested_filename = download.suggested_filename or "backend_aweme_export"
    target_path = target_dir / Path(suggested_filename).name
    download.save_as(target_path)
    if target_path.suffix.lower() in WORKBOOK_EXTENSIONS and target_path.stat().st_size > 0:
        return target_path
    target_path.unlink(missing_ok=True)
    return None


def wait_for_completed_download(page: Any, completed_download: dict[str, str], *, timeout_ms: int) -> dict[str, str]:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if completed_download.get("file_url"):
            return completed_download
        page.wait_for_timeout(500)
    raise BrowserExportError("Timed out waiting for backend aweme workbook file URL.")


def save_workbook_from_file_url(
    context: Any,
    *,
    file_url: str,
    file_name: str,
    target_dir: Path,
    timeout_ms: int,
) -> Path:
    resolved_url = normalize_download_file_url(file_url)
    response = context.request.get(resolved_url, timeout=timeout_ms)
    if not response.ok:
        raise BrowserExportError(f"Backend aweme workbook download failed with HTTP {response.status}.")
    body = response.body()
    if not body:
        raise BrowserExportError("Backend aweme workbook download returned an empty file.")

    target_path = target_dir / workbook_filename(file_name, resolved_url)
    target_path.write_bytes(body)
    return target_path


def extract_completed_download_info(payload: dict[str, Any]) -> dict[str, str] | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    infos = data.get("download_infos")
    if not isinstance(infos, list):
        return None

    for raw_info in infos:
        if not isinstance(raw_info, dict):
            continue
        file_url = raw_info.get("file_url")
        if not file_url:
            continue
        status = raw_info.get("status")
        if status not in {2, "2"}:
            continue
        return {
            "file_url": str(file_url),
            "file_name": str(raw_info.get("file_name") or ""),
        }
    return None


def normalize_download_file_url(file_url: str) -> str:
    stripped = file_url.strip()
    if stripped.startswith("//"):
        return f"https:{stripped}"
    if not urlparse(stripped).scheme:
        return f"https://{stripped.lstrip('/')}"
    return stripped


def workbook_filename(file_name: str, file_url: str) -> str:
    parsed_name = Path(file_name).name if file_name else ""
    if parsed_name:
        return parsed_name
    url_name = Path(urlparse(file_url).path).name
    if url_name:
        return url_name
    return "backend_aweme_export.xlsx"


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
