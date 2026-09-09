from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select

from apps.api.dy_api.models import DouyinRefundEvent, JobImpact, RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinRefundRecord, RawDouyinVerifyRecord
from apps.worker.collectors.orders import collect_orders
from apps.worker.collectors.refunds import collect_refunds
from apps.worker.collectors.types import CollectionWindow
from apps.worker.collectors.verify_records import collect_verify_records
from apps.worker.repositories import payload_fingerprint, upsert_raw_order


WINDOW = CollectionWindow(start=datetime(2026, 9, 8, tzinfo=timezone.utc), end=datetime(2026, 9, 9, tzinfo=timezone.utc), timezone_name="UTC")


class OrderClient:
    def __init__(self, created=(), updated=()):
        self.created, self.updated = created, updated

    def iter_orders(self, start, end):
        yield from self.created

    def iter_order_updates(self, start, end):
        yield from self.updated


def test_old_order_and_coupon_updates_survive_stale_replay_and_commit(db_session):
    old = {"order_id": "old-order", "order_status": "201", "create_order_time": 1700000000,
           "update_order_time": 1788800000,
           "certificate": [{"certificate_id": "old-coupon", "item_status": "100", "item_update_time": 1788800000}]}
    db_session.add(RawDouyinOrder(order_id="old-order", order_status="201", raw_payload=deepcopy(old)))
    db_session.flush()
    db_session.add(RawDouyinOrderCoupon(order_id="old-order", coupon_id="old-coupon", coupon_status="100", raw_payload=deepcopy(old["certificate"][0])))
    db_session.commit()
    new = deepcopy(old)
    new.update(order_status="1", update_order_time=1788886400)
    new["certificate"][0].update(item_status="301", item_update_time=1788886400)
    collect_orders(db_session, OrderClient(updated=[new]), WINDOW, source_run_id="new-version")
    db_session.commit()
    collect_orders(db_session, OrderClient(created=[old]), WINDOW, source_run_id="stale-replay")
    db_session.commit()
    db_session.expire_all()
    order = db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "old-order"))
    coupon = db_session.scalar(select(RawDouyinOrderCoupon).where(RawDouyinOrderCoupon.coupon_id == "old-coupon"))
    assert order.order_status == "1"
    assert coupon.coupon_status == "301"
    assert order.source_observed_at is not None
    assert coupon.source_observed_at is not None
    assert db_session.scalar(select(JobImpact).where(JobImpact.source_run_id == "new-version")) is not None
    assert db_session.scalar(select(JobImpact).where(JobImpact.source_run_id == "stale-replay")) is None


def test_undated_order_replay_cannot_replace_timestamped_status(db_session):
    new = {"order_id": "timed-order", "order_status": "1", "update_order_time": 1788886400}
    collect_orders(db_session, OrderClient(updated=[new]), WINDOW, source_run_id="timed")
    collect_orders(db_session, OrderClient(created=[{"order_id": "timed-order", "order_status": "201"}]), WINDOW, source_run_id="undated")
    db_session.commit()
    assert db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == "timed-order")).order_status == "1"


def test_verify_cancellation_updates_and_old_verify_does_not_restore(db_session):
    class VerifyClient:
        def __init__(self, row): self.row = row
        def query_verify_records(self, *args, **kwargs):
            return {"data": {"records": [self.row], "has_more": False}}
    old = {"verify_id": "v", "status": "valid", "verify_time": 1788800000, "poi_id": "p"}
    new = dict(old, status="cancelled", cancel_time=1788886400)
    collect_verify_records(db_session, VerifyClient(old), WINDOW, source_run_id="v1")
    collect_verify_records(db_session, VerifyClient(new), WINDOW, source_run_id="v2")
    db_session.commit()
    collect_verify_records(db_session, VerifyClient(old), WINDOW, source_run_id="v3")
    db_session.commit()
    row = db_session.scalar(select(RawDouyinVerifyRecord).where(RawDouyinVerifyRecord.verify_id == "v"))
    assert row.verify_status == "cancelled"
    assert row.cancel_time is not None


