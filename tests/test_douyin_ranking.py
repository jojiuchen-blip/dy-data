from __future__ import annotations

from datetime import datetime, timedelta, timezone

from openpyxl import Workbook

from apps.api.dy_api.models import (
    ClueAssignmentRound,
    ClueFollowUpRecord,
    DimAwemeAccount,
    DimStore,
    DimStoreOrgAssignment,
    DimStorePoiMapping,
    DimSkuProductRule,
    RawAwemeBinding,
    RawDouyinOrder,
    SettlementOrderDetail,
)
from apps.api.dy_api.douyin_ranking import build_douyin_ranking_report
from apps.worker.douyin_ranking import import_store_org_assignments


def test_import_store_org_assignments_is_idempotent_and_reports_conflicts(
    db_session, tmp_path
) -> None:
    workbook_path = tmp_path / "store-org.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["服务店编码", "服务店名称", "所属服务中心", "所属大区", "所属区域"])
    sheet.append(["SVC-001", "门店一", "中心一", "大区一", "区域一"])
    sheet.append(["SVC-001", "门店一", "中心一", "大区一", "区域一"])
    sheet.append(["SVC-001", "门店一", "中心二", "大区二", "区域二"])
    workbook.save(workbook_path)

    stats = import_store_org_assignments(db_session, workbook_path)
    assignment = db_session.get(DimStoreOrgAssignment, "SVC-001")

    assert stats == {
        "rows": 3,
        "updated": 1,
        "duplicates": 1,
        "conflicts": 1,
        "missing_code": 0,
        "deactivated": 0,
    }
    assert assignment is not None
    assert assignment.service_center_name == "中心一"
    assert assignment.district_name == "大区一"
    assert assignment.area_name == "区域一"


def test_import_store_org_assignments_accepts_business_csv_aliases_and_deactivates_missing(
    db_session, tmp_path
) -> None:
    csv_path = tmp_path / "门店_服务中心_大区_区域_映射表.csv"
    csv_path.write_text(
        "服务店编码,服务店名称,服务中心,大区,区域,所属集团,集团编码\n"
        "SVC-001,门店一,中心一,大区一,区域一,集团一,G-001\n",
        encoding="utf-8-sig",
    )
    first = import_store_org_assignments(db_session, csv_path)
    assert first["updated"] == 1
    assert first["deactivated"] == 0
    assert db_session.get(DimStoreOrgAssignment, "SVC-001").is_active is True
    assert db_session.get(DimStoreOrgAssignment, "SVC-001").group_name == "集团一"
    assert db_session.get(DimStoreOrgAssignment, "SVC-001").group_code == "G-001"

    second_path = tmp_path / "next.csv"
    second_path.write_text(
        "服务店编码,服务店名称,服务中心,大区,区域,所属集团,集团编码\n"
        "SVC-002,门店二,中心二,大区二,区域二,集团二,G-002\n",
        encoding="utf-8-sig",
    )
    second = import_store_org_assignments(db_session, second_path)
    assert second["deactivated"] == 1
    assert db_session.get(DimStoreOrgAssignment, "SVC-001").is_active is False


