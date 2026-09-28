"""Generate JSON schemas and a synthetic example; never open a source database."""
from datetime import datetime, timezone
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    Base, DimSkuProductRule, DouyinRefundEvent, RawDouyinOrder,
    RawDouyinOrderCoupon, RawDouyinVerifyRecord,
)
from dy_api.pdca_snapshot_projection import project_snapshot
from dy_api.pdca_snapshot_schema import SnapshotManifest, SnapshotPage
from dy_api.pdca_snapshot_store import SnapshotStore


def main():
    destination = Path(__file__).resolve().parents[1] / 'docs/api'
    for name, schema in [('manifest', SnapshotManifest), ('page', SnapshotPage)]:
        (destination / f'pdca-event-{name}.schema.json').write_text(
            json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 2, tzinfo=timezone.utc)
    cutoff = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add(DimSkuProductRule(sku_id='SYNTHETIC-SKU', product_scope='精诚养车'))
        session.add(RawDouyinOrder(order_id='SYNTHETIC-ORDER', sku_id='SYNTHETIC-SKU',
            create_order_time=start, pay_time=start, order_status='201',
            raw_payload={'receipt_amount': 16000, 'discount_amount': 800,
                         'discounts': [{'platform_discount_amount': 800}]}))
        session.flush()
        session.add(RawDouyinOrderCoupon(order_id='SYNTHETIC-ORDER', coupon_id='SYNTHETIC-COUPON'))
        session.add(RawDouyinVerifyRecord(verify_id='SYNTHETIC-VERIFY', coupon_id='SYNTHETIC-COUPON',
            verify_status='1', verify_time=start))
        session.add(DouyinRefundEvent(refund_event_id='SYNTHETIC-REFUND', order_id='SYNTHETIC-ORDER',
            coupon_id='SYNTHETIC-COUPON', refund_type=1, refund_status=2,
            refund_amount_cent=1000, occurred_at=end, successful_observed_at=end))
        session.commit()
        datasets, sku_ids, rule_version = project_snapshot(session, start, end, cutoff)
    store = SnapshotStore()
    manifest = store.freeze('synthetic-client', datasets, start=start, end=end, cutoff=cutoff,
        sku_ids=sku_ids, explicit_scope=False, rule_version=rule_version, as_of=datetime.now(timezone.utc))
    pages = {dataset: store.page('synthetic-client', manifest.meta.snapshot_id, dataset).model_dump(mode='json')
             for dataset in datasets}
    example = {'synthetic_only': True, 'manifest': manifest.model_dump(mode='json'), 'pages': pages}
    (destination / 'pdca-event-synthetic-example.json').write_text(
        json.dumps(example, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    engine.dispose()


if __name__ == '__main__':
    main()
