from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, func

from apps.api.dy_api.ranking_schema_v1 import metadata, org_history, eligibility, lead_bindings


AT = datetime(2026, 8, 31, 16, tzinfo=timezone.utc)


def organization(center="中心甲"):
    return dict(store_id="store-a", service_store_code="CODE-A", store_name="门店甲",
                group_name="集团甲", group_key="G1", service_center_name=center,
                district_name="大区甲", area_name="区域甲")


@pytest.fixture
def config_db(db_session):
    metadata.create_all(db_session.bind)
    return db_session


def publish(session, rows=None, codes=None, at=AT):
    from apps.api.dy_api.ranking_configuration import publish_configuration
    return publish_configuration(session, organizations=rows or [organization()],
                                 eligible_codes=codes if codes is not None else ["CODE-A"],
                                 effective_from=at)


def test_configuration_update_preserves_history_and_first_assignment_pin(config_db):
    first = publish(config_db)
    config_db.execute(lead_bindings.insert().values(lead_key="old-lead", first_assigned_at=AT,
                       mapping_version=first["mapping_version"]))
    second = publish(config_db, [organization("中心乙")], at=AT + timedelta(days=10))
    assert first["mapping_version"] != second["mapping_version"]
    assert config_db.scalar(select(func.count()).select_from(org_history)) == 2
    assert config_db.scalar(select(lead_bindings.c.mapping_version)) == first["mapping_version"]
    assert config_db.scalar(select(org_history.c.service_center_name).where(
        org_history.c.mapping_version == first["mapping_version"])) == "中心甲"


def test_identical_configuration_is_idempotent_but_reverting_creates_version(config_db):
    first = publish(config_db)
    again = publish(config_db, at=AT + timedelta(days=1))
    assert again == first
    publish(config_db, [organization("中心乙")], at=AT + timedelta(days=2))
    reverted = publish(config_db, at=AT + timedelta(days=3))
    assert reverted["mapping_version"] != first["mapping_version"]
    assert config_db.scalar(select(func.count()).select_from(org_history)) == 3


@pytest.mark.parametrize("invalid", ["unknown_eligibility", "duplicate_store", "duplicate_code", "missing_org", "backdated"])
def test_invalid_full_configuration_writes_nothing(config_db, invalid):
    publish(config_db)
    rows, codes, at = [organization()], ["CODE-A"], AT + timedelta(days=1)
    if invalid == "unknown_eligibility":
        codes = ["UNKNOWN"]
    elif invalid == "duplicate_store":
        rows.append(dict(organization(), service_store_code="CODE-B"))
    elif invalid == "duplicate_code":
        rows.append(dict(organization(), store_id="store-b"))
    elif invalid == "missing_org":
        rows[0]["area_name"] = ""
    else:
        rows[0]["area_name"] = "改动"
        at = AT - timedelta(seconds=1)
    with pytest.raises(ValueError):
        publish(config_db, rows, codes, at)
    assert config_db.scalar(select(func.count()).select_from(org_history)) == 1
    assert config_db.scalar(select(func.count()).select_from(eligibility)) == 1


def test_composite_organization_keys_disambiguate_repeated_district_names(config_db):
    rows = [organization(), dict(organization("中心乙"), store_id="store-b", service_store_code="CODE-B")]
    publish(config_db, rows, ["CODE-A", "CODE-B"])
    result = config_db.execute(select(org_history)).mappings().all()
    assert len({row["district_key"] for row in result}) == 2
    assert len({row["area_key"] for row in result}) == 2


@pytest.mark.parametrize("conflict", [False, True])
def test_noneligible_duplicate_code_requires_identical_organization(config_db, conflict):
    rows = [organization(), dict(organization("冲突中心" if conflict else "中心甲"), store_id="store-b"),
            dict(organization(), store_id="store-c", service_store_code="CODE-C")]
    if conflict:
        with pytest.raises(ValueError, match="重复服务店编码"):
            publish(config_db, rows, ["CODE-C"])
    else:
        publish(config_db, rows, ["CODE-C"])
        assert config_db.scalar(select(func.count()).select_from(org_history)) == 3
        assert config_db.scalar(select(func.count()).select_from(eligibility)) == 1
