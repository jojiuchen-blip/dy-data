"""Exact catalog classification rules, independent of ranking membership."""

JINGCHENG_PRODUCT_SCOPE = "精诚养车"
JINGCHENG_PRODUCT_TYPE = "精诚养车"


def synced_product_type(product_scope: str, current_type: str) -> str:
    """Maintain the confirmed legacy scope conversion during platform sync.

    Scope is an internal membership fact. Never infer it from a type or name.
    Non-target classifications remain under manual administration.
    """
    if product_scope == JINGCHENG_PRODUCT_SCOPE:
        return JINGCHENG_PRODUCT_TYPE
    return current_type
