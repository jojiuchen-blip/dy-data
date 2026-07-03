from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.db import get_session_factory, session_scope
from apps.api.dy_api.models import DimStorePoiMapping
from apps.worker.browser_exports.backend_aweme_parser import parse_backend_aweme_workbook
from apps.worker.collectors.types import PhaseStats
from apps.worker.repositories import (
    upsert_aweme_account,
    upsert_aweme_binding,
    upsert_store,
    upsert_store_poi_mapping,
)


DEFAULT_EXPORT_URL = "https://life.douyin.com/"
DEFAULT_EXPORT_SELECTOR = "div.lifep-container-header button.byted-btn"
BACKEND_AWEME_BIND_LIST_PATH = "/life/merchant/v1/integration-user/bind/list"
BIND_LIST_PAGE_SIZE = 100
WORKBOOK_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
INACTIVE_BINDING_STATUSES = {
    "inactive",
    "unbound",
    "unbind",
    "failed",
    "pending",
    "rejected",
    "reviewing",
    "\u5df2\u89e3\u7ed1",
    "\u7ed1\u5b9a\u5931\u6548",
    "\u5ba1\u6838\u5931\u8d25",
    "\u7ed1\u5b9a\u5df2\u62d2\u7edd",
}


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
    if workbook_path:
        records = parse_backend_aweme_workbook(Path(workbook_path))
    else:
        records = export_backend_aweme_records_via_browser(
            cdp_url=cdp_url,
            export_url=export_url,
            run_dir=run_dir,
        )
    return upsert_backend_aweme_records(session, records, source_run_id=source_run_id)