def test_refund_official_times_repair_identical_legacy_snapshot(db_session):
    class RefundClient:
        def iter_refunds(self, *args, **kwargs): yield payload
    upsert_raw_order(db_session, "refund-order")
    payload = {"after_sale_id": "as-official", "order_id": "refund-order", "status": 50,
               "refund_type": 1, "refund_amount_cent": 1234, "create_time": 1788800000,
               "update_time": 1788886401, "complete_time": 1788886400}
    observed = datetime.fromtimestamp(payload["update_time"], tz=timezone.utc)
    db_session.add(RawDouyinRefundRecord(source_record_key="as-official", refund_id="as-official",
                   order_id="refund-order", raw_refund_status="50", normalized_refund_status=2,
                   refund_amount_cent=1234, source_observed_at=observed,
                   payload_hash=payload_fingerprint(payload), raw_payload=deepcopy(payload)))
    db_session.commit()
    collect_refunds(db_session, RefundClient(), WINDOW, source_run_id="repair")
    db_session.commit()
    row = db_session.scalar(select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.refund_id == "as-official"))
    assert row.refund_applied_at.replace(tzinfo=timezone.utc).timestamp() == payload["create_time"]
    assert row.refund_completed_at.replace(tzinfo=timezone.utc).timestamp() == payload["complete_time"]
    event = db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == "as-official"))
    assert event is not None
    assert event.occurred_at.replace(tzinfo=timezone.utc).timestamp() == payload["complete_time"]
    assert event.refund_amount_cent == 1234

def test_equal_version_different_payload_is_flagged_not_hash_ordered(db_session):
    from apps.api.dy_api.models import DataQualityIssue
    candidates = [
        {'order_id': 'same-second', 'order_status': status, 'update_order_time': 1788886400}
        for status in ('201', '1')
    ]
    candidates.sort(key=payload_fingerprint)
    collect_orders(db_session, OrderClient(updated=[candidates[0]]), WINDOW, source_run_id='first')
    collect_orders(db_session, OrderClient(updated=[candidates[1]]), WINDOW, source_run_id='conflicting')
    db_session.commit()
    row = db_session.scalar(select(RawDouyinOrder).where(RawDouyinOrder.order_id == 'same-second'))
    assert row.order_status == candidates[0]['order_status']
    issue = db_session.scalar(select(DataQualityIssue).where(DataQualityIssue.issue_type == 'source_version_conflict'))
    assert issue is not None

def test_legacy_coupon_later_refund_fact_is_not_overwritten(db_session):
    from apps.worker.repositories import upsert_order_coupon
    upsert_raw_order(db_session, 'fact-order')
    db_session.add(RawDouyinOrderCoupon(
        order_id='fact-order', coupon_id='fact-coupon', coupon_status='301',
        latest_refund_at=datetime.fromtimestamp(1789000000, tz=timezone.utc),
        raw_payload={'item_update_time': 1788800000},
    ))
    db_session.commit()
    upsert_order_coupon(
        db_session, 'fact-coupon', 'fact-order', coupon_status='100',
        source_observed_at=datetime.fromtimestamp(1788886400, tz=timezone.utc),
        observation_key='source:older', raw_payload={'item_update_time': 1788886400},
    )
    db_session.commit()
    row = db_session.scalar(select(RawDouyinOrderCoupon).where(RawDouyinOrderCoupon.coupon_id == 'fact-coupon'))
    assert row.coupon_status == '301'

def test_verify_equal_time_conflict_uses_verify_primary_key(db_session):
    from apps.api.dy_api.models import DataQualityIssue
    class VerifyClient:
        def __init__(self, status): self.status = status
        def query_verify_records(self, *args, **kwargs):
            return {'data': {'records': [{'verify_id': 'same-verify', 'status': self.status, 'verify_time': 1788800000, 'poi_id': 'p'}], 'has_more': False}}
    collect_verify_records(db_session, VerifyClient('valid'), WINDOW, source_run_id='initial')
    collect_verify_records(db_session, VerifyClient('cancelled'), WINDOW, source_run_id='conflict')
    db_session.commit()
    assert db_session.scalar(select(RawDouyinVerifyRecord).where(RawDouyinVerifyRecord.verify_id == 'same-verify')).verify_status == 'valid'
    assert db_session.scalar(select(DataQualityIssue).where(DataQualityIssue.issue_type == 'source_version_conflict')) is not None


