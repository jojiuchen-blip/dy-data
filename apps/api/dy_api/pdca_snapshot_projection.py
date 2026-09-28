"""Bounded SELECT-only projections; no collector or metric code is invoked."""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json

from sqlalchemy import Text, case, cast, func, literal, or_, select, text
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DataQualityIssue, DimSkuProductRule, DimStorePoiMapping, DouyinRefundEvent,
    JobRun, JobStageRun, RawDouyinOrder, RawDouyinOrderCoupon,
    RawDouyinRefundRecord, RawDouyinVerifyRecord,
)
from dy_api import pdca_readonly_access
from dy_api.pdca_source_evidence import _receipt_evidence
from dy_api.pdca_source_schema import PoiRow, SkuRow
from dy_api.pdca_snapshot_schema import (
    CollectionBatch, CollectionStage, QualityIssue, RawRefund, RefundEvent,
    SnapshotCoupon, SnapshotOrder, VerificationEvent,
)

MAX_DATASET_ROWS = 20000
MAX_TOTAL_ROWS = 50000
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_CELL_CHARACTERS = 256 * 1024
COMPLETION_FIELDS = ('refund_completed_at', 'completed_at', 'finish_time', 'refund_done_at', 'complete_time')
# Version-frozen read-only interpretation of repositories._normalize_verify_status;
# no import of the mutating worker repository or change to its behavior.
VERIFIED_STATUSES = {'1', 'valid', 'verified', 'success', 'fulfilled', 'used', '已核销'}
REVOKED_STATUSES = {'2', 'cancelled', 'canceled', 'revoked', 'reversed', 'refunded', '已撤销'}


class SnapshotLimitError(Exception):
    """Refuse incomplete evidence instead of silently truncating."""


class SnapshotSourceError(Exception):
    """A coherent database read could not be established."""