def test_ranking_orders_include_store_professional_accounts_and_all_channels(db_session) -> None:
    timestamp = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    db_session.add_all(
        [
            DimStore(
                store_id="store-a",
                store_name="门店 A",
                service_store_code="SVC-A",
                is_active=True,
            ),
            DimStore(
                store_id="store-b",
                store_name="门店 B",
                service_store_code="SVC-B",
                is_active=True,
            ),
            DimStoreOrgAssignment(
                service_store_code="SVC-A",
                service_center_name="中心一",
                district_name="大区一",
                area_name="区域一",
            ),
            DimStoreOrgAssignment(
                service_store_code="SVC-B",
                service_center_name="中心一",
                district_name="大区一",
                area_name="区域一",
            ),
            DimAwemeAccount(account_id="store-a-account", store_id="store-a", nickname="门店 A"),
            DimAwemeAccount(account_id="professional-a", store_id="store-a", nickname="职人 A"),
            DimAwemeAccount(account_id="professional-a-binding", nickname="职人 A2"),
            DimAwemeAccount(account_id="professional-b", store_id="store-b", nickname="职人 B"),
            DimStorePoiMapping(
                store_id="store-a",
                poi_id="poi-a",
                poi_name="门店 A",
                mapping_source="test",
                is_primary=True,
            ),
            DimSkuProductRule(sku_id="sku-jc-1", product_scope="精诚养车"),
            DimSkuProductRule(sku_id="sku-jc-2", product_scope="精诚养车"),
            DimSkuProductRule(sku_id="sku-jc-3", product_scope="精诚养车"),
            DimSkuProductRule(sku_id="sku-jc-4", product_scope="精诚养车"),
            DimSkuProductRule(sku_id="sku-other", product_scope="其他品牌"),
            RawAwemeBinding(
                binding_key="professional-a-binding:poi-a",
                account_id="professional-a-binding",
                douyin_nickname="职人 A2",
                poi_id="poi-a",
                binding_status="active",
            ),
            RawDouyinOrder(
                order_id="order-a-store",
                sku_id="sku-jc-1",
                owner_account_id="store-a-account",
                sale_channel_normalized="other",
                sale_time=timestamp,
                updated_at=timestamp,
            ),
            RawDouyinOrder(
                order_id="order-a-professional",
                sku_id="sku-jc-2",
                owner_account_id="professional-a",
                sale_channel_normalized="live",
                sale_time=timestamp + timedelta(hours=1),
                updated_at=timestamp + timedelta(hours=1),
            ),
            RawDouyinOrder(
                order_id="order-b-professional",
                sku_id="sku-jc-3",
                owner_account_id="professional-b",
                sale_channel_normalized="short_video",
                sale_time=timestamp + timedelta(hours=2),
                updated_at=timestamp + timedelta(hours=2),
            ),
            RawDouyinOrder(
                order_id="order-a-binding-professional",
                sku_id="sku-jc-4",
                owner_account_id="professional-a-binding",
                sale_channel_normalized="other",
                sale_time=timestamp + timedelta(hours=3),
                updated_at=timestamp + timedelta(hours=3),
            ),
            RawDouyinOrder(
                order_id="order-a-other-brand",
                sku_id="sku-other",
                owner_account_id="store-a-account",
                sale_channel_normalized="other",
                sale_time=timestamp + timedelta(hours=4),
                updated_at=timestamp + timedelta(hours=4),
            ),
            RawDouyinOrder(
                order_id="lead-order-a-1",
                sku_id="sku-jc-1",
                owner_account_id="unrelated-account",
                sale_time=timestamp,
                updated_at=timestamp,
            ),
            RawDouyinOrder(
                order_id="lead-order-a-2",
                sku_id="sku-jc-1",
                owner_account_id="unrelated-account",
                sale_time=timestamp,
                updated_at=timestamp,
            ),
            RawDouyinOrder(
                order_id="lead-order-b-1",
                sku_id="sku-jc-1",
                owner_account_id="unrelated-account",
                sale_time=timestamp,
                updated_at=timestamp,
            ),
            ClueAssignmentRound(
                assignment_round_id="round-a-1",
                order_id="lead-order-a-1",
                round_status="active_followed",
                execution_mode="formal",
                assigned_store_id="store-a",
                assigned_at=timestamp,
                verified_at=timestamp + timedelta(hours=2),
                verified_store_id="store-a",
            ),
            ClueAssignmentRound(
                assignment_round_id="round-a-2",
                order_id="lead-order-a-2",
                round_status="active_unfollowed",
                execution_mode="formal",
                assigned_store_id="store-a",
                assigned_at=timestamp + timedelta(days=1),
            ),
            ClueAssignmentRound(
                assignment_round_id="round-b-1",
                order_id="lead-order-b-1",
                round_status="closed_order_verified",
                execution_mode="formal",
                assigned_store_id="store-b",
                assigned_at=timestamp + timedelta(days=2),
            ),
            ClueFollowUpRecord(
                follow_up_record_id="follow-a-1",
                order_id="lead-order-a-1",
                assignment_round_id="round-a-1",
                round_no=1,
                assigned_store_id="store-a",
                follow_result="appointment",
                created_at=timestamp + timedelta(hours=3),
            ),
            SettlementOrderDetail(
                coupon_id="coupon-b-1",
                order_id="lead-order-b-1",
                product_type="保养",
                is_verified=True,
                verify_time=timestamp + timedelta(days=3),
                verify_store_id="store-b",
            ),
        ]
    )
    db_session.commit()

    report = build_douyin_ranking_report(
        db_session,
        period_start=timestamp - timedelta(hours=1),
        period_end=timestamp + timedelta(days=31),
        level="area",
    )

    row = report["rows"][0]
    assert row["order_count"] == 4
    assert row["order_average"] == 2.0
    assert row["follow_numerator"] == 1
    assert row["follow_denominator"] == 3
    assert row["verification_numerator"] == 2
    assert row["verification_denominator"] == 3


def test_ranking_can_group_by_business_group(db_session) -> None:
    db_session.add_all(
        [
            DimStore(
                store_id="store-group",
                store_name="集团门店",
                service_store_code="SVC-GROUP",
                is_active=True,
            ),
            DimStoreOrgAssignment(
                service_store_code="SVC-GROUP",
                group_code="G-001",
                group_name="集团一",
                service_center_name="中心一",
                district_name="大区一",
                area_name="区域一",
            ),
        ]
    )
    db_session.commit()

    report = build_douyin_ranking_report(
        db_session,
        period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        level="group",
    )

    assert report["rows"][0]["name"] == "集团一"
    assert report["rows"][0]["store_count"] == 1
