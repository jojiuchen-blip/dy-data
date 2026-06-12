from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import DimAwemeAccount, RawAwemeBinding
from apps.worker.collectors.aweme_bindings import collect_aweme_bindings


class FakeAwemeBindingClient:
    def __init__(self, bind_status: str = "active"):
        self.bind_status = bind_status

    def query_craftsman_bind_info(self, *, cursor=None, size: int = 50):
        return {
            "data": {
                "openapi_merchat_craftsman_info": [
                    {
                        "aweme_short_id": "dy-1",
                        "nickname": "Owner One",
                        "craftsman_uid": "owner-1",
                        "poi_id": "poi-1",
                        "poi_account_name": "Store One",
                        "account_id": "merchant-1",
                        "account_name": "Merchant One",
                        "bind_status": self.bind_status,
                    }
                ],
                "has_more": False,
            }
        }


def count(session: Session, model: type) -> int:
    value = session.scalar(select(func.count()).select_from(model))
    assert value is not None
    return value


def test_collect_aweme_bindings_upserts_raw_and_dimension_rows(db_session: Session):
    first = collect_aweme_bindings(db_session, FakeAwemeBindingClient(), source_run_id="run-aweme")
    second = collect_aweme_bindings(db_session, FakeAwemeBindingClient("inactive"), source_run_id="run-aweme")

    assert first.fetched == 1
    assert first.upserted == 2
    assert second.upserted == 2
    assert count(db_session, RawAwemeBinding) == 1
    assert count(db_session, DimAwemeAccount) == 1

    binding = db_session.get(RawAwemeBinding, "owner-1:dy-1:poi-1")
    assert binding is not None
    assert binding.douyin_id == "dy-1"
    assert binding.douyin_nickname == "Owner One"
    assert binding.account_id == "owner-1"
    assert binding.account_name == "Merchant One"
    assert binding.poi_id == "poi-1"
    assert binding.binding_status == "inactive"
    assert binding.raw_payload["craftsman_uid"] == "owner-1"

    account = db_session.get(DimAwemeAccount, "owner-1")
    assert account is not None
    assert account.nickname == "Owner One"
    assert account.binding_status == "inactive"