def test_newer_refund_snapshot_does_not_clear_or_backdate_times(db_session):
    class RefundClient:
        def iter_refunds(self, *args, **kwargs): yield payload
    upsert_raw_order(db_session, 'preserved-refund-order')
    payload = {'after_sale_id': 'preserved-as', 'order_id': 'preserved-refund-order', 'status': 50,
               'refund_type': 1, 'refund_amount_cent': 1234, 'create_time': 1788800000,
               'update_time': 1788886401, 'complete_time': 1788886400}
    collect_refunds(db_session, RefundClient(), WINDOW, source_run_id='initial-refund')
    db_session.commit()
    payload = dict(payload, update_time=1788886500)
    del payload['complete_time']
    del payload['create_time']
    collect_refunds(db_session, RefundClient(), WINDOW, source_run_id='missing-times')
    db_session.commit()
    payload = dict(payload, update_time=1788886600, complete_time=1788800001)
    collect_refunds(db_session, RefundClient(), WINDOW, source_run_id='earlier-time')
    db_session.commit()
    row = db_session.scalar(select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.refund_id == 'preserved-as'))
    assert row.refund_applied_at.replace(tzinfo=timezone.utc).timestamp() == 1788800000
    assert row.refund_completed_at.replace(tzinfo=timezone.utc).timestamp() == 1788886400
    event = db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == 'preserved-as'))
    assert event.occurred_at.replace(tzinfo=timezone.utc).timestamp() == 1788886400

def test_pending_refund_preserves_refund_created_at_alias(db_session):
    class RefundClient:
        def iter_refunds(self, *args, **kwargs):
            yield {'after_sale_id': 'alias-as', 'order_id': 'alias-order', 'status': 10,
                   'refund_type': 1, 'refund_amount_cent': 1234,
                   'refund_created_at': 1788800000, 'update_time': 1788800001}
    upsert_raw_order(db_session, 'alias-order')
    collect_refunds(db_session, RefundClient(), WINDOW, source_run_id='alias-refund')
    db_session.commit()
    event = db_session.scalar(select(DouyinRefundEvent).where(DouyinRefundEvent.refund_event_id == 'alias-as'))
    assert event.occurred_at.replace(tzinfo=timezone.utc).timestamp() == 1788800000


def test_refund_same_version_and_legacy_stale_payload_keep_success(db_session):
    from apps.api.dy_api.models import DataQualityIssue
    class RefundClient:
        def iter_refunds(self, *args, **kwargs): yield payload
    upsert_raw_order(db_session, 'guard-refund-order')
    original = {'after_sale_id': 'guard-as', 'order_id': 'guard-refund-order', 'status': 50,
                'refund_type': 1, 'refund_amount_cent': 1234, 'create_time': 1788800000,
                'update_time': 1788886401, 'complete_time': 1788886400}
    payload = deepcopy(original)
    collect_refunds(db_session, RefundClient(), WINDOW, source_run_id='success')
    db_session.commit()
    payload = dict(original, status=10)
    collect_refunds(db_session, RefundClient(), WINDOW, source_run_id='same-second-refund')
    db_session.commit()
    row = db_session.scalar(select(RawDouyinRefundRecord).where(RawDouyinRefundRecord.refund_id == 'guard-as'))
    assert row.normalized_refund_status == 2
    assert db_session.scalar(select(DataQualityIssue).where(DataQualityIssue.issue_type == 'refund_source_version_conflict')) is not None
    row.source_observed_at = None
    db_session.commit()
    payload = dict(original, status=10, update_time=1788800001)
    del payload['complete_time']
    collect_refunds(db_session, RefundClient(), WINDOW, source_run_id='legacy-stale-refund')
    db_session.commit()
    assert row.normalized_refund_status == 2
    assert row.raw_payload == original
