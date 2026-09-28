"""Process-local, expiring immutable evidence. No database/filesystem writes."""
import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
from threading import Lock, Semaphore
import time

from dy_api.pdca_snapshot_schema import SnapshotManifest, SnapshotMeta, SnapshotPage

TTL_SECONDS = 600
MAX_SNAPSHOTS = 4
BUILD_SLOT = Semaphore(1)
_CURSOR_KEY = secrets.token_bytes(32)


class SnapshotGoneError(Exception):
    """Expired, wrong owner or process; never reconstruct under the old ID."""


class SnapshotBusyError(Exception):
    """Capacity is exhausted; do not evict a valid client snapshot."""


@dataclass(frozen=True)
class FrozenSnapshot:
    owner: str
    deadline: float
    manifest_json: str
    rows: dict[str, tuple[str, ...]]


class SnapshotStore:
    def __init__(self):
        self._lock = Lock()
        self._snapshots = {}

    def _expire(self):
        now = time.monotonic()
        self._snapshots = {key: value for key, value in self._snapshots.items() if value.deadline > now}

    def check_capacity(self):
        with self._lock:
            self._expire()
            if len(self._snapshots) >= MAX_SNAPSHOTS:
                raise SnapshotBusyError()

    def freeze(self, owner, datasets, *, start, end, cutoff, sku_ids, explicit_scope, rule_version, as_of, quality_issue_scope="related_batches"):
        snapshot_id = secrets.token_urlsafe(32)
        summaries = [dict(dataset=name, row_count=len(rows),
                          sha256=hashlib.sha256('\n'.join(rows).encode()).hexdigest())
                     for name, rows in datasets.items()]
        manifest = SnapshotManifest(data={'datasets': summaries}, meta=SnapshotMeta(
            snapshot_id=snapshot_id, as_of=as_of,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS),
            period_start=start, period_end_exclusive=end, observed_through=cutoff,
            sku_ids=sku_ids, scope_basis='explicit_sku_ids' if explicit_scope else 'current_sku_rules',
            rule_version=rule_version, quality_issue_scope=quality_issue_scope, blocking_reasons=(['batch_only_quality_issues_excluded'] if quality_issue_scope == 'cohort' else []) + [
                'collection_watermark_unknown', 'event_history_incomplete',
                'order_receipt_semantics_unverified', 'purchase_quantity_unavailable',
                'unlinked_or_missing_date_records_not_proven_covered',
                'historical_status_and_dimension_versions_unavailable',
            ]))
        entry = FrozenSnapshot(owner, time.monotonic() + TTL_SECONDS, manifest.model_dump_json(), dict(datasets))
        with self._lock:
            self._expire()
            if len(self._snapshots) >= MAX_SNAPSHOTS:
                raise SnapshotBusyError()
            self._snapshots[snapshot_id] = entry
        return manifest

    def page(self, owner, snapshot_id, dataset, page_size=500, cursor=None):
        with self._lock:
            self._expire()
            entry = self._snapshots.get(snapshot_id)
        if entry is None or not hmac.compare_digest(entry.owner.encode(), owner.encode()):
            raise SnapshotGoneError()
        if dataset not in entry.rows or type(page_size) is not int or not 1 <= page_size <= 500:
            raise ValueError('Invalid dataset/page size')
        rows = entry.rows[dataset]
        offset = 0 if cursor is None else _decode_cursor(cursor, snapshot_id, dataset, len(rows))
        end = min(offset + page_size, len(rows))
        more = end < len(rows)
        manifest = SnapshotManifest.model_validate_json(entry.manifest_json)
        summary = next(item for item in manifest.data.datasets if item.dataset == dataset)
        return SnapshotPage(meta=manifest.meta, data=dict(
            dataset=dataset, total_rows=len(rows), dataset_sha256=summary.sha256,
            rows=[json.loads(row) for row in rows[offset:end]], has_more=more,
            next_cursor=_encode_cursor(snapshot_id, dataset, end) if more else None))


def _encode_cursor(snapshot_id, dataset, offset):
    body = json.dumps([snapshot_id, dataset, offset], separators=(',', ':')).encode()
    signature = hmac.digest(_CURSOR_KEY, body, 'sha256')
    return base64.urlsafe_b64encode(signature + body).decode()


def _decode_cursor(cursor, snapshot_id, dataset, total):
    try:
        if not isinstance(cursor, str) or not 0 < len(cursor) <= 2048:
            raise ValueError()
        decoded = base64.b64decode(cursor, altchars=b'-_', validate=True)
        signature, body = decoded[:32], decoded[32:]
        if not hmac.compare_digest(signature, hmac.digest(_CURSOR_KEY, body, 'sha256')):
            raise ValueError()
        identity, source, offset = json.loads(body)
        if identity != snapshot_id or source != dataset or type(offset) is not int or not 0 <= offset < total:
            raise ValueError()
        return offset
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
        raise ValueError('Invalid snapshot cursor') from None


STORE = SnapshotStore()
