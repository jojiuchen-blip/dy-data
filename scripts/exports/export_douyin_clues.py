from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import douyin_account_id, douyin_app_id, douyin_app_secret
from src.dy_data.douyin_client import DouyinCredentials, DouyinOpenApiClient


DEFAULT_START = "2026-01-01 00:00:00"
DEFAULT_OUT_DIR = Path("local_exports/clues/2026")
PAGE_ITEM_LIMIT = 10_000
NEAR_PAGE_LIMIT_ROWS = 9_500
FIELD_COVERAGE_KEYS = [
    "clue_id",
    "create_time_detail",
    "modify_time",
    "name",
    "telephone",
    "enc_telephone",
    "weixin",
    "allocation_status",
    "follow_state_name",
    "clue_owner_name",
    "follow_life_account_id",
    "follow_life_account_name",
    "follow_poi_id",
    "intention_poi_id",
    "intention_life_account_name",
    "product_id",
    "product_name",
    "order_id",
    "content_id",
    "video_id",
    "ad_id",
    "advertiser_id",
    "leads_page",
    "flow_type",
    "flow_entrance",
    "tags",
    "system_tags",
    "remark",
    "remark_dict",
]


class ClueClient(Protocol):
    def query_clues(self, start: datetime, end: datetime, *, page: int, page_size: int) -> dict[str, Any]:
        ...


def parse_datetime(value: str) -> datetime:
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid datetime: {value}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.")


def default_end_time(now: datetime | None = None) -> datetime:
    return ((now or datetime.now()) - timedelta(minutes=10)).replace(microsecond=0)


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize_text(value: Any, *, secrets: list[str] | tuple[str, ...] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "[redacted]")
    return text[:1800]


def split_windows(start: datetime, end: datetime, *, window_hours: int) -> list[tuple[datetime, datetime]]:
    if start >= end:
        raise ValueError("start must be earlier than end.")
    if window_hours < 1:
        raise ValueError("window_hours must be at least 1.")

    windows: list[tuple[datetime, datetime]] = []
    current = start
    delta = timedelta(hours=window_hours)
    while current < end:
        window_end = min(current + delta, end)
        windows.append((current, window_end))
        current = window_end
    return windows


def window_filename(start: datetime, end: datetime) -> str:
    if (
        start.time() == datetime.min.time()
        and end.time() == datetime.min.time()
        and (end - start) >= timedelta(days=1)
    ):
        return f"clues_{start:%Y%m%d}_{end:%Y%m%d}.jsonl"
    return f"clues_{start:%Y%m%d%H%M%S}_{end:%Y%m%d%H%M%S}.jsonl"


