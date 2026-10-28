"""Explicit synthetic month-end evidence for scenarios extending into October."""
from datetime import timedelta

from apps.worker import account_qualification as qualification


def binding(account="owner-dual", *, kind="子机构门店号", status="认证成功", poi="poi-sale", douyin="dy-owner"):
    return dict(account_id=account, douyin_id=douyin, poi_id=poi, raw_payload={
        "account_id": account, "账号类型": kind, "抖音号绑定状态": status,
        "认证信息": "任意真实企业名称或商家认证账号",
    })


def observe(session, records=None, *, month="2026-10", offset=60, duration=10, complete=True):
    _, cutoff = qualification.month_bounds(month)
    rows = records if records is not None else [binding()]
    identity = qualification.start_observation(session, source_run_id="synthetic-month-end",
        started_at=cutoff - timedelta(minutes=offset))
    qualification.complete_observation(session, identity,
        qualification.BindingRecords(rows, source_type="synthetic", proof={"complete": complete, "record_count": len(rows)}),
        ended_at=cutoff - timedelta(minutes=offset) + timedelta(minutes=duration))
    return identity


def seed_month_qualification(session, month="2026-10", records=None):
    existing = session.scalar(qualification.select(qualification.Version).where(qualification.Version.business_month == month))
    if existing is not None:
        return existing
    observe(session, records, month=month)
    return qualification.freeze_month(session, month, now=qualification.month_bounds(month)[1])
