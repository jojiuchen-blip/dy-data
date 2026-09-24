"""Shared product partition for clue indicators and clue detail queries."""
from sqlalchemy import true

PRODUCT_SCOPE_LABELS = {"all": "全部商品", "jingcheng": "精诚养车", "byd": "比亚迪本品"}


def validate_product_scope(scope: str) -> str:
    if scope not in PRODUCT_SCOPE_LABELS:
        raise ValueError("请选择全部商品、精诚养车或比亚迪本品")
    return scope


def scope_predicate(scope: str, membership):
    """Membership must be a non-null boolean (EXISTS or explicitly coalesced)."""
    validate_product_scope(scope)
    return true() if scope == "all" else membership if scope == "jingcheng" else ~membership