def extract_clues(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return []
    for key in ("clue_data", "clues", "list", "records"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def extract_total(payload: dict[str, Any]) -> int | None:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    for key in ("total", "total_count", "count"):
        value = data.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    page = data.get("page")
    if isinstance(page, dict) and page.get("total") not in (None, ""):
        try:
            return int(page["total"])
        except (TypeError, ValueError):
            return None
    return None


def parse_source_time(value: Any) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return datetime.fromtimestamp(number)
    text = str(value).strip()
    if text.isdigit():
        return parse_source_time(int(text))
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def is_present(value: Any) -> bool:
    return value not in (None, "", [], {})


def fetch_window(
    client: ClueClient,
    start: datetime,
    end: datetime,
    *,
    page_size: int,
    max_pages: int | None,
    stop_if_near_limit: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page_limit = PAGE_ITEM_LIMIT // page_size
    if max_pages is not None:
        page_limit = min(page_limit, max_pages)
    page_limit = max(1, page_limit)

    records: list[dict[str, Any]] = []
    pages_fetched = 0
    max_page_seen = 0
    near_limit = False
    page = 1
    while page <= page_limit:
        payload = client.query_clues(start, end, page=page, page_size=page_size)
        items = extract_clues(payload)
        total = extract_total(payload)
        pages_fetched += 1
        max_page_seen = max(max_page_seen, page)
        records.extend(items)

        if total is not None and total >= NEAR_PAGE_LIMIT_ROWS:
            near_limit = True
            if stop_if_near_limit:
                break
        if len(records) >= NEAR_PAGE_LIMIT_ROWS or page >= max(1, int(page_limit * 0.95)):
            near_limit = True
        if len(items) < page_size:
            break
        page += 1

    if records and len(records) >= PAGE_ITEM_LIMIT:
        near_limit = True
    return records, {
        "pages_fetched": pages_fetched,
        "max_page_seen": max_page_seen,
        "near_limit": near_limit,
        "page_limit": page_limit,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp_path.replace(path)


def empty_summary(start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "export_started_at": utc_now_text(),
        "export_finished_at": None,
        "start_time": format_datetime(start),
        "end_time": format_datetime(end),
        "total_rows": 0,
        "unique_clue_ids": 0,
        "duplicate_clue_ids": 0,
        "daily_counts": {},
        "monthly_counts": {},
        "field_presence_counts": {field: {"present": 0, "missing": 0} for field in FIELD_COVERAGE_KEYS},
        "first_create_time": None,
        "last_create_time": None,
        "windows": [],
        "failed_windows": [],
        "pages_fetched": 0,
        "max_page_seen": 0,
        "near_page_limit_windows": [],
        "notes": [
            "Raw clue payloads are kept only in local JSONL files under the selected out_dir.",
            "Summary and console output intentionally omit phone-number values and raw payload bodies.",
        ],
    }


def write_summary(out_dir: Path, summary: dict[str, Any]) -> None:
    summary["export_finished_at"] = utc_now_text()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def update_summary_counts(
    summary: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    seen_clue_ids: set[str],
    create_times: list[datetime],
) -> None:
    for raw in records:
        summary["total_rows"] += 1
        clue_id = str(raw.get("clue_id") or "").strip()
        if clue_id:
            if clue_id in seen_clue_ids:
                summary["duplicate_clue_ids"] += 1
            seen_clue_ids.add(clue_id)

        created_at = parse_source_time(raw.get("create_time_detail"))
        if created_at:
            create_times.append(created_at)
            day_key = created_at.strftime("%Y-%m-%d")
            month_key = created_at.strftime("%Y-%m")
        else:
            day_key = "_missing_create_time"
            month_key = "_missing_create_time"
        summary["daily_counts"][day_key] = summary["daily_counts"].get(day_key, 0) + 1
        summary["monthly_counts"][month_key] = summary["monthly_counts"].get(month_key, 0) + 1

        for field in FIELD_COVERAGE_KEYS:
            bucket = "present" if is_present(raw.get(field)) else "missing"
            summary["field_presence_counts"][field][bucket] += 1

    summary["unique_clue_ids"] = len(seen_clue_ids)
    if create_times:
        summary["first_create_time"] = format_datetime(min(create_times))
        summary["last_create_time"] = format_datetime(max(create_times))


def export_clues(
    *,
    client: ClueClient | None,
    start: datetime,
    end: datetime,
    out_dir: str | Path,
    window_hours: int = 24,
    page_size: int = 100,
    max_pages: int | None = None,
    dry_run: bool = False,
    secrets: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    if page_size < 1 or page_size > 100:
        raise ValueError("page_size must be between 1 and 100.")

    out_path = Path(out_dir)
    summary = empty_summary(start, end)
    seen_clue_ids: set[str] = set()
    create_times: list[datetime] = []
    windows = split_windows(start, end, window_hours=window_hours)

    if dry_run:
        for window_start, window_end in windows:
            summary["windows"].append(
                {
                    "source_window_start": format_datetime(window_start),
                    "source_window_end": format_datetime(window_end),
                    "status": "dry_run",
                    "file": str(out_path / window_filename(window_start, window_end)),
                }
            )
        write_summary(out_path, summary)
        return summary

    if client is None:
        raise ValueError("client is required unless dry_run is true.")

    for window_start, window_end in windows:
        try:
            duration = window_end - window_start
            records, meta = fetch_window(
                client,
                window_start,
                window_end,
                page_size=page_size,
                max_pages=max_pages,
                stop_if_near_limit=duration > timedelta(hours=1),
            )
            summary["pages_fetched"] += meta["pages_fetched"]
            summary["max_page_seen"] = max(summary["max_page_seen"], meta["max_page_seen"])

            if meta["near_limit"] and duration > timedelta(hours=1):
                summary["near_page_limit_windows"].append(
                    {
                        "source_window_start": format_datetime(window_start),
                        "source_window_end": format_datetime(window_end),
                        "rows_seen_before_split": len(records),
                        "pages_seen_before_split": meta["pages_fetched"],
                        "action": "split_to_1h",
                    }
                )
                for hour_start, hour_end in split_windows(window_start, window_end, window_hours=1):
                    _export_single_window(
                        client,
                        hour_start,
                        hour_end,
                        out_path=out_path,
                        summary=summary,
                        page_size=page_size,
                        max_pages=max_pages,
                        secrets=secrets,
                        seen_clue_ids=seen_clue_ids,
                        create_times=create_times,
                    )
                write_summary(out_path, summary)
                continue

            _record_successful_window(
                records,
                window_start,
                window_end,
                out_path=out_path,
                summary=summary,
                meta=meta,
                seen_clue_ids=seen_clue_ids,
                create_times=create_times,
            )
        except Exception as exc:  # noqa: BLE001 - continue exporting independent windows.
            error = sanitize_text(exc, secrets=secrets)
            logging.warning(
                "Window failed: %s to %s: %s",
                format_datetime(window_start),
                format_datetime(window_end),
                error,
            )
            summary["failed_windows"].append(
                {
                    "source_window_start": format_datetime(window_start),
                    "source_window_end": format_datetime(window_end),
                    "error": error,
                }
            )
        write_summary(out_path, summary)
    return summary


def _export_single_window(
    client: ClueClient,
    window_start: datetime,
    window_end: datetime,
    *,
    out_path: Path,
    summary: dict[str, Any],
    page_size: int,
    max_pages: int | None,
    secrets: list[str] | tuple[str, ...],
    seen_clue_ids: set[str],
    create_times: list[datetime],
) -> None:
    try:
        records, meta = fetch_window(
            client,
            window_start,
            window_end,
            page_size=page_size,
            max_pages=max_pages,
            stop_if_near_limit=False,
        )
        summary["pages_fetched"] += meta["pages_fetched"]
        summary["max_page_seen"] = max(summary["max_page_seen"], meta["max_page_seen"])
        if meta["near_limit"]:
            summary["near_page_limit_windows"].append(
                {
                    "source_window_start": format_datetime(window_start),
                    "source_window_end": format_datetime(window_end),
                    "rows": len(records),
                    "pages": meta["pages_fetched"],
                    "action": "review_smaller_window",
                }
            )
        _record_successful_window(
            records,
            window_start,
            window_end,
            out_path=out_path,
            summary=summary,
            meta=meta,
            seen_clue_ids=seen_clue_ids,
            create_times=create_times,
        )
    except Exception as exc:  # noqa: BLE001 - continue with the next hour window.
        summary["failed_windows"].append(
            {
                "source_window_start": format_datetime(window_start),
                "source_window_end": format_datetime(window_end),
                "error": sanitize_text(exc, secrets=secrets),
            }
        )


def _record_successful_window(
    records: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    *,
    out_path: Path,
    summary: dict[str, Any],
    meta: dict[str, Any],
    seen_clue_ids: set[str],
    create_times: list[datetime],
) -> None:
    fetched_at = utc_now_text()
    wrapped_rows = [
        {
            "source_window_start": format_datetime(window_start),
            "source_window_end": format_datetime(window_end),
            "fetched_at": fetched_at,
            "raw_payload": record,
        }
        for record in records
    ]
    file_path = out_path / window_filename(window_start, window_end)
    write_jsonl(file_path, wrapped_rows)
    update_summary_counts(summary, records, seen_clue_ids=seen_clue_ids, create_times=create_times)
    summary["windows"].append(
        {
            "source_window_start": format_datetime(window_start),
            "source_window_end": format_datetime(window_end),
            "status": "ok",
            "rows": len(records),
            "pages_fetched": meta["pages_fetched"],
            "max_page_seen": meta["max_page_seen"],
            "file": str(file_path),
        }
    )
    logging.info(
        "Window exported: %s to %s, rows=%s, pages=%s, file=%s",
        format_datetime(window_start),
        format_datetime(window_end),
        len(records),
        meta["pages_fetched"],
        file_path,
    )


def build_client_from_config() -> tuple[DouyinOpenApiClient, list[str]]:
    app_id = douyin_app_id()
    app_secret = douyin_app_secret()
    account_id = douyin_account_id()
    missing = []
    if not app_id:
        missing.append("DOUYIN_APP_ID")
    if not app_secret:
        missing.append("DOUYIN_APP_SECRET")
    if not account_id:
        missing.append("DOUYIN_ACCOUNT_ID")
    if missing:
        raise RuntimeError("Missing required environment/config values: " + ", ".join(missing))
    credentials = DouyinCredentials(app_id=str(app_id), app_secret=str(app_secret), account_id=str(account_id))
    return DouyinOpenApiClient(credentials), [str(app_secret)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Douyin local-life CRM clues to local JSONL files.")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    args = parse_args(argv)
    start = parse_datetime(args.start)
    end = parse_datetime(args.end) if args.end else default_end_time()

    client: DouyinOpenApiClient | None = None
    secrets: list[str] = []
    if not args.dry_run:
        client, secrets = build_client_from_config()

    summary = export_clues(
        client=client,
        start=start,
        end=end,
        out_dir=args.out_dir,
        window_hours=args.window_hours,
        page_size=args.page_size,
        max_pages=args.max_pages,
        dry_run=args.dry_run,
        secrets=secrets,
    )
    print(
        json.dumps(
            {
                "summary_path": str(Path(args.out_dir) / "summary.json"),
                "total_rows": summary["total_rows"],
                "failed_windows": len(summary["failed_windows"]),
                "near_page_limit_windows": len(summary["near_page_limit_windows"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if summary["failed_windows"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