def utc(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value


def validate_window(period_start: date, period_end: date, observed_through: datetime):
    if not 0 <= (period_end - period_start).days < 7 or observed_through.tzinfo is None:
        raise ValueError('Invalid window')
    local = timezone(timedelta(hours=8))
    start = datetime.combine(period_start, time.min, local).astimezone(timezone.utc)
    end = datetime.combine(period_end + timedelta(days=1), time.min, local).astimezone(timezone.utc)
    cutoff = utc(observed_through)
    if not start <= cutoff <= datetime.now(timezone.utc):
        raise ValueError('Invalid cutoff')
    return start, end, cutoff


@contextmanager
def snapshot_session():
    """Separate connection: isolation is set BEFORE the first data SELECT."""
    engine = pdca_readonly_access.get_engine()
    if engine is None or engine.dialect.name not in {'postgresql', 'sqlite'}:
        raise SnapshotSourceError()
    with engine.connect() as connection:
        previous = None
        try:
            if engine.dialect.name == 'postgresql':
                connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
                connection.execute(text("SET LOCAL statement_timeout = '8s'"))
                connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            else:
                previous = connection.scalar(text('PRAGMA query_only'))
                connection.execute(text('PRAGMA query_only = ON'))
                # pysqlite legacy mode does not start a snapshot on SELECT alone.
                connection.execute(text('BEGIN'))
            with Session(bind=connection, autoflush=False) as session:
                yield session
        finally:
            connection.rollback()
            if previous is not None:
                try:
                    connection.execute(text('PRAGMA query_only = ON' if previous else 'PRAGMA query_only = OFF'))
                    connection.rollback()
                except Exception:
                    connection.invalidate()
                    raise


def _columns(model, schema):
    return [getattr(model, name) for name in schema.model_fields
            if name != 'kind' and hasattr(model, name)]


def _rows(session, statement):
    rows, size = [], 0
    # Bound individual text/JSON cells inside the database BEFORE transferring
    # them. This includes the discounts projection discarded after arithmetic.
    bounded = statement.limit(MAX_DATASET_ROWS + 1).subquery()
    too_large = select(literal(1)).select_from(bounded).where(or_(
        *(func.length(cast(column, Text)) > MAX_CELL_CHARACTERS for column in bounded.c))).limit(1)
    if session.scalar(too_large) is not None:
        raise SnapshotLimitError()
    result = session.execute(statement.limit(MAX_DATASET_ROWS + 1).execution_options(
        stream_results=True, max_row_buffer=128))
    try:
        for source in result.mappings():
            row = {key: utc(value) for key, value in source.items()}
            size += len(json.dumps(row, default=str, ensure_ascii=False).encode())
            if len(rows) >= MAX_DATASET_ROWS or size > MAX_SNAPSHOT_BYTES:
                raise SnapshotLimitError()
            rows.append(row)
    finally:
        result.close()
    return rows


def _quality_rows(session, order_ids, coupon_ids, run_ids, scope):
    """Select bounded identifiers by each indexed link, then sort the union.

    Sorting a wide OR first can walk the whole primary-key index. Each branch
    stays in this transaction and raises on overflow; no partial union is used.
    """
    if scope not in {'cohort', 'related_batches'}:
        raise ValueError('Invalid quality scope')
    links = [(DataQualityIssue.order_id, order_ids),
             (DataQualityIssue.coupon_id, coupon_ids)]
    if scope == 'related_batches':
        links.append((DataQualityIssue.source_run_id, run_ids))
    identities = set()
    identity_bytes = 0
    for column, values in links:
        if not values:
            continue
        # Unordered LIMIT subsets may differ between the guard and stream query.
        # Bound the actual transfer too, without reintroducing a primary-key scan.
        bounded_id = case((func.length(DataQualityIssue.issue_id) <= MAX_CELL_CHARACTERS,
                           DataQualityIssue.issue_id), else_=None).label('issue_id')
        for row in _rows(session, select(bounded_id).where(column.in_(sorted(values)))):
            identity = row['issue_id']
            if identity is None:
                raise SnapshotLimitError()
            if identity not in identities:
                identities.add(identity)
                identity_bytes += len(identity.encode('utf-8'))
                if len(identities) > MAX_DATASET_ROWS or identity_bytes > MAX_SNAPSHOT_BYTES:
                    raise SnapshotLimitError()
    if not identities:
        return []
    return _rows(session, select(*_columns(DataQualityIssue, QualityIssue))
                 .where(DataQualityIssue.issue_id.in_(sorted(identities)))
                 .order_by(DataQualityIssue.issue_id))


def _json_field_type(session, model, key):
    if session.get_bind().dialect.name == 'sqlite':
        return func.json_type(model.raw_payload, '$.' + key)
    return func.jsonb_typeof(model.raw_payload[key])


def _event_id(verify_id, kind):
    return 'verify:' + sha256((verify_id + '\0' + kind).encode()).hexdigest()


def project_snapshot(session, start, end, cutoff, sku_ids=None, quality_issue_scope="related_batches"):
    """Freeze selected creation cohort, including all current statuses/events.

    Events after cutoff stay visible with a false cutoff flag. Late observations
    are not discarded, and no claim about knowledge at historical cutoff is made.
    """
    datasets = {}
    total_bytes = total_rows = 0

    def save(name, rows):
        nonlocal total_bytes, total_rows
        encoded = tuple(row.model_dump_json() for row in rows)
        total_bytes += sum(len(row.encode()) for row in encoded)
        total_rows += len(encoded)
        if (len(encoded) > MAX_DATASET_ROWS or total_rows > MAX_TOTAL_ROWS
                or total_bytes > MAX_SNAPSHOT_BYTES):
            raise SnapshotLimitError()
        datasets[name] = encoded

    rules_query = select(*_columns(DimSkuProductRule, SkuRow))
    if sku_ids is None:
        rules_query = rules_query.where(DimSkuProductRule.product_scope == '精诚养车')
    else:
        if not 1 <= len(sku_ids) <= 100 or any(not value or len(value) > 128 for value in sku_ids):
            raise ValueError('Invalid SKU scope')
        rules_query = rules_query.where(DimSkuProductRule.sku_id.in_(sku_ids))
    rules = _rows(session, rules_query.order_by(DimSkuProductRule.sku_id))
    selected_skus = sorted(set(sku_ids if sku_ids is not None else [row['sku_id'] for row in rules]))
    order_ids = select(RawDouyinOrder.order_id).where(
        RawDouyinOrder.sku_id.in_(selected_skus), RawDouyinOrder.create_order_time >= start,
        RawDouyinOrder.create_order_time < end, RawDouyinOrder.create_order_time <= cutoff)
    coupon_ids = select(RawDouyinOrderCoupon.coupon_id).where(RawDouyinOrderCoupon.order_id.in_(order_ids))
    columns = _columns(RawDouyinOrder, SnapshotOrder)
    for key in ('receipt_amount', 'discounts', 'discount_amount'):
        expression = RawDouyinOrder.raw_payload[key]
        if session.get_bind().dialect.name == 'sqlite':
            expression = case((func.json_type(RawDouyinOrder.raw_payload, '$.' + key).in_(['true', 'false']), None), else_=expression)
        columns.append(expression.label('_' + key))
    orders = _rows(session, select(*columns).where(RawDouyinOrder.order_id.in_(order_ids)).order_by(RawDouyinOrder.order_id))
    for row in orders:
        row.update(_receipt_evidence(row.pop('_receipt_amount'), row.pop('_discounts'), row.pop('_discount_amount')))
        row['payment_evidence'] = ('unknown' if row['pay_time'] is None else
                                   'paid_by_cutoff' if row['pay_time'] <= cutoff else 'paid_after_cutoff')
    save('orders', [SnapshotOrder(**row) for row in orders])
    coupons = _rows(session, select(*_columns(RawDouyinOrderCoupon, SnapshotCoupon))
                    .where(RawDouyinOrderCoupon.order_id.in_(order_ids)).order_by(RawDouyinOrderCoupon.coupon_id))
    save('coupons', [SnapshotCoupon(**row) for row in coupons])
    coupon_orders = {row['coupon_id']: row['order_id'] for row in coupons}
    verify_fields = 'verify_id coupon_id sku_id verify_status verify_time cancel_time poi_id source_run_id source_observed_at'.split()
    verifies = _rows(session, select(*(getattr(RawDouyinVerifyRecord, key) for key in verify_fields))
                     .where(RawDouyinVerifyRecord.coupon_id.in_(coupon_ids)).order_by(RawDouyinVerifyRecord.verify_id))
    verification_events = []
    for source in verifies:
        row = dict(source)
        verified, cancelled = row.pop('verify_time'), row.pop('cancel_time')
        status = str(row['verify_status'] or '').strip().lower().replace('-', '_')
        known = status in VERIFIED_STATUSES | REVOKED_STATUSES
        kind = 'verification' if known and verified is not None else 'unknown'
        identity = _event_id(row['verify_id'], kind)
        verification_events.append(VerificationEvent(**row, order_id=coupon_orders[row['coupon_id']],
            event_id=identity, event_type=kind, effective_at=verified,
            within_business_cutoff=None if verified is None or kind == 'unknown' else verified <= cutoff))
        if cancelled is not None or status in REVOKED_STATUSES:
            verification_events.append(VerificationEvent(**row, order_id=coupon_orders[row['coupon_id']],
                event_id=_event_id(row['verify_id'], 'revocation'), event_type='revocation',
                original_event_id=identity if kind == 'verification' else None, effective_at=cancelled,
                within_business_cutoff=None if cancelled is None else cancelled <= cutoff))
    save('verification_events', sorted(verification_events, key=lambda row: row.event_id))
    refunds = _rows(session, select(*_columns(DouyinRefundEvent, RefundEvent))
                    .where(DouyinRefundEvent.order_id.in_(order_ids)).order_by(DouyinRefundEvent.refund_event_id))
    for row in refunds:
        row['refund_scope'] = {1: 'partial', 2: 'full'}.get(row['refund_type'], 'unknown')
        row['effective_at'] = row['occurred_at'] if row['refund_status'] == 2 else None
        row['within_business_cutoff'] = None if row['effective_at'] is None else row['effective_at'] <= cutoff
    save('refund_events', [RefundEvent(**row) for row in refunds])
    refund_columns = _columns(RawDouyinRefundRecord, RawRefund)
    for key in ('refund_amount_cent', *COMPLETION_FIELDS):
        refund_columns.append(_json_field_type(session, RawDouyinRefundRecord, key).label('_type_' + key))
    raw_refunds = _rows(session, select(*refund_columns)
                       .where(RawDouyinRefundRecord.order_id.in_(order_ids)).order_by(RawDouyinRefundRecord.source_record_key))
    for row in raw_refunds:
        raw_type = row.pop('_type_refund_amount_cent')
        row['amount_field_type'] = {None: 'missing', 'integer': 'number', 'real': 'number',
                                    'text': 'string', 'true': 'boolean', 'false': 'boolean'}.get(raw_type, raw_type)
        row['completion_fields_present'] = [key for key in COMPLETION_FIELDS if row.pop('_type_' + key) is not None]
    save('raw_refunds', [RawRefund(**row) for row in raw_refunds])
    run_ids = {row.get('source_run_id') for rows in (orders, coupons, verifies, refunds, raw_refunds) for row in rows} - {None}
    jobs_query = select(*_columns(JobRun, CollectionBatch)).where(or_(
        JobRun.job_id.in_(run_ids),
        (JobRun.window_start <= cutoff) & (JobRun.window_end > start)))
    jobs = _rows(session, jobs_query.order_by(JobRun.job_id))
    save('collection_batches', [CollectionBatch(**row) for row in jobs])
    job_ids = [row['job_id'] for row in jobs]
    stages = _rows(session, select(*_columns(JobStageRun, CollectionStage))
                   .where(JobStageRun.job_id.in_(job_ids)).order_by(JobStageRun.stage_run_id))
    save('collection_stages', [CollectionStage(**row) for row in stages])
    issues = _quality_rows(session, {row['order_id'] for row in orders},
                           {row['coupon_id'] for row in coupons}, set(job_ids) | run_ids,
                           quality_issue_scope)
    save('quality_issues', [QualityIssue(**row) for row in issues])
    save('sku_rules', [SkuRow(**row) for row in rules])
    pois = _rows(session, select(*_columns(DimStorePoiMapping, PoiRow))
                 .order_by(DimStorePoiMapping.store_id, DimStorePoiMapping.poi_id))
    save('poi_mappings', [PoiRow(**row) for row in pois])
    rule_version = sha256(('\n'.join(datasets['sku_rules']) + '\n' + '\n'.join(selected_skus)).encode()).hexdigest()
    return datasets, selected_skus, rule_version
