"""Bounded, public filter metadata for CSV response headers.

Query filters remain untouched. Expanded authorization and organization scopes
belong on the server, not in a response header whose size grows with access.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


MAX_EXPORT_FILTER_HEADER_BYTES = 1024
_PRIVATE_FILTER_KEYS = frozenset(
    {"scope_store_ids", "organization_store_ids", "page", "page_size", "pageSize"}
)


def export_filter_header(filters: Mapping[str, Any]) -> str:
    """Serialize public filter metadata within a fixed ASCII byte budget.

    Collection filters are described by count rather than echoing bulk IDs.
    Oversized scalar metadata is explicitly omitted, never silently truncated.
    This serialization does not modify filters used for queries or audit rows.
    """
    public_filters = {
        key: {"count": len(value)} if isinstance(value, (list, tuple, set)) else value
        for key, value in filters.items()
        if key not in _PRIVATE_FILTER_KEYS and value not in (None, "", "all")
    }
    encoded = json.dumps(public_filters, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    if len(encoded) <= MAX_EXPORT_FILTER_HEADER_BYTES:
        return encoded
    return json.dumps(
        {"metadata_omitted": True, "filter_count": len(public_filters)},
        separators=(",", ":"),
    )
