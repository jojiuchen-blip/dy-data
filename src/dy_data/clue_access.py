"""Shared data-scope policy for authenticated clue-operation actors."""

from collections.abc import Mapping
from typing import Any


def can_access_clue_store(actor: Mapping[str, Any], store_id: Any) -> bool:
    """Require an explicit scope; a role alone never grants all-store access."""
    role = str(actor.get("role") or "").strip()
    target = str(store_id or "").strip()
    if role not in {"admin", "highest_admin", "store"} or not target:
        return False
    scope_mode = actor.get("store_scope_mode")
    # Environment administrators are an explicit, authenticated global identity.
    if actor.get("auth_type") == "env_admin" and actor.get("is_highest_admin"):
        scope_mode = "all"
    if scope_mode == "all":
        return role in {"admin", "highest_admin"}
    if scope_mode != "specified":
        return False
    store_ids = actor.get("store_ids") or ()
    if not isinstance(store_ids, (list, tuple, set, frozenset)):
        return False
    return target in {str(value).strip() for value in store_ids if value is not None}
