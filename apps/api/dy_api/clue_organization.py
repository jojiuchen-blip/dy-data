"""Search and resolve clue organization filters using the authorized current catalog."""
import json
from types import SimpleNamespace

from apps.api.dy_api.account_scope import ORG_SCOPE_FIELDS, account_store_catalog

LEVEL_FIELDS = {**ORG_SCOPE_FIELDS, "store": ("store_id",)}


def catalog(session, scope_store_ids):
    return account_store_catalog(session, SimpleNamespace(
        has_global_data_access=scope_store_ids is None, store_ids=scope_store_ids or ()))


def organization_options(session, scope_store_ids, *, level, q="", selected_key="", limit=50):
    if level not in LEVEL_FIELDS:
        raise ValueError("请选择有效的组织层级")
    fields = LEVEL_FIELDS[level]
    options = {}
    for row in catalog(session, scope_store_ids):
        path = [row[field] for field in fields]
        if not all(path):
            continue
        key = json.dumps(path, ensure_ascii=False, separators=(",", ":"))
        label = f"{row['store_name']} / {row['store_id']}" if level == "store" else " / ".join(path)
        if q.casefold() in label.casefold() or key == selected_key:
            options[key] = {"value": key, "label": label}
    ordered = sorted(options.values(), key=lambda item: item["label"])
    chosen = options.get(selected_key)
    result = ordered[:limit]
    if chosen and chosen not in result:
        result = [chosen, *result[:limit - 1]]
    return result


def organization_filter_store_ids(session, scope_store_ids, *, level, key):
    if level == "all":
        if key:
            raise ValueError("全部层级不能指定组织")
        return scope_store_ids
    if level not in LEVEL_FIELDS:
        raise ValueError("请选择有效的组织层级")
    if not key:
        return scope_store_ids
    try:
        path = json.loads(key)
    except (TypeError, ValueError) as exc:
        raise ValueError("组织路径格式错误") from exc
    fields = LEVEL_FIELDS[level]
    if not isinstance(path, list) or len(path) != len(fields) or not all(isinstance(p, str) and p for p in path):
        raise ValueError("请选择完整的组织路径")
    return tuple(row["store_id"] for row in catalog(session, scope_store_ids)
                 if all(row[field] == value for field, value in zip(fields, path)))