def export_backend_aweme_records_via_browser(
    *,
    cdp_url: str | None = None,
    export_url: str | None = None,
    run_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    try:
        workbook = export_workbook_via_browser(cdp_url=cdp_url, export_url=export_url, run_dir=run_dir)
    except BrowserExportError as exc:
        if "Timed out waiting for backend aweme workbook download" not in str(exc):
            raise
        return fetch_backend_aweme_records_via_bind_list_api(cdp_url=cdp_url)
    return parse_backend_aweme_workbook(workbook)


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

        raw_payload = record.get("raw_payload") or record
        binding_status = record.get("binding_status")
        account_type = raw_payload.get("\u8d26\u53f7\u7c7b\u578b") or raw_payload.get("account_type")
        binding_key = _binding_key(account_id, douyin_id, poi_id, binding_status, account_type)
        upsert_aweme_binding(
            session,
            binding_key,
            douyin_id=douyin_id,
            douyin_nickname=record.get("douyin_nickname"),
            account_id=account_id,
            account_name=record.get("account_name"),
            poi_id=poi_id,
            binding_status=binding_status,
            raw_payload=raw_payload,
            source_run_id=source_run_id,
        )
        stats.upserted += 1

        if account_id and is_active_binding_status(binding_status):
            store_name = record.get("account_name") or record.get("douyin_nickname") or account_id
            upsert_store(
                session,
                account_id,
                store_name,
                certified_subject_name=record.get("certified_subject_name"),
            )
            stats.upserted += 1
            if is_valid_poi_id(poi_id):
                upsert_backend_store_poi_mapping(
                    session,
                    store_id=account_id,
                    poi_id=poi_id,
                    poi_name=record.get("account_name"),
                )
                stats.upserted += 1
            upsert_aweme_account(
                session,
                account_id,
                nickname=record.get("douyin_nickname"),
                store_id=account_id,
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

    target_dir = Path(
        run_dir
        or os.getenv("BROWSER_EXPORT_RUN_DIR")
        or os.getenv("BROWSER_EXPORT_ARTIFACT_DIR")
        or "."
    ).resolve()
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
            observed_responses: list[dict[str, Any]] = []

            def capture_export_response(response: Any) -> None:
                response_url = str(response.url)
                if is_relevant_export_response(response_url):
                    item = {"url": redact_url(response_url), "status": getattr(response, "status", None)}
                    try:
                        payload = response.json()
                    except Exception:
                        payload = None
                    if payload is not None:
                        item["json"] = json.dumps(payload, ensure_ascii=False)[:1200]
                    observed_responses.append(item)
                    del observed_responses[:-30]

                if "/life/gate/v3/download/mget" not in response_url:
                    return
                try:
                    payload = response.json()
                except Exception:
                    return
                info = extract_completed_download_info(payload)
                if info:
                    completed_download.update(info)

            page.on("response", capture_export_response)
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page_content = page.content()
            if is_login_required(page.url, page_content):
                raise BrowserExportError("Douyin backend login required. Log in through the protected noVNC browser first.")

            download = None
            click_started_at = time.time() - 5
            try:
                with page.expect_download(timeout=timeout_ms) as download_info:
                    click_started_at = time.time() - 5
                    click_backend_export(
                        page,
                        export_selector=export_selector,
                        export_text=export_text,
                        timeout_ms=timeout_ms,
                    )
                download = download_info.value
            except PlaywrightTimeoutError:
                downloaded_path = find_recent_workbook(
                    export_workbook_search_dirs(target_dir),
                    since_epoch=click_started_at,
                )
                if downloaded_path is not None:
                    return downloaded_path
                if not completed_download.get("file_url"):
                    log_export_page_diagnostics(
                        page,
                        search_dirs=export_workbook_search_dirs(target_dir),
                        observed_responses=observed_responses,
                    )
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


def fetch_backend_aweme_records_via_bind_list_api(*, cdp_url: str | None = None) -> list[dict[str, Any]]:
    resolved_cdp_url = (cdp_url if cdp_url is not None else os.getenv("BROWSER_CDP_URL", "")).strip()
    if not resolved_cdp_url:
        raise BrowserExportError("BROWSER_CDP_URL is required when workbook_path is not provided.")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserExportError("Install playwright before running browser exports.") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(resolve_playwright_cdp_url(resolved_cdp_url))
        context = browser.contexts[0] if browser.contexts else browser.new_context(accept_downloads=True)
        page = context.pages[0] if context.pages else context.new_page()
        bind_list_url = discover_backend_aweme_bind_list_url(page)
        if not bind_list_url:
            raise BrowserExportError("Backend aweme bind list API URL was not observed after export download timeout.")
        records = fetch_backend_aweme_bind_list_records(page, bind_list_url)
        print(
            f"[backend-aweme-export] bind_list_api_fallback fetched={len(records)}",
            flush=True,
        )
        return records


def discover_backend_aweme_bind_list_url(page: Any) -> str | None:
    urls = page.evaluate(
        """
        () => performance.getEntriesByType('resource')
          .map((entry) => entry.name || '')
          .filter((url) => url.includes('/life/merchant/v1/integration-user/bind/list'))
          .slice(-5)
        """
    )
    if not isinstance(urls, list):
        return None
    for url in reversed(urls):
        if isinstance(url, str) and BACKEND_AWEME_BIND_LIST_PATH in url:
            return url
    return None


def fetch_backend_aweme_bind_list_records(page: Any, bind_list_url: str) -> list[dict[str, Any]]:
    parsed = urlparse(bind_list_url)
    params = {
        key: values[-1] if values else ""
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
    }
    params["page"] = "1"
    params["size"] = str(BIND_LIST_PAGE_SIZE)
    base_url = urlunparse(parsed._replace(query=""))

    first = fetch_backend_aweme_bind_list_page(page, base_url, params)
    total = _safe_int(first.get("Total"), 0)
    items = list(first.get("integration_info") or [])
    page_count = max(1, (total + BIND_LIST_PAGE_SIZE - 1) // BIND_LIST_PAGE_SIZE) if total else 1
    max_pages = _safe_int(os.getenv("BACKEND_AWEME_BIND_LIST_MAX_PAGES"), 100)
    if page_count > max_pages:
        raise BrowserExportError(f"Backend aweme bind list page count {page_count} exceeds limit {max_pages}.")

    for page_number in range(2, page_count + 1):
        params["page"] = str(page_number)
        payload = fetch_backend_aweme_bind_list_page(page, base_url, params)
        items.extend(payload.get("integration_info") or [])

    return records_from_backend_aweme_api_items(items)


def fetch_backend_aweme_bind_list_page(page: Any, base_url: str, params: dict[str, str]) -> dict[str, Any]:
    url = f"{base_url}?{urlencode(params)}"
    payload = page.evaluate(
        """
        async (url) => {
          const response = await fetch(url, { credentials: 'include' });
          const text = await response.text();
          let json = {};
          try {
            json = text ? JSON.parse(text) : {};
          } catch (error) {
            return { __http_status: response.status, __parse_error: String(error), __body: text.slice(0, 300) };
          }
          json.__http_status = response.status;
          return json;
        }
        """,
        url,
    )
    if not isinstance(payload, dict):
        raise BrowserExportError("Backend aweme bind list API returned a non-object payload.")
    if payload.get("__http_status") != 200:
        raise BrowserExportError(f"Backend aweme bind list API failed with HTTP {payload.get('__http_status')}.")
    status_code = payload.get("status_code")
    if status_code not in {0, "0", None}:
        raise BrowserExportError(f"Backend aweme bind list API returned status_code={status_code}.")
    return payload


def records_from_backend_aweme_api_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in items:
        content = item.get("integration_content") or {}
        user_info = content.get("user_info") or {}
        subject_info = content.get("subject_info") or {}
        bind_form = content.get("bind_form") or {}
        account_id = _text(item.get("account_id") or user_info.get("user_id"))
        scene_id = _text(item.get("scene_id"))
        record = {
            "douyin_nickname": _text(user_info.get("nickname") or bind_form.get("nick_name")),
            "douyin_id": _text(user_info.get("aweme_id")),
            "account_id": account_id,
            "account_name": _text(user_info.get("account_name") or item.get("scene_name") or bind_form.get("nick_name")),
            "poi_id": scene_id if scene_id and scene_id != account_id else None,
            "certified_subject_name": _text(subject_info.get("company_name")),
            "binding_status": backend_aweme_api_binding_status(item, user_info),
            "raw_payload": item,
        }
        if any(record[key] for key in ("douyin_nickname", "douyin_id", "account_id", "poi_id")):
            records.append(record)
    return records


def backend_aweme_api_binding_status(item: dict[str, Any], user_info: dict[str, Any]) -> str:
    status = item.get("status", user_info.get("integration_status"))
    if str(status) == "1":
        return "active"
    if str(status) == "6":
        return "rejected"
    return "inactive"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def export_workbook_search_dirs(target_dir: Path) -> list[Path]:
    candidates: list[str | Path | None] = [
        target_dir,
        os.getenv("BROWSER_EXPORT_RUN_DIR"),
        os.getenv("BROWSER_EXPORT_DOWNLOAD_DIR"),
        os.getenv("BROWSER_EXPORT_ARTIFACT_DIR"),
        Path.home() / "Downloads",
    ]
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate is None or not str(candidate).strip():
            continue
        resolved = Path(candidate).expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def find_recent_workbook(search_dirs: list[Path], *, since_epoch: float) -> Path | None:
    newest_path: Path | None = None
    newest_mtime = since_epoch
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        paths = [search_dir] if search_dir.is_file() else search_dir.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in WORKBOOK_EXTENSIONS:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size <= 0 or stat.st_mtime < since_epoch:
                continue
            if stat.st_mtime >= newest_mtime:
                newest_mtime = stat.st_mtime
                newest_path = path
    return newest_path


def is_relevant_export_response(url: str) -> bool:
    lowered = url.lower()
    return any(
        keyword in lowered
        for keyword in (
            "download",
            "export",
            "excel",
            "xlsx",
            "bc_manage",
            "aweme",
            "douyin",
            "account",
        )
    )


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.query:
        return url
    return urlunparse(parsed._replace(query="<redacted>"))


def log_export_page_diagnostics(
    page: Any,
    *,
    search_dirs: list[Path],
    observed_responses: list[dict[str, Any]] | None = None,
) -> None:
    try:
        page_state = page.evaluate(
            """
            () => ({
              url: location.href,
              title: document.title,
              clickableTexts: Array.from(document.querySelectorAll('button,a,[role="button"]'))
                .map((node) => (node.innerText || node.textContent || '').trim())
                .filter(Boolean)
                .slice(0, 40),
              dialogTexts: Array.from(document.querySelectorAll('[role="dialog"], .byted-modal, .semi-modal, .arco-modal'))
                .map((node) => (node.innerText || node.textContent || '').trim().slice(0, 300))
                .filter(Boolean)
                .slice(0, 5),
            })
            """
        )
    except Exception as exc:
        page_state = {"diagnostic_error": str(exc)}

    files: list[dict[str, Any]] = []
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        try:
            paths = [search_dir] if search_dir.is_file() else sorted(
                search_dir.rglob("*"),
                key=lambda path: path.stat().st_mtime if path.exists() else 0,
                reverse=True,
            )[:20]
        except OSError:
            continue
        for path in paths:
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            files.append({"path": str(path), "size": stat.st_size, "mtime": stat.st_mtime})
    print(
        "[backend-aweme-export] diagnostic "
        + json.dumps(
            {
                "page": page_state,
                "download_files": files[:30],
                "observed_responses": observed_responses or [],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


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

    timeout_seconds = float(os.getenv("BROWSER_CDP_READY_TIMEOUT_SECONDS", "120"))
    deadline = time.monotonic() + max(timeout_seconds, 0)
    last_error: Exception | None = None
    version_url = f"{cdp_url.rstrip('/')}/json/version"

    while True:
        try:
            with urlopen(version_url, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            websocket_url = str(payload.get("webSocketDebuggerUrl") or "")
            if websocket_url:
                return normalize_cdp_websocket_url(cdp_url, websocket_url)
            last_error = BrowserExportError(f"Browser CDP endpoint at {cdp_url} did not return a websocket URL.")
        except (OSError, URLError, json.JSONDecodeError) as exc:
            last_error = exc

        if time.monotonic() >= deadline:
            raise BrowserExportError(f"Unable to inspect browser CDP endpoint at {cdp_url}.") from last_error
        time.sleep(1)


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


def _binding_key(
    account_id: str | None,
    douyin_id: str | None,
    poi_id: str | None,
    binding_status: str | None,
    account_type: Any,
) -> str:
    return ":".join(str(part) if part not in {None, ""} else "-" for part in (account_id, douyin_id, poi_id, binding_status, account_type))


def is_active_binding_status(status: str | None) -> bool:
    return (status or "").strip().lower() not in INACTIVE_BINDING_STATUSES


def is_valid_poi_id(poi_id: str | None) -> bool:
    return bool(poi_id and str(poi_id).strip() not in {"0", "-1"})


def upsert_backend_store_poi_mapping(
    session: Session,
    *,
    store_id: str,
    poi_id: str,
    poi_name: str | None,
) -> DimStorePoiMapping:
    existing = session.scalar(select(DimStorePoiMapping).where(DimStorePoiMapping.poi_id == poi_id).limit(1))
    if existing is not None:
        existing.store_id = store_id
        existing.poi_name = poi_name or existing.poi_name
        existing.mapping_source = "backend_aweme_export"
        existing.is_primary = True
        session.flush()
        return existing
    return upsert_store_poi_mapping(
        session,
        store_id,
        poi_id,
        poi_name=poi_name,
        mapping_source="backend_aweme_export",
        is_primary=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
