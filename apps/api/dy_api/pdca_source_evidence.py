"""Bounded raw evidence reads for PDCA; no calculation or source mutation."""
import base64
import binascii
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json

from sqlalchemy import or_, select, tuple_
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DimSkuProductRule, DimStorePoiMapping, RawDouyinOrder, RawDouyinOrderCoupon,
    RawDouyinRefundRecord, RawDouyinVerifyRecord,
)
from dy_api.pdca_source_schema import (
    CouponRow, EvidencePage, OrderRow, PoiRow, RefundRow, SkuRow, VerificationRow,
)

PROJECTIONS = {
    'orders': (RawDouyinOrder, OrderRow, ('order_id',)),
    'coupons': (RawDouyinOrderCoupon, CouponRow, ('coupon_id',)),
    'verifications': (RawDouyinVerifyRecord, VerificationRow, ('verify_id',)),
    'refunds': (RawDouyinRefundRecord, RefundRow, ('source_record_key',)),
    'sku_rules': (DimSkuProductRule, SkuRow, ('sku_id',)),
    'poi_mappings': (DimStorePoiMapping, PoiRow, ('store_id', 'poi_id')),
}
SCHEMA_VERSION = 'pdca-source-observation-v1'


def read_pdca_page(session: Session, *, dataset: str, period_start: date, period_end: date,
                   observed_through: datetime, page_size: int = 500, cursor: str | None = None) -> EvidencePage:
    """Read current observations for a creation-date cohort, retaining unknowns."""
    now = datetime.now(timezone.utc)
    if dataset not in PROJECTIONS or not 1 <= page_size <= 500:
        raise ValueError('Invalid dataset or page size')
    if not 0 <= (period_end - period_start).days < 7 or observed_through.tzinfo is None:
        raise ValueError('Invalid date range or timezone')
    local = timezone(timedelta(hours=8))
    start = datetime.combine(period_start, time.min, local).astimezone(timezone.utc)
    end = datetime.combine(period_end + timedelta(days=1), time.min, local).astimezone(timezone.utc)
    cutoff = observed_through.astimezone(timezone.utc)
    if not start <= cutoff <= now:
        raise ValueError('Invalid observation cutoff')
    fingerprint = hashlib.sha256(json.dumps([SCHEMA_VERSION, dataset, start.isoformat(),
                                             end.isoformat(), cutoff.isoformat()]).encode()).hexdigest()
    rules = select(DimSkuProductRule.sku_id).where(DimSkuProductRule.product_scope == '精诚养车')
    orders = select(RawDouyinOrder.order_id).where(
        RawDouyinOrder.sku_id.in_(rules), RawDouyinOrder.create_order_time >= start,
        RawDouyinOrder.create_order_time < end, RawDouyinOrder.create_order_time <= cutoff)
    model, schema, key_names = PROJECTIONS[dataset]
    columns = [getattr(model, field) for field in schema.model_fields if field != 'kind' and hasattr(model, field)]
    keys = [getattr(model, key) for key in key_names]
    statement = select(*columns)
    if dataset == 'orders':
        statement = statement.where(model.order_id.in_(orders))
    elif dataset in {'coupons', 'refunds'}:
        statement = statement.where(model.order_id.in_(orders))
    elif dataset == 'verifications':
        coupons = select(RawDouyinOrderCoupon.coupon_id).where(RawDouyinOrderCoupon.order_id.in_(orders))
        statement = statement.where(model.coupon_id.in_(coupons),
                                    or_(model.verify_time <= cutoff, model.verify_time.is_(None)))
    elif dataset == 'sku_rules':
        statement = statement.where(model.product_scope == '精诚养车')
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or not 0 < len(cursor) <= 2048:
                raise ValueError()
            token = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
            after = token.get('after') if isinstance(token, dict) else None
            if (not isinstance(token, dict) or token.get('context') != fingerprint
                    or not isinstance(after, list) or len(after) != len(keys)
                    or any(not isinstance(value, str) or not 0 < len(value) <= 512 for value in after)):
                raise ValueError()
        except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
            raise ValueError('Invalid cursor for this query') from None
        statement = statement.where(tuple_(*keys) > tuple_(*after))
    with session.no_autoflush:
        raw_rows = list(session.execute(statement.order_by(*keys).limit(page_size + 1)).mappings())
    more = len(raw_rows) > page_size
    raw_rows = raw_rows[:page_size]
    next_cursor = None
    if more:
        next_cursor = base64.urlsafe_b64encode(json.dumps({
            'context': fingerprint, 'after': [str(raw_rows[-1][key]) for key in key_names]
        }).encode()).decode()
    rows = []
    for raw in raw_rows:
        values = dict(raw)
        # SQLite test storage loses tzinfo; production PostgreSQL preserves it.
        if session.get_bind().dialect.name == 'sqlite':
            values = {key: value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value
                      for key, value in values.items()}
        rows.append(schema(**values))
    return EvidencePage(data={'rows': rows, 'next_cursor': next_cursor, 'has_more': more}, meta={
        'schema_version': SCHEMA_VERSION, 'dataset': dataset, 'query_fingerprint': fingerprint,
        'period_start': start, 'period_end_exclusive': end, 'observed_through': cutoff, 'generated_at': now,
        'scope': 'current_dimensions' if dataset in {'sku_rules', 'poi_mappings'} else 'order_creation_current_whitelist',
        'limitations': [
            'Current source rows and current SKU rules, not immutable historical snapshots.',
            'Missing creation dates, unknown SKU mappings and unlinked events are not proven covered.',
            'Observation cutoff filters order/verification event times; refunds and cancellations are current state, not historical replay.',
            'Collection completeness and amount-field equivalence to export are unverified; do not replace the PDCA primary source.',
            'Refund reasons are unavailable; no raw payload is exported.',
        ]})
