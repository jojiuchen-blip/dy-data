"""Regression coverage for proxy-safe export metadata, independent of row count."""

from copy import deepcopy
import json

import pytest
from starlette.responses import StreamingResponse

from apps.api.dy_api.export_metadata import MAX_EXPORT_FILTER_HEADER_BYTES, export_filter_header


@pytest.mark.parametrize("scope_size", [0, 1, 170, 1000, 10000])
def test_export_metadata_never_echoes_internal_scope_or_mutates_query(scope_size: int) -> None:
    scope = [f"{number:020d}" for number in range(scope_size)]
    filters = {
        "scope_store_ids": scope,
        "organization_store_ids": scope,
        "assigned_date_start": "2099-01-01",
        "store_display_status": "待跟进",
        "page": 99,
        "page_size": 100,
    }
    before = deepcopy(filters)
    header = export_filter_header(filters)
    assert json.loads(header) == {
        "assigned_date_start": "2099-01-01",
        "store_display_status": "待跟进",
    }
    assert len(header.encode("ascii")) <= MAX_EXPORT_FILTER_HEADER_BYTES
    assert filters == before
    response = StreamingResponse(iter([b"\xef\xbb\xbfcolumn\r\n"]), headers={"X-Export-Filters": header})
    assert sum(len(key) + len(value) + 4 for key, value in response.raw_headers) < 2048


def test_bulk_selection_metadata_preserves_zero_vs_absent_without_echoing_ids() -> None:
    assert json.loads(export_filter_header({"assigned_store_ids": None})) == {}
    assert json.loads(export_filter_header({"assigned_store_ids": []})) == {"assigned_store_ids": {"count": 0}}
    ids = [f"000000000000000{index:05d}" for index in range(1000)]
    assert json.loads(export_filter_header({"assigned_store_ids": ids})) == {"assigned_store_ids": {"count": 1000}}


def test_oversized_public_metadata_is_explicitly_omitted_and_header_safe() -> None:
    filters = {"q": "中文\r\n" * 1000, "month": "2026-09"}
    header = export_filter_header(filters)
    assert json.loads(header) == {"metadata_omitted": True, "filter_count": 2}
    assert len(header.encode("ascii")) <= MAX_EXPORT_FILTER_HEADER_BYTES
    assert "\r" not in header and "\n" not in header
    assert filters["q"].startswith("中文\r\n")
