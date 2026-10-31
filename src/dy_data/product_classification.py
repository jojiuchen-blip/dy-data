"""Exact catalog classification rules, independent of ranking membership."""

JINGCHENG_PRODUCT_SCOPE = "精诚养车"
JINGCHENG_PRODUCT_TYPE = "精诚养车"
OFFICIAL_PRODUCT_TYPE = "售后官方"


def commission_product_type(current_type: str, *, participates: bool,
                            official: bool = False) -> str:
    """Classify an evidenced commission SKU without changing membership.

    The caller must establish participation by exact SKU and formal rules.
    Unknown and nonparticipating products retain their existing classification.
    """
    if not participates:
        return current_type
    if official or current_type == OFFICIAL_PRODUCT_TYPE:
        return OFFICIAL_PRODUCT_TYPE
    return JINGCHENG_PRODUCT_TYPE


def synced_product_type(product_scope: str, current_type: str) -> str:
    """Maintain the confirmed legacy scope conversion during platform sync.

    Scope is an internal membership fact. Never infer it from a type or name.
    Non-target classifications remain under manual administration.
    """
    if current_type == OFFICIAL_PRODUCT_TYPE:
        return OFFICIAL_PRODUCT_TYPE
    if product_scope == JINGCHENG_PRODUCT_SCOPE:
        return JINGCHENG_PRODUCT_TYPE
    return current_type
