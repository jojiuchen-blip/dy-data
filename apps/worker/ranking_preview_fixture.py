"""Synthetic acceptance inputs only; never run against a business database."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DimStore, DimStorePoiMapping, DimSkuProductRule, DimAwemeAccount,
    RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
    ClueMasterLead, ClueAssignmentRound, ClueFollowUpRecord,
)
from apps.api.dy_api.ranking_schema_v1 import org_history, eligibility

START = datetime(2026, 8, 31, 16, tzinfo=timezone.utc)  # Sept 1, Shanghai
END = datetime(2026, 9, 30, 16, tzinfo=timezone.utc)
AT = START + timedelta(days=1, hours=2)
CUTOFF = END + timedelta(days=1)
ELIGIBILITY_VERSION = "synthetic-eligibility-v1"


def seed_preview(session: Session) -> None:
    if session.bind.dialect.name != "sqlite":
        raise ValueError("synthetic seeder supports local SQLite only")
    for model in (DimStore, RawDouyinOrder, ClueAssignmentRound):
        if session.scalar(select(func.count()).select_from(model)):
            raise ValueError("refusing to seed a populated database")
    for store in "ABCD":
        session.add(DimStore(store_id=store, service_store_code="TEST-" + store,
                             store_name=f"虚拟门店{store}", is_active=True))
    session.flush()
    for store in "ABCD":
        session.add(DimStorePoiMapping(store_id=store, poi_id="TEST-POI-" + store, is_primary=True))
        for kind in ("store", "craftsman"):
            session.add(DimAwemeAccount(account_id=f"{store}-{kind}", store_id=store,
                                       nickname=f"虚拟{store}{kind}", binding_status="active"))
    session.add_all([DimSkuProductRule(sku_id="TEST-JC", product_id="TEST-JC", product_scope="精诚养车"),
                     DimSkuProductRule(sku_id="TEST-OTHER", product_scope="其他")])
    session.execute(org_history.insert(), [dict(mapping_version="synthetic-org-v1", store_id=store,
        service_store_code="TEST-" + store, store_name=f"虚拟门店{store}", effective_from=START,
        group_key="TEST-G", group_name="虚拟集团", service_center_key="TEST-C", service_center_name="虚拟中心",
        district_key="TEST-D", district_name="虚拟大区", area_key="TEST-A", area_name="虚拟区域",
        source_hash="synthetic") for store in "ABCD"])
    session.execute(eligibility.insert(), [dict(eligibility_version=ELIGIBILITY_VERSION,
        service_store_code="TEST-" + store, product_scope="精诚养车", effective_from=START,
        source_hash="synthetic") for store in "ABC"])
    for number in range(1, 11):
        store = "A" if number <= 4 else "B"
        kind = "craftsman" if number in {4, 9, 10} else "store"
        session.add(RawDouyinOrder(order_id=f"O{number}", sku_id="TEST-JC",
            owner_account_id=f"{store}-{kind}", sale_time=AT, pay_time=AT,
            sale_role="职人" if kind == "craftsman" else "商家",
            sale_channel=["直播", "短视频", "搜索", "商城", "其他"][number % 5],
            order_status="退款" if number == 10 else "已支付"))
    session.add(RawDouyinOrder(order_id="OTHER", sku_id="TEST-OTHER",
                               owner_account_id="A-store", sale_time=AT))
    for order in ("O1", "O2", "O3"):
        session.add(ClueMasterLead(lead_key="LEAD-" + order, source_clue_row_key="RAW-" + order,
                                  source_identity_key="IDENTITY-" + order, order_id=order))
    session.flush()
    specs = [("RA1", "O1", "A", 1), ("RA2", "O2", "A", 1), ("RB1", "O2", "B", 2)]
    specs += [(f"RB{i+1}", "O3", "B", i) for i in range(1, 8)]
    for rid, order, store, number in specs:
        session.add(ClueAssignmentRound(assignment_round_id=rid, lead_key="LEAD-" + order,
            order_id=order, assigned_store_id=store, assigned_at=AT, round_no=number,
            execution_mode="formal", round_status="active_unfollowed"))
    session.add(ClueAssignmentRound(assignment_round_id="TRIAL", lead_key="LEAD-O3", order_id="O3",
        assigned_store_id="A", assigned_at=AT, round_no=1, execution_mode="trial", round_status="active"))
    for fid, rid, order, store, hours, deleted in [
        ("F1", "RA1", "O1", "A", 1, False), ("F1DUP", "RA1", "O1", "A", 2, False),
        ("F2", "RA2", "O2", "A", 24, False), ("F3", "RB1", "O2", "B", 2, False),
        ("LATE", "RB2", "O3", "B", 25, False), ("DELETED", "RB3", "O3", "B", 1, True),
    ]:
        session.add(ClueFollowUpRecord(follow_up_record_id=fid, assignment_round_id=rid,
            order_id=order, round_no=1, assigned_store_id=store, follow_result="appointment",
            created_at=AT + timedelta(hours=hours), deleted_at=AT + timedelta(hours=2) if deleted else None))
    session.flush()
    for coupon, order in [("C1", "O1"), ("C2", "O2"), ("C2B", "O2"), ("C3", "O3"), ("C4", "O4")]:
        session.add(RawDouyinOrderCoupon(coupon_id=coupon, order_id=order))
    session.flush()
    for vid, coupon, store, canceled in [
        ("V1", "C1", "A", False), ("V2", "C2", "B", False), ("V2B", "C2B", "B", False),
        ("V3", "C3", "B", True), ("NATURAL", "C4", "B", False),
    ]:
        session.add(RawDouyinVerifyRecord(verify_id=vid, coupon_id=coupon, verify_status="success",
            poi_id="TEST-POI-" + store, sku_id="TEST-JC", verify_time=AT + timedelta(days=2),
            cancel_time=AT + timedelta(days=3) if canceled else None))
    session.flush()
